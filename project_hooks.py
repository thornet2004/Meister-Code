"""Project lifecycle rules. Configuration is inert until its exact bytes are activated."""
from __future__ import annotations
import fnmatch,json,subprocess,time,uuid
from pathlib import Path
from coding_tools import atomic,digest,read_json,owner_alive,process_identity
from command_jobs import load as load_command
from workspace_snapshot import WorkspaceSnapshot

EVENTS=('before_tool','after_tool','task_end')
DEFAULT={'version':1,'deny_tools':[],'hooks':[]}

def parse(text):
    if not isinstance(text,str) or len(text.encode('utf-8'))>65536:raise ValueError('Configuração limitada a 64 KiB.')
    data=json.loads(text)
    if not isinstance(data,dict) or data.get('version')!=1:raise ValueError('A configuração requer version: 1.')
    deny=data.get('deny_tools',[]);hooks=data.get('hooks',[])
    if not isinstance(deny,list) or len(deny)>50 or any(not isinstance(s,str) or not s or len(s)>100 for s in deny):raise ValueError('deny_tools deve conter até 50 padrões de nomes de ferramentas.')
    if not isinstance(hooks,list) or len(hooks)>20:raise ValueError('Máximo de 20 hooks.')
    ids=set()
    for h in hooks:
        if not isinstance(h,dict):raise ValueError('Hook inválido.')
        key=h.get('id');argv=h.get('argv');event=h.get('event');pattern=h.get('tool','*');cwd=h.get('cwd','.')
        if not isinstance(key,str) or not key or len(key)>64 or key in ids:raise ValueError('Cada hook requer um id único (até 64 caracteres).')
        ids.add(key)
        if event not in EVENTS or not isinstance(pattern,str) or not pattern or len(pattern)>100:raise ValueError('Evento ou filtro do hook inválido.')
        if not isinstance(argv,list) or not argv or len(argv)>100 or any(not isinstance(a,str) or not a or '\0' in a or len(a)>10000 for a in argv):raise ValueError('argv deve ser uma lista de argumentos não vazios.')
        if not isinstance(cwd,str) or Path(cwd).is_absolute() or '..' in Path(cwd).parts:raise ValueError('cwd tem de ser relativo ao projeto, sem .. .')
        if type(h.get('timeout',60)) is not int or not 1<=h.get('timeout',60)<=300:raise ValueError('Timeout entre 1 e 300 segundos.')
        if h.get('on_failure','block') not in ('block','warn'):raise ValueError('on_failure: block ou warn.')
        if type(h.get('repeat_on_resume',False)) is not bool:raise ValueError('repeat_on_resume deve ser booleano.')
    return dict(version=1,deny_tools=deny,hooks=hooks)

def configuration(root):
    root=Path(root).resolve();p=root/'.meister/hooks.json'
    if not p.exists():return json.dumps(DEFAULT,indent=2),'',False
    if not p.resolve().is_relative_to(root) or p.stat().st_size>65536:raise ValueError('Ficheiro de hooks fora do projeto ou demasiado grande.')
    raw=p.read_bytes();text=raw.decode('utf-8-sig');parse(text);return text,digest(raw),True

def trust_path(meta):return Path(meta)/'hook-trust.json'
def status(root,meta):
    text,sha,exists=configuration(root)
    try:trust=read_json(trust_path(meta))
    except (OSError,ValueError):trust={}
    active=bool(exists and trust.get('sha256')==sha and trust.get('workspace')==str(Path(root).resolve()))
    return dict(text=text,sha256=sha,exists=exists,active=active,plan=parse(text) if active else dict(DEFAULT))

def activate(root,meta,text):
    parse(text);root=Path(root).resolve();p=root/'.meister/hooks.json'
    if not p.resolve().is_relative_to(root):raise ValueError('Configuração fora do projeto.')
    atomic(p,text.encode('utf-8'));atomic(trust_path(meta),json.dumps(dict(workspace=str(root),sha256=digest(text.encode('utf-8')))).encode())
    return status(root,meta)

def listing(meta):
    rows=[]
    for p in (Path(meta)/'hook-runs').glob('*.json'):
        try:
            d=read_json(p)
            if d['state']=='running' and not owner_alive(d):d['state']='interrupted'
            rows.append(d)
        except (OSError,ValueError,KeyError):continue
    return sorted(rows,key=lambda d:d['created_at'],reverse=True)[:50]

def denied(plan,name):return any(fnmatch.fnmatchcase(name,p) for p in plan.get('deny_tools',[]))

def pending(plan,journal):
    """Failed mandatory hooks from an earlier attempt must not vanish on resume."""
    if not journal:return []
    data=journal.load();latest={}
    for action in data['actions']:
        if action['name']!='project_hook':continue
        try:
            args=json.loads(action.get('arguments_preview','{}'));key=(args['id'],args['event'],args['tool'],args.get('trigger',''))
            latest[key]=(args,action)
        except (ValueError,KeyError):continue
    rows=[]
    for args,action in latest.values():
        if action['attempt']>=data['attempt'] or action.get('outcome') in ('completed','not_run'):continue
        try:state=json.loads(action.get('output_preview','{}')).get('state',action.get('outcome'))
        except ValueError:state=action.get('outcome')
        if state=='completed':continue
        h=next((h for h in plan.get('hooks',[]) if h['id']==args['id'] and h['event']==args['event']),None)
        if h and h['event']!='task_end' and h.get('on_failure','block')=='block':rows.append((h,args))
    return rows

def run(plan,event,name,root,meta,commands,ctx,steps,approve,cancel):
    """No model arguments are interpolated into commands; no recursive tool dispatch."""
    if ctx.get('readonly') or not ctx.get('on'):return True
    journal=ctx.get('_recovery_journal');ok=True
    for h in plan.get('hooks',[]):
        if h['event']!=event or not fnmatch.fnmatchcase(name,h.get('tool','*')):continue
        if cancel.is_set():return False
        if journal and journal.unknown():
            steps.append(dict(kind='hook',title='Hook bloqueado: '+h['id'],body='Operações com resultado desconhecido; usa a recuperação.',ok=False));return False
        call=dict(name='project_hook',arguments=dict(id=h['id'],event=event,tool=name,configuration=digest(json.dumps(h,sort_keys=True).encode()),trigger=ctx.get('_hook_trigger','')))
        previous=journal.previous_effect(call) if journal and not h.get('repeat_on_resume',False) else None
        if previous:
            try:passed=json.loads(previous.get('output_preview','{}')).get('state')=='completed'
            except ValueError:passed=False
            passed=passed or previous.get('outcome')=='completed'
            steps.append(dict(kind='hook',title=event+' / '+h['id'],body='Resultado anterior reutilizado na retoma; o hook não foi repetido. '+previous.get('output_preview',''),ok=passed))
            if not passed and h.get('on_failure','block')=='block':return False
            continue
        cwd=(Path(root)/h.get('cwd','.')).resolve()
        import os
        key=uuid.uuid4().hex;record=dict(id=key,hook=h['id'],event=event,tool=name,workspace=str(root),argv=h['argv'],created_at=time.time(),state='running',owner_pid=os.getpid(),owner_identity=process_identity());p=Path(meta)/'hook-runs'/(key+'.json')
        def save():atomic(p,json.dumps(record,ensure_ascii=False).encode())
        action=None
        try:
            save()
            if journal:action=journal.begin(call,True)
            if not cwd.is_relative_to(Path(root).resolve()) or not cwd.is_dir():record.update(state='invalid',output='Pasta do hook inexistente ou fora do projeto.')
            elif not approve(h):record.update(state='denied',output='Execução recusada.')
            elif cancel.is_set():record.update(state='cancelled')
            else:
                job=commands.start(meta,subprocess.list2cmdline(h['argv']),cwd,h.get('timeout',60),WorkspaceSnapshot(meta,root,'Hook: '+h['id']),argv=h['argv'],origin_action=action)
                record['job_id']=job['id'];save()
                while True:
                    result=load_command(meta,job['id'])
                    if result['state'] not in ('starting','running','cancelling'):break
                    if cancel.wait(.1):commands.cancel(meta,job['id'])
                record.update(state=result['state'],returncode=result.get('returncode'),output=(result.get('output') or result.get('message') or '')[-12000:])
                if result.get('checkpoint',{}).get('file_count'):
                    ctx['_workspace_changed']=True
                    if journal:journal.code_changed()
            if action:journal.returned(action,json.dumps({k:record.get(k) for k in ('id','hook','event','state','returncode','job_id')},ensure_ascii=False))
        except Exception as exc:
            record.update(state='error',output=str(exc))
            if action:journal.failed(action,str(exc))
        finally:
            record['finished_at']=time.time();save()
        passed=record['state']=='completed';steps.append(dict(kind='hook',title=event+' / '+h['id'],body=json.dumps(record,ensure_ascii=False),ok=passed))
        if not passed and h.get('on_failure','block')=='block':ok=False;break
    return ok
