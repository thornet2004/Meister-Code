"""Descoberta de verificações e execução persistente, sem comandos inventados pelo modelo."""
from __future__ import annotations
import json,os,re,shutil,subprocess,sys,threading,time,uuid
from pathlib import Path
import config
from coding_tools import atomic,digest,files,read,read_json,owner_alive,process_identity
from command_jobs import load as load_command
from workspace_snapshot import WorkspaceSnapshot

CODE_EXTENSIONS={'.py','.pyi','.js','.jsx','.ts','.tsx','.mjs','.cjs','.rs','.go','.java','.cs','.cpp','.c','.h','.hpp','.html','.css','.scss','.json','.toml','.yaml','.yml','.sh','.ps1','.sql','.vue','.svelte','.kt','.dart','.swift','.rb','.php','.xml','.cmake'}
def is_code_change(path):
    p=Path(path);return p.suffix.lower() in CODE_EXTENSIONS or p.name in {'requirements.txt','requirements-dev.txt','CMakeLists.txt','Makefile','Dockerfile'}

def metadata(meta,key):
    if not isinstance(key,str) or len(key)!=32 or any(c not in '0123456789abcdef' for c in key):raise ValueError('Validação inválida.')
    return Path(meta)/'validation-runs'/(key+'.json')
def save(meta,data):atomic(metadata(meta,data['id']),json.dumps(data,ensure_ascii=False,indent=2).encode())
def load(meta,key):
    data=read_json(metadata(meta,key))
    if data['state'] in ('queued','running') and not owner_alive(data):
        data.update(state='interrupted',message='Validação interrompida pelo encerramento. Não foi repetida.');save(meta,data)
    return data
def listing(meta):
    directory=Path(meta)/'validation-runs';rows=[]
    if directory.exists():
        for p in directory.glob('*.json'):
            try:rows.append(load(meta,p.stem))
            except (OSError,ValueError):continue
    return sorted(rows,key=lambda r:r['created_at'],reverse=True)[:30]
def code_fingerprint(root):
    """Validação deixa de ser atual quando qualquer ficheiro coberto muda."""
    import hashlib
    result=hashlib.sha256();budget=64*1024*1024
    for n,(p,rel) in enumerate(files(root)):
        if n>=10000:raise ValueError('Projeto excede 10000 ficheiros cobertos pela validação.')
        size=p.stat().st_size
        if size>8*1024*1024 or size>budget:raise ValueError('Projeto excede os limites de tamanho da validação.')
        content=read(p);budget-=len(content);result.update(rel.encode()+b'\0'+digest(content).encode()+b'\0')
    return result.hexdigest()
def _json(root,name):
    p=Path(root)/name
    if not p.exists():return {}
    if not p.resolve().is_relative_to(Path(root).resolve()) or p.stat().st_size>1024*1024:raise ValueError('Configuração de validação inválida: '+name)
    return json.loads(p.read_text(encoding='utf-8-sig'))
def python_runtime(root):
    env=Path(root)/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    if env.is_file():return str(env)
    if not getattr(sys,'frozen',False):return sys.executable
    candidates=list((config.application_root()/'Ferramentas/_Runtime/python').glob('cpython-*/python.exe'))
    return str(candidates[0]) if candidates else shutil.which('python')
def npm_runtime():
    portable=config.application_root()/'Ferramentas/REA/runtime/node-v24.22.1-win-x64/node.exe'
    node=shutil.which('node') or (str(portable) if portable.exists() else None)
    if not node:return None
    npm=shutil.which('npm');candidates=[Path(node).parent/'node_modules/npm/bin/npm-cli.js']
    if npm:candidates.extend([Path(npm).parent/'node_modules/npm/bin/npm-cli.js',Path(npm).resolve().parent.parent/'lib/node_modules/npm/bin/npm-cli.js'])
    for p in candidates:
        if p.is_file():return [node,str(p)]
    if os.name!='nt' and npm:return [npm]
    return None

def discover(root):
    root=Path(root).resolve();checks=[];setup=[];warnings=[]
    def add(key,label,argv,kind='test',recommended=True,timeout=300):
        checks.append(dict(id=key,label=label,argv=argv or [],kind=kind,recommended=recommended,timeout=timeout,available=bool(argv),cwd=str(root)))
    package=_json(root,'package.json')
    if package:
        npm=npm_runtime();manager=package.get('packageManager','')
        if manager and not manager.startswith('npm@'):warnings.append('O projeto indica '+manager+'. Configura os comandos próprios em .meister/validation.json; não é substituído automaticamente por npm.')
        else:
            for name in ('test','typecheck','lint','check','build'):
                if name in (package.get('scripts') or {}):add('npm:'+name,'npm run '+name,[*npm,'run',name] if npm else None,'build' if name=='build' else 'test' if name=='test' else 'check',name!='build')
            if (root/'package-lock.json').exists() and npm:setup.append(dict(id='setup:npm',label='Instalar dependências do lockfile (sem scripts de instalação)',argv=[*npm,'ci','--ignore-scripts','--no-audit','--no-fund'],cwd=str(root),timeout=900,available=True))
    py=python_runtime(root);tests=[p for p,rel in files(root,'test*.py') if '/tests/' in '/'+rel or p.name.startswith('test_')][:80]
    pyproject=root/'pyproject.toml'
    pytest_config=(root/'pytest.ini').exists() or (root/'conftest.py').exists() or (pyproject.exists() and '[tool.pytest' in pyproject.read_text(encoding='utf-8',errors='replace')[:100000])
    if tests or pytest_config:
        use_pytest=pytest_config
        if not use_pytest:
            samples=[p.read_text(encoding='utf-8',errors='replace')[:100000] for p in tests]
            use_pytest=any(re.search(r'(?m)^(?:async )?def test_|\b(?:import pytest|from pytest)',text) for text in samples) or not any('unittest' in text for text in samples)
        args=['-m','pytest','-q'] if use_pytest else ['-m','unittest','discover','-s','tests' if (root/'tests').is_dir() else '.', '-p','test*.py']
        add('python:pytest' if use_pytest else 'python:unittest','Testes Python (pytest)' if use_pytest else 'Testes Python (unittest)',[py,*args] if py else None)
    requirements=[name for name in ('requirements.txt','requirements-dev.txt') if (root/name).is_file()]
    if (tests or requirements or pyproject.exists()) and py:
        env_python=root/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
        if not env_python.exists():setup.append(dict(id='setup:venv',label='Criar ambiente Python local',argv=[py,'-m','venv',str(root/'.venv')],cwd=str(root),timeout=180,available=True))
        if requirements:setup.append(dict(id='setup:pip',label='Instalar requisitos no ambiente local',argv=[str(env_python),'-m','pip','install',*[v for name in requirements for v in ('-r',name)]],cwd=str(root),timeout=900,available=True))
        elif pyproject.exists():setup.append(dict(id='setup:pip',label='Instalar projeto no ambiente local',argv=[str(env_python),'-m','pip','install','-e','.'],cwd=str(root),timeout=900,available=True))
    if (root/'Cargo.toml').exists():
        cargo=shutil.which('cargo');add('cargo:test','cargo test',[cargo,'test',*(['--locked'] if (root/'Cargo.lock').exists() else [])] if cargo else None,timeout=600)
    if (root/'go.mod').exists():
        go=shutil.which('go');add('go:test','go test ./...',[go,'test','./...'] if go else None)
    custom=_json(root,'.meister/validation.json')
    for c in custom.get('checks',[]):
        key=c.get('id','');argv=c.get('argv');cwd=(root/c.get('cwd','.')).resolve()
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',key) or not isinstance(argv,list) or not argv or len(argv)>100 or any(not isinstance(v,str) or not v or '\0' in v for v in argv) or not cwd.is_relative_to(root):raise ValueError('Verificação personalizada inválida.')
        executable=shutil.which(argv[0]) or (str((root/argv[0]).resolve()) if (root/argv[0]).is_file() else None)
        add('custom:'+key,str(c.get('label',key))[:200],[executable,*argv[1:]] if executable else None,str(c.get('kind','test')),bool(c.get('recommended',True)),max(1,min(1800,int(c.get('timeout',300)))))
        checks[-1]['cwd']=str(cwd)
    if not checks:warnings.append('Nenhuma verificação detetada. Define checks em .meister/validation.json para este projeto.')
    return dict(workspace=str(root),checks=checks,setup=setup,warnings=warnings,python=py)

class ValidationRuns:
    def __init__(self,commands):self.commands=commands;self.lock=threading.RLock();self.jobs={};self.closed=False
    def start(self,meta,root,ids=None,prepare=False,approve=None,parent_cancel=None):
        plan=discover(root);choices=plan['setup' if prepare else 'checks'];selected=[c for c in choices if c.get('recommended',True)] if ids is None else [c for c in choices if c['id'] in ids]
        if ids is not None and (not isinstance(ids,list) or len(set(ids))!=len(ids) or any(key not in {c['id'] for c in choices} for key in ids)):raise ValueError('Verificações desconhecidas.')
        with self.lock:
            if self.closed or len(self.jobs)>=2:raise ValueError('As validações estão ocupadas ou a encerrar.')
            if any(Path(item['data']['workspace']).resolve()==Path(root).resolve() for item in self.jobs.values()):raise ValueError('Já existe uma preparação ou verificação nesta área. Aguarda a conclusão.')
            key=uuid.uuid4().hex;data=dict(id=key,state='queued',workspace=str(Path(root).resolve()),prepare=prepare,created_at=time.time(),owner_pid=os.getpid(),owner_identity=process_identity(),checks=[],warnings=plan['warnings'],requested=[c['id'] for c in selected])
            item=dict(meta=str(meta),data=data,cancel=threading.Event(),done=threading.Event(),persist=True,parent_cancel=parent_cancel)
            save(meta,data);self.jobs[key]=item;threading.Thread(target=self._run,args=(item,selected,approve),daemon=True).start();return dict(data)
    def _save(self,item):
        if item['persist']:save(item['meta'],item['data'])
    def _run(self,item,checks,approve):
        data=item['data'];root=data['workspace']
        def cancelled():return item['cancel'].is_set() or (item['parent_cancel'] is not None and item['parent_cancel'].is_set())
        try:
            data.update(state='running',before_fingerprint=code_fingerprint(root));self._save(item)
            for check in checks:
                if cancelled():break
                record=dict(id=check['id'],label=check['label'],state='unavailable',argv=check['argv'],kind=check.get('kind','setup'));data['checks'].append(record)
                if not check['available']:record['message']='Runtime necessário não instalado.';self._save(item);continue
                if approve and not approve(check):record.update(state='denied',message='Execução recusada.');self._save(item);continue
                if cancelled():break
                record['state']='running';self._save(item)
                job=self.commands.start(item['meta'],subprocess.list2cmdline(check['argv']),check['cwd'],check['timeout'],WorkspaceSnapshot(item['meta'],root,'Verificação: '+check['label']),argv=check['argv']);record['job_id']=job['id'];self._save(item)
                while True:
                    result=load_command(item['meta'],job['id'])
                    if result['state'] not in ('starting','running','cancelling'):break
                    if cancelled():self.commands.cancel(item['meta'],job['id'])
                    time.sleep(.1)
                record.update(state='passed' if result['state']=='completed' else result['state'],returncode=result.get('returncode'),output=(result.get('output') or result.get('message') or '')[-24000:])
                if check['id']=='python:unittest' and re.search(r'Ran 0 tests\b',record['output']):record.update(state='no_tests',message='O runner terminou sem executar testes.')
                self._save(item)
                if data['prepare'] and record['state']!='passed':break
            data.update(after_fingerprint=code_fingerprint(root),finished_at=time.time())
            if cancelled():data['state']='cancelled'
            elif not checks:data['state']='no_checks'
            elif all(c['state']=='passed' for c in data['checks']) and len(data['checks'])==len(checks):data['state']='passed'
            else:data['state']='failed'
            if data['state']=='passed' and not data['prepare'] and data['before_fingerprint']!=data['after_fingerprint']:
                data.update(state='changed',message='O código mudou durante as verificações. Volta a executar para validar a versão atual.')
        except Exception as exc:data.update(state='error',message=str(exc)[:3000])
        finally:
            with self.lock:
                try:self._save(item)
                finally:self.jobs.pop(data['id'],None);item['done'].set()
    def wait(self,meta,key,cancel=None):
        with self.lock:item=self.jobs.get(key)
        if item and Path(item['meta']).resolve()==Path(meta).resolve():
            while not item['done'].wait(.1):
                if cancel is not None and cancel.is_set():item['cancel'].set()
        return load(meta,key)
    def cancel(self,meta,key):
        with self.lock:
            item=self.jobs.get(key)
            if item and Path(item['meta']).resolve()==Path(meta).resolve():item['cancel'].set()
        return load(meta,key)
    def detach_context(self,meta):
        with self.lock:
            for item in self.jobs.values():
                if Path(item['meta']).resolve().is_relative_to(Path(meta).resolve()):item['persist']=False;item['cancel'].set()
    def close(self):
        with self.lock:self.closed=True;items=list(self.jobs.values())
        for item in items:item['cancel'].set()
        for item in items:item['done'].wait(5)
