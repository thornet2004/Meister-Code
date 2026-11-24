"""Pesquisa e edições verificadas, com diário persistente de undo/redo."""
from __future__ import annotations
import difflib,fnmatch,hashlib,json,os,stat,threading,uuid,time
from datetime import datetime,timezone
from pathlib import Path

MAX_FILE=8*1024*1024
IGNORED={'.git','.studio','.venv','venv','node_modules','__pycache__','.pytest_cache','.mypy_cache','.ruff_cache','htmlcov','coverage','build','dist','Ferramentas','Conversas','Projectos','.integrations'}
_LOCK=threading.RLock()

def digest(data):return hashlib.sha256(data).hexdigest() if data is not None else 'ausente'
def read_json(path):
    for attempt in range(8):
        try:return json.loads(Path(path).read_text(encoding='utf-8'))
        except PermissionError:
            if attempt==7:raise
            time.sleep(min(.15,.01*2**attempt))
def read(path):
    p=Path(path)
    if p.is_absolute() and os.path.normcase(str(p))!=os.path.normcase(str(p.resolve())):raise ValueError('O caminho passou a apontar para outro local: '+str(p))
    if not p.exists():return None
    if not p.is_file() or p.stat().st_size>MAX_FILE:raise ValueError('Só são aceites ficheiros regulares até 8 MiB.')
    return p.read_bytes()

def atomic(path,data):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    temp=p.with_name('.'+p.name+'.studio-'+uuid.uuid4().hex+'.tmp')
    try:
        with temp.open('xb') as out:out.write(data);out.flush();os.fsync(out.fileno())
        if p.exists():os.chmod(temp,stat.S_IMODE(p.stat().st_mode))
        for attempt in range(8):
            try:os.replace(temp,p);break
            except PermissionError:
                if attempt==7:raise
                time.sleep(.01*(attempt+1))
    finally:
        if temp.exists():temp.unlink()

def difference(path,before,after):
    old=(before or b'').decode('utf-8-sig',errors='replace').splitlines()
    new=(after or b'').decode('utf-8-sig',errors='replace').splitlines()
    return '\n'.join(difflib.unified_diff(old,new,fromfile='antes/'+str(path),tofile='depois/'+str(path),lineterm=''))[:50000]

# Dados que a app guarda dentro da pasta de uma conversa sem projeto (aí a pasta de trabalho é a própria pasta da conversa).
# Não são ficheiros do utilizador: se entrarem nas listagens, cada checkpoint copia os checkpoints anteriores (visto a
# 24/11/2026: 312 MB e 15 s por comando numa conversa de uma manhã) e o índice de código lê milhares de cópias.
APP_DATA={'attachments','checkpoints','command-jobs','turn-runs','agent-attempts','agent-sandboxes','agent-tasks','hook-runs','validation-runs',
          'conversation.json','conversation.json.tmp','conversation-info.json','context-state.json','history.json','hook-trust.json','stderr.log','stdout.log'}
def app_data(root):
    """Nomes a ignorar no topo de ``root`` quando ela é a pasta de uma conversa da app."""
    root=Path(root)
    return APP_DATA if (root/'conversation.json').is_file() or (root/'conversation-info.json').is_file() else frozenset()

def files(root,pattern='*'):
    root=Path(root).resolve();seen=0;directories=set();own=app_data(root)
    for folder,dirs,names in os.walk(root,followlinks=False):
        canonical=os.path.normcase(str(Path(folder).resolve()))
        if canonical in directories or len(directories)>=20000:dirs[:]=[];continue
        directories.add(canonical)
        top=own if Path(folder)==root else ()
        dirs[:]=sorted(d for d in dirs if d not in IGNORED and d not in top and not (Path(folder)/d).is_symlink() and not (Path(folder)/d).is_junction() and (Path(folder)/d).resolve().is_relative_to(root))
        for name in sorted(names):
            if name in ('.git','.coverage'):continue
            if top and (name in top or name.startswith(('code-context.sqlite','code-semantic.sqlite'))):continue
            p=Path(folder)/name
            if p.is_symlink() or not p.resolve().is_relative_to(root):continue
            seen+=1
            if seen>20000:return
            rel=p.relative_to(root).as_posix()
            if fnmatch.fnmatch(rel,pattern) or fnmatch.fnmatch(name,pattern) or (pattern.startswith('**/') and fnmatch.fnmatch(rel,pattern[3:])):yield p,rel

def search(root,pattern='*',text=None,case_sensitive=False):
    found=[];truncated=False;budget=32*1024*1024;skipped=0
    for p,rel in files(root,pattern):
        if text is None:found.append({'path':rel})
        else:
            size=p.stat().st_size
            if size>2*1024*1024 or size>budget:skipped+=1;continue
            budget-=size
            data=p.read_bytes()
            if b'\0' in data[:4096]:continue
            try:content=data.decode('utf-8-sig')
            except UnicodeError:continue
            needle=text if case_sensitive else text.casefold()
            for number,line in enumerate(content.splitlines(),1):
                if needle in (line if case_sensitive else line.casefold()):
                    found.append({'path':rel,'line':number,'text':line[:500]})
                    if len(found)>=300:break
        if len(found)>=300:truncated=True;break
    return {'results':found,'truncated':truncated or skipped>0,'skipped_large_or_budget_files':skipped,'excluded_directories':sorted(IGNORED),'max_files':20000}

class Checkpoints:
    def __init__(self,meta):self.root=Path(meta)/'checkpoints'
    def _path(self,key):
        if not isinstance(key,str) or len(key)!=32 or any(c not in '0123456789abcdef' for c in key):raise ValueError('Checkpoint inválido.')
        return self.root/key
    def load(self,key):
        data=read_json(self._path(key)/'checkpoint.json')
        if data.get('id')!=key:raise ValueError('Checkpoint inválido.')
        return data
    def save(self,data):
        folder=self._path(data['id']);folder.mkdir(parents=True,exist_ok=True)
        atomic(folder/'checkpoint.json',json.dumps(data,ensure_ascii=False,indent=2).encode('utf-8'))
    def begin(self,title='Edição de ficheiros'):
        data=dict(id=uuid.uuid4().hex,title=str(title)[:160],created_at=datetime.now(timezone.utc).isoformat(),state='active',owner_pid=os.getpid(),owner_identity=process_identity(),files=[])
        self.save(data);return data['id']
    def _blob(self,key,data):
        if data is None:return None
        sha=digest(data);folder=self._path(key)/'blobs';folder.mkdir(parents=True,exist_ok=True)
        path=folder/sha
        if not path.exists():atomic(path,data)
        return sha
    def _bytes(self,key,sha):
        if sha is None:return None
        if len(sha)!=64 or any(c not in '0123456789abcdef' for c in sha):raise ValueError('Backup inválido.')
        data=(self._path(key)/'blobs'/sha).read_bytes()
        if digest(data)!=sha:raise ValueError('Integridade do backup incorreta.')
        return data
    def apply(self,key,updates):
        """Preflight de todos os ficheiros antes de qualquer escrita."""
        with _LOCK:
            cp=self.load(key)
            original=json.loads(json.dumps(cp))
            if cp['state']!='active':raise ValueError('Checkpoint já fechado.')
            for path,before,after in updates:
                if read(path)!=before:raise ValueError('Conflito: o ficheiro mudou entretanto: '+str(path))
                if after is not None and len(after)>MAX_FILE:raise ValueError('Saída excede 8 MiB.')
            plan=[]
            for path,before,after in updates:
                path=str(Path(path).resolve())
                previous=next((f for f in cp['files'] if f['path']==path),None)
                entry=previous or dict(path=path,before=self._blob(key,before))
                if previous and previous['after']!=self._blob(key,before):raise ValueError('O ficheiro mudou fora deste checkpoint: '+path)
                entry['after']=self._blob(key,after)
                if not previous:cp['files'].append(entry)
                plan.append((path,before,after))
            # Write-ahead journal permits conflict-safe inspection after interruption.
            self.save(cp)
            written=[]
            try:
                for path,before,after in plan:
                    if read(path)!=before:raise ValueError('Conflito durante a gravação: '+path)
                    if after is None:self._retire(key,path)
                    else:atomic(path,after)
                    written.append((path,before,after))
            except Exception:
                rollback_ok=True
                for path,before,after in reversed(written):
                    try:
                        if read(path)!=after:rollback_ok=False;continue
                        if before is None:self._retire(key,path)
                        else:atomic(path,before)
                    except OSError:rollback_ok=False
                if rollback_ok:self.save(original)
                raise
            return cp
    def finish(self,key):
        with _LOCK:
            cp=self.load(key);cp['state']='applied';self.save(cp)
    def _retire(self,key,path):
        p=Path(path)
        if p.exists():
            folder=self._path(key)/'recovered';folder.mkdir(parents=True,exist_ok=True)
            os.replace(p,folder/(uuid.uuid4().hex+'-'+p.name[:64]))
    def preview(self,key):
        cp=self.load(key);items=[]
        for f in cp['files']:
            before=self._bytes(key,f['before']);after=self._bytes(key,f['after'])
            expected=f['before'] if cp['state']=='undone' else f['after']
            try:
                current=digest(read(f['path']));allowed={'ausente' if expected is None else expected}
                if cp.get('interrupted'):allowed.add('ausente' if f['before'] is None else f['before'])
                conflict=current not in allowed
            except (OSError,ValueError):conflict=True
            items.append(dict(path=f['path'],kind='created' if before is None else 'deleted' if after is None else 'modified',diff=difference(f['path'],before,after),conflict=conflict))
        return {**{k:v for k,v in cp.items() if k!='files'},'files':items}
    def list(self):
        if not self.root.exists():return []
        result=[]
        for folder in sorted(self.root.iterdir(),reverse=True):
            try:
                cp=self.load(folder.name)
                if cp['files']:result.append({k:v for k,v in cp.items() if k!='files'}|{'file_count':len(cp['files'])})
            except (OSError,ValueError):continue
        return sorted(result,key=lambda r:r['created_at'],reverse=True)[:100]
    def recover_abandoned(self):
        for item in self.list():
            if item['state']!='active' or owner_alive(item):continue
            with _LOCK:
                cp=self.load(item['id']);cp.update(state='applied',interrupted=True);self.save(cp)
    def restore(self,key,redo=False):
        with _LOCK:
            cp=self.load(key)
            if cp['state']=='active':raise ValueError('Este pedido ainda não terminou; interrompe ou aguarda antes de restaurar.')
            if cp['state']!=('undone' if redo else 'applied'):raise ValueError('Estado incompatível com esta operação.')
            updates=[]
            for f in cp['files']:
                before=self._bytes(key,f['before']);after=self._bytes(key,f['after'])
                expected=before if redo else after;target=after if redo else before
                current=read(f['path'])
                if current==target:continue
                if current!=expected:raise ValueError('Conflito: alteração posterior em '+f['path']+'. Nenhum ficheiro restaurado.')
                updates.append((f['path'],expected,target))
            written=[]
            try:
                for path,expected,target in updates:
                    if read(path)!=expected:raise ValueError('Conflito durante o restauro: '+path)
                    if target is None:self._retire(key,path)
                    else:atomic(path,target)
                    written.append((path,expected,target))
            except Exception:
                for path,expected,target in reversed(written):
                    if read(path)==target:
                        if expected is None:self._retire(key,path)
                        else:atomic(path,expected)
                raise
            cp['state']='applied' if redo else 'undone';self.save(cp);return self.preview(key)

def process_alive(pid):
    if not isinstance(pid,int) or pid<=0:return False
    if pid==os.getpid():return True
    if os.name=='nt':
        import ctypes
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)];kernel.GetExitCodeProcess.restype=wintypes.BOOL
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        handle=kernel.OpenProcess(0x1000,False,pid)
        if not handle:return ctypes.get_last_error()==5
        try:
            code=wintypes.DWORD();return not kernel.GetExitCodeProcess(handle,ctypes.byref(code)) or code.value==259
        finally:kernel.CloseHandle(handle)
    try:os.kill(pid,0);return True
    except ProcessLookupError:return False
    except PermissionError:return True

def process_identity(pid=None):
    pid=os.getpid() if pid is None else pid
    if not isinstance(pid,int) or pid<=0:return None
    if os.name=='nt':
        import ctypes
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True);kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE;kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        kernel.GetProcessTimes.argtypes=[wintypes.HANDLE,*([ctypes.POINTER(wintypes.FILETIME)]*4)];kernel.GetProcessTimes.restype=wintypes.BOOL
        handle=kernel.OpenProcess(0x1000,False,pid)
        if not handle:return None
        try:
            values=[wintypes.FILETIME() for _ in range(4)]
            if not kernel.GetProcessTimes(handle,*[ctypes.byref(v) for v in values]):return None
            return str((values[0].dwHighDateTime<<32)|values[0].dwLowDateTime)
        finally:kernel.CloseHandle(handle)
    try:
        fields=Path('/proc/'+str(pid)+'/stat').read_text().rsplit(')',1)[1].split();boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip();return boot+':'+fields[19]
    except (OSError,ValueError,IndexError):return None

def owner_alive(data):
    pid=data.get('owner_pid',0)
    if not process_alive(pid):return False
    expected=data.get('owner_identity');actual=process_identity(pid) if expected else None
    return actual is None or actual==expected
