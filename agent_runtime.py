"""Perfis e tarefas de subagentes, incluindo implementação e validação isoladas."""
from __future__ import annotations
import json,os,queue,threading,uuid
from datetime import datetime,timezone
from pathlib import Path
from coding_tools import atomic,read_json,owner_alive,process_identity
from task_recovery import Journal,location as recovery_location,RESUMABLE

PROFILES={
 'build':dict(label='Implementar',readonly=False,prompt='Implementa e verifica as alterações pedidas. Usa patches e checkpoints; comunica limitações e resultados reais.'),
 'plan':dict(label='Planear',readonly=True,prompt='Analisa o projeto e produz um plano executável. Não alteres ficheiros nem executes comandos. Identifica ficheiros relevantes, decisões e validações.'),
 'review':dict(label='Rever',readonly=True,prompt='Revê código e identifica problemas concretos com caminhos, linhas, impacto e sugestões. Não alteres ficheiros nem executes comandos. Se não encontrares problemas, diz o que verificaste e as limitações.'),
}
READ_TOOLS={'listar_pasta','ler_ficheiro','ler_codigo','pesquisar_ficheiros','pesquisar_conteudo','git_consultar','lsp_diagnosticos','memoria_consultar','skills_listar','skill_carregar','agente_delegar','agentes_tarefas','agente_resultado','projeto_verificacoes','indice_actualizar','codigo_contexto','codigo_semantico','codigo_simbolos','lsp_navegar','contexto_consultar','conhecimento_procurar','conhecimento_ler'}
READ_TOOLS|={'processos_listar','processo_resultado'}
CHILD_TOOLS=READ_TOOLS-{'agente_delegar'}
TASK_PROFILES={'explore':('Explorar','Pesquisa os ficheiros relevantes e devolve factos com caminhos e linhas. Não alteres ficheiros nem executes comandos.'),'plan':('Planear',PROFILES['plan']['prompt']),'review':('Rever',PROFILES['review']['prompt'])}
TASK_PROFILES['build']=('Implementar e verificar em área isolada','Implementa na worktree/cópia indicada. Lê antes de editar, usa patches e LSP. Consulta projeto_verificacoes; executa projeto_validar e corrige as falhas. Se faltarem dependências, projeto_preparar instala-as na área de trabalho, sujeito às aprovações configuradas. Não tens shell genérico nem MCP. A app verifica a proposta antes de concluir e as alterações exigem revisão antes de aplicar ao original.')
BUILD_CHILD_TOOLS=(CHILD_TOOLS-{'git_consultar','agentes_tarefas','agente_resultado'})|{'escrever_ficheiro','aplicar_patch','projeto_validar','projeto_preparar'}

def now():return datetime.now(timezone.utc).isoformat()
def task_dir(meta):return Path(meta)/'agent-tasks'
def task_path(meta,key):
    if not isinstance(key,str) or len(key)!=32 or any(c not in '0123456789abcdef' for c in key):raise ValueError('Tarefa inválida.')
    return task_dir(meta)/(key+'.json')
def save(meta,data):atomic(task_path(meta,data['id']),json.dumps(data,ensure_ascii=False,indent=2).encode('utf-8'))
def get_task(meta,key):
    data=read_json(task_path(meta,key))
    if data.get('id')!=key:raise ValueError('Tarefa inválida.')
    if data['state'] in ('queued','running','cancelling') and not owner_alive(data):
        data.update(state='interrupted',updated_at=now(),message='A aplicação encerrou antes de concluir esta tarefa.');save(meta,data)
    journal=recovery_location(meta,key)
    if journal.exists():
        details=Journal(journal).describe();data['recovery']={k:details[k] for k in ('state','attempt','updated_at','unknown','action_count')}
        data['progress']=details.get('progress',{})
    return data
def list_tasks(meta):
    folder=task_dir(meta)
    if not folder.is_dir():return []
    result=[]
    for path in folder.glob('*.json'):
        try:data=get_task(meta,path.stem)
        except (OSError,ValueError):continue
        row={k:v for k,v in data.items() if k not in ('result','steps','progress')}
        if row.get('recovery'):row['recovery']={k:v for k,v in row['recovery'].items() if k!='unknown'}|{'unknown_count':len(row['recovery'].get('unknown',[]))}
        result.append(row)
    return sorted(result,key=lambda t:t['created_at'],reverse=True)[:100]

class AgentTasks:
    def __init__(self,runner):
        self.runner=runner;self.queue=queue.Queue(maxsize=16);self.lock=threading.RLock();self.workers=[];self.jobs={};self.closed=False
    def submit(self,meta,profile,prompt,payload):
        if profile not in TASK_PROFILES:raise ValueError('Subagente inválido. Escolhe explore, plan, review ou build.')
        if not isinstance(prompt,str) or not prompt.strip() or len(prompt)>12000:raise ValueError('A tarefa precisa de texto até 12 000 caracteres.')
        with self.lock:
            if self.closed:raise ValueError('As tarefas estão a encerrar.')
            if sum(not job['event'].is_set() and job['data']['state'] in ('queued','running','cancelling') for job in self.jobs.values())>=8:raise ValueError('Já existem oito tarefas pendentes. Aguarda ou cancela uma tarefa.')
            key=uuid.uuid4().hex;data=dict(id=key,profile=profile,title=prompt.strip().splitlines()[0][:120],prompt=prompt.strip(),state='queued',created_at=now(),updated_at=now(),owner_pid=os.getpid(),owner_identity=process_identity(),provider_id=payload['provider']['id'],model_id=payload['model']['id'],workspace=str(payload['workspace']),readonly=profile!='build',usage={},attempt=1,origin_action=payload.get('origin_action'))
            job=dict(meta=str(meta),data=data,payload=payload,event=threading.Event(),done=threading.Event(),persist=True)
            save(meta,data);self.jobs[key]=job
            if not self.workers:
                for _ in range(2):
                    thread=threading.Thread(target=self._worker,daemon=True);self.workers.append(thread);thread.start()
            try:self.queue.put_nowait(job)
            except queue.Full:
                data.update(state='error',message='Fila de tarefas cheia.');save(meta,data);self.jobs.pop(key,None);raise ValueError('Fila de tarefas cheia.')
            return dict(data)
    def resume(self,meta,key,payload):
        with self.lock:
            if self.closed or key in self.jobs:raise ValueError('A tarefa está ativa ou a aplicação está a encerrar.')
            if len(self.jobs)>=8:raise ValueError('Já existem oito tarefas pendentes.')
            old=get_task(meta,key)
            if old['state'] not in RESUMABLE:raise ValueError('A tarefa não pode ser retomada neste estado.')
            if Path(old['workspace']).resolve()!=Path(payload['workspace']).resolve():raise ValueError('A tarefa pertence a outro workspace.')
            attempt=int(old.get('attempt',1))+1
            if attempt>21:raise ValueError('Limite de vinte retomas atingido.')
            archive=Path(meta)/'agent-attempts'/key/(str(attempt-1)+'.json');atomic(archive,json.dumps(old,ensure_ascii=False,indent=2).encode())
            data={k:v for k,v in old.items() if k not in ('recovery','progress','result','steps','proposal','validation')};data.update(state='queued',owner_pid=os.getpid(),owner_identity=process_identity(),attempt=attempt,updated_at=now(),provider_id=payload['provider']['id'],model_id=payload['model']['id'],usage={},message='Retoma solicitada na interface.')
            job=dict(meta=str(meta),data=data,payload=payload,event=threading.Event(),done=threading.Event(),persist=True);payload['resume']=True
            save(meta,data);self.jobs[key]=job
            if not self.workers:
                for _ in range(2):
                    thread=threading.Thread(target=self._worker,daemon=True);self.workers.append(thread);thread.start()
            try:self.queue.put_nowait(job)
            except queue.Full:
                self.jobs.pop(key,None);save(meta,old);raise ValueError('Fila de tarefas cheia.')
            return dict(data)
    def _worker(self):
        while True:
            job=self.queue.get()
            if job is None:return
            data=job['data'];event=job['event']
            try:
                with self.lock:
                    if event.is_set():continue
                    data.update(state='running',updated_at=now());self._save_job(job)
                job['payload']['_should_persist']=lambda j=job:j.get('persist',True)
                result=self.runner(job['payload'],data,event)
                with self.lock:
                    data.update(result,state='cancelled' if event.is_set() else result.get('state','completed'),updated_at=now());self._save_job(job)
            except Exception as exc:
                with self.lock:
                    # Provider errors can contain a request/response; never expose credentials.
                    secret=job['payload']['provider'].get('api_key','');message=str(exc)
                    if secret:message=message.replace(secret,'[credencial oculta]')
                    data.update(state='cancelled' if event.is_set() else 'error',message=message[:3000],updated_at=now())
                    try:self._save_job(job)
                    except OSError:pass
            finally:
                job['done'].set()
                with self.lock:self.jobs.pop(data['id'],None)
                self.queue.task_done()
    def _save_job(self,job):
        if job.get('persist'):save(job['meta'],job['data'])
    def detach_context(self,meta):
        with self.lock:
            for job in self.jobs.values():
                if Path(job['meta']).resolve()==Path(meta).resolve():job['persist']=False;job['event'].set()
    def wait(self,meta,key,seconds=0):
        with self.lock:job=self.jobs.get(key)
        if job and Path(job['meta']).resolve()==Path(meta).resolve():job['done'].wait(max(0,min(10,int(seconds))))
        return get_task(meta,key)
    def cancel(self,meta,key):
        with self.lock:
            job=self.jobs.get(key)
            if not job or Path(job['meta']).resolve()!=Path(meta).resolve():return get_task(meta,key)
            job['event'].set();data=job['data'];data.update(state='cancelled' if data['state']=='queued' else 'cancelling',updated_at=now());save(meta,data);return dict(data)
    def close(self):
        with self.lock:
            self.closed=True
            for job in list(self.jobs.values()):
                job['event'].set();job['data'].update(state='interrupted',message='A aplicação encerrou.',updated_at=now())
                try:save(job['meta'],job['data'])
                except OSError:pass
            for _ in self.workers:
                try:self.queue.put_nowait(None)
                except queue.Full:break
