"""Read-only dependency probes and bounded synthetic provider tool-cycle tests."""
from __future__ import annotations
import copy,json,os,platform,shutil,subprocess,sys,tempfile,threading,time,uuid
import config,providers
from app_version import VERSION
from coding_tools import atomic,read_json,owner_alive,process_identity
from coding_lsp import LanguageServers
import project_validation

def webview_version():
    if os.name!='nt':return None
    import winreg
    # Enumerate client records: Evergreen product ID may vary by distribution.
    for hive in (winreg.HKEY_CURRENT_USER,winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive,r'SOFTWARE\Microsoft\EdgeUpdate\Clients',0,winreg.KEY_READ|winreg.KEY_WOW64_32KEY) as clients:
                for i in range(winreg.QueryInfoKey(clients)[0]):
                    with winreg.OpenKey(clients,winreg.EnumKey(clients,i)) as key:
                        try:
                            if 'webview2' in winreg.QueryValueEx(key,'name')[0].lower():return winreg.QueryValueEx(key,'pv')[0]
                        except OSError:pass
        except OSError:pass
    return None

def report():
    root=config.application_root();rows=[]
    rows.append(dict(name='WebView2',state='ok' if webview_version() else 'missing',detail=webview_version() or 'Instala o WebView2 Evergreen Runtime.',help='https://developer.microsoft.com/microsoft-edge/webview2/'))
    probes=[('Git',shutil.which('git'),['--version']),('Node.js',shutil.which('node'),['--version']),('Python de desenvolvimento',project_validation.python_runtime(root),['--version']),('PowerShell',shutil.which('powershell.exe') or shutil.which('pwsh'),['-NoProfile','-NonInteractive','-Command','$PSVersionTable.PSVersion.ToString()'])]
    for name,exe,args in probes:
        row=dict(name=name,state='missing',detail='Não encontrado. Opcional para funcionalidades que não o utilizam.')
        if exe:
            try:
                r=subprocess.run([exe,*args],capture_output=True,text=True,timeout=8,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));row.update(state='ok' if r.returncode==0 else 'error',detail=(r.stdout or r.stderr).strip()[:250],path=str(exe))
            except (OSError,subprocess.TimeoutExpired):row.update(state='error',detail='Não foi possível executar o runtime em oito segundos.')
        rows.append(row)
    for lsp in LanguageServers().status():rows.append(dict(name='LSP '+lsp.get('label',lsp['name']),state='ok' if lsp['installed'] else 'missing',detail='Requer os componentes em Ferramentas/_Runtime/lsp e Node portátil.' if lsp.get('source','bundled')=='bundled' else 'Opcional: usa '+lsp['executable']+' se estiver instalado e no PATH.'))
    for label,p in [('Dados da aplicação',root),('Configuração',config.config_dir())]:
        try:
            p.mkdir(parents=True,exist_ok=True)
            with tempfile.TemporaryFile(dir=p):pass
            rows.append(dict(name=label,state='ok',detail=str(p),free_bytes=shutil.disk_usage(p).free))
        except OSError:rows.append(dict(name=label,state='error',detail='Sem acesso de escrita: '+str(p)))
    return dict(version=VERSION,platform=platform.platform(),architecture=platform.machine(),packaged=bool(getattr(sys,'frozen',False)),checks=rows,created_at=time.time(),network_tested=False)

def location(key):
    if not isinstance(key,str) or len(key)!=32 or any(c not in '0123456789abcdef' for c in key):raise ValueError('Diagnóstico inválido.')
    return config.config_dir()/'provider-diagnostics'/(key+'.json')
def load(key):
    data=read_json(location(key))
    if data['state']=='running' and not owner_alive(data):data.update(state='interrupted');atomic(location(key),json.dumps(data).encode())
    return data
def listing():
    rows=[]
    for p in (config.config_dir()/'provider-diagnostics').glob('*.json'):
        try:rows.append(load(p.stem))
        except (OSError,ValueError):pass
    return sorted(rows,key=lambda d:d['created_at'],reverse=True)[:20]

class ProviderTests:
    def __init__(self):self.lock=threading.Lock();self.jobs={};self.closed=False
    def start(self,provider,model,rounds=3,max_tokens=256):
        if type(rounds)is not int or not 1<=rounds<=10:raise ValueError('Escolhe entre uma e dez rondas.')
        if type(max_tokens)is not int or not 64<=max_tokens<=4096:raise ValueError('Limite de saída entre 64 e 4096 tokens por chamada.')
        with self.lock:
            if self.closed or self.jobs:raise ValueError('Já existe um ensaio em execução ou a app está a encerrar.')
            key=uuid.uuid4().hex;cancel=threading.Event();data=dict(id=key,state='running',provider_id=provider['id'],kind=provider['kind'],model_id=model['id'],rounds=rounds,max_tokens=max_tokens,results=[],responses=[],usage={},created_at=time.time(),owner_pid=os.getpid(),owner_identity=process_identity())
            atomic(location(key),json.dumps(data).encode());self.jobs[key]=cancel;threading.Thread(target=self._run,args=(copy.deepcopy(provider),copy.deepcopy(model),data,cancel),daemon=True).start();return data
    def _run(self,provider,model,data,cancel):
        secret=provider.get('api_key','');deadline=time.monotonic()+600
        def save():atomic(location(data['id']),json.dumps(data,ensure_ascii=False).encode())
        def usage(result):
            for k,v in (result.get('usage') or {}).items():
                if isinstance(v,(int,float)):data['usage'][k]=data['usage'].get(k,0)+v
        def observe(result,stage,n):
            reason=str(result.get('finish_reason') or 'unknown')[:120]
            if secret:reason=reason.replace(secret,'[credencial oculta]')
            record=dict(round=n+1,stage=stage,finish_reason=reason,tool_count=len(result.get('tool_calls') or []),content_chars=len(result.get('content') or ''))
            data['responses'].append(record);save();return reason.lower()
        def fail(code,message,n,stage,reason):
            data['failure']=dict(code=code,round=n+1,stage=stage,finish_reason=reason);raise ValueError(message)
        try:
            limit=data['max_tokens'];model.setdefault('defaults',{}).update(max_tokens=limit);adapter=providers.get_chat_adapter(provider['kind'])
            tool=dict(type='function',function=dict(name='diagnostico_eco',description='Devolve o token recebido; não acede ao computador.',parameters=dict(type='object',properties=dict(token=dict(type='string')),required=['token'])))
            for n in range(data['rounds']):
                if cancel.is_set() or time.monotonic()>deadline:break
                token='probe-'+uuid.uuid4().hex[:12];start=time.monotonic();messages=[dict(role='system',content='Ensaio sintético de ferramentas. Chama diagnostico_eco com o token pedido. Depois responde apenas com esse token.'),dict(role='user',content=token)]
                data.update(current_round=n+1,stage='tool');save()
                first=adapter(provider,model,messages,[tool],{'_cancel':cancel,'_on_delta':lambda s:None,'max_tokens':limit});usage(first);reason=observe(first,'tool',n)
                if cancel.is_set():break
                if reason in ('length','max_tokens','max_output_tokens'):fail('output_limit','A resposta atingiu o limite de saída; escolhe um limite maior para este modelo e inicia outro ensaio.',n,'tool',reason)
                if reason not in ('stop','tool_calls','completed','end_turn','tool_use','unknown','stop_sequence'):fail('provider_stop','O provedor terminou a resposta com o motivo: '+reason,n,'tool',reason)
                calls=first.get('tool_calls') or []
                if not calls:fail('no_tool_call','O modelo terminou sem a chamada de eco esperada.',n,'tool',reason)
                if len(calls)!=1 or calls[0].get('name')!='diagnostico_eco' or calls[0].get('arguments')!={'token':token}:fail('unexpected_tool_call','A chamada de eco não corresponde ao nome/argumentos pedidos.',n,'tool',reason)
                messages.extend([first['raw_message'],dict(role='tool',tool_call_id=calls[0]['id'],content=json.dumps(dict(token=token)))])
                if time.monotonic()>deadline:break
                data['stage']='final';save()
                second=adapter(provider,model,messages,None,{'_cancel':cancel,'_on_delta':lambda s:None,'max_tokens':limit});usage(second);reason=observe(second,'final',n)
                if cancel.is_set():break
                if reason in ('length','max_tokens','max_output_tokens'):fail('output_limit','A resposta final atingiu o limite de saída; escolhe um limite maior e inicia outro ensaio.',n,'final',reason)
                if reason not in ('stop','completed','end_turn','unknown','stop_sequence'):fail('provider_stop','O provedor terminou a resposta final com o motivo: '+reason,n,'final',reason)
                if token not in second.get('content','') or second.get('tool_calls'):fail('final_mismatch','A resposta final não confirmou o resultado da ferramenta.',n,'final',reason)
                data['results'].append(dict(round=n+1,state='passed',seconds=round(time.monotonic()-start,3)));save()
            data['state']='cancelled' if cancel.is_set() else 'passed' if len(data['results'])==data['rounds'] else 'limited'
        except Exception as exc:
            data.setdefault('failure',dict(code='provider_error',round=data.get('current_round'),stage=data.get('stage')))
            message=str(exc);data.update(state='cancelled' if cancel.is_set() else 'failed',error=(message.replace(secret,'[credencial oculta]') if secret else message)[:800])
        finally:
            data['finished_at']=time.time()
            with self.lock:
                try:save()
                finally:self.jobs.pop(data['id'],None)
    def cancel(self,key):
        with self.lock:
            if key in self.jobs:self.jobs[key].set()
        return load(key)
    def close(self):
        with self.lock:
            self.closed=True
            for event in self.jobs.values():event.set()
