"""Checkpoints de alterações externas no workspace, com cobertura explícita."""
from pathlib import Path
import threading
from coding_tools import Checkpoints,files,read,_LOCK
from coding_tools import owner_alive

_ACTIVE=set();_GUARD=threading.RLock()
def active(root):
    with _GUARD:return str(Path(root).resolve()).casefold() in _ACTIVE

def recover(meta):
    store=Checkpoints(meta)
    if not store.root.exists():return
    for p in store.root.glob('*/checkpoint.json'):
        cp=store.load(p.parent.name)
        if cp.get('external_snapshot') and not owner_alive(cp):
            snapshot=WorkspaceSnapshot(meta,cp['external_snapshot']['root'],cp['title']);snapshot.finish(cp['id'])
            cp=store.load(cp['id']);cp['interrupted']=True;store.save(cp)

class WorkspaceSnapshot:
    def __init__(self,meta,root,title):self.meta=meta;self.root=Path(root).resolve();self.store=Checkpoints(meta);self.title=title;self.token=str(self.root).casefold()
    def scan(self):
        result={};skipped=[];budget=64*1024*1024
        for n,(p,rel) in enumerate(files(self.root)):
            if n>=10000:skipped.append('[limite de 10000 ficheiros]');break
            try:
                size=p.stat().st_size
                if size>8*1024*1024 or size>budget:skipped.append(rel);continue
                content=read(p);budget-=len(content);result[str(p)]=content
            except (OSError,ValueError):skipped.append(rel)
        return result,skipped
    def begin(self):
        with _GUARD:
            if self.token in _ACTIVE:raise ValueError('Já existe uma operação com snapshot neste workspace. Aguarda a sua conclusão.')
            _ACTIVE.add(self.token)
        try:
            key=self.store.begin(self.title);baseline,skipped=self.scan()
            cp=self.store.load(key);cp['external_snapshot']=dict(root=str(self.root),baseline={p:self.store._blob(key,b) for p,b in baseline.items()},skipped=skipped)
            cp['coverage']='Workspace: até 10000 ficheiros, 8 MiB por ficheiro e 64 MiB no total; exclui dependências, dados da app, .git e caminhos externos.'
            self.store.save(cp);return key
        except Exception:
            with _GUARD:_ACTIVE.discard(self.token)
            raise
    def abandon(self):
        with _GUARD:_ACTIVE.discard(self.token)
    def finish(self,key):
        try:
            with _LOCK:
                cp=self.store.load(key);original=cp['external_snapshot'];after,skipped=self.scan();before=original['baseline'];ignored=set(skipped+original['skipped']);entries=[]
                for p in sorted(set(before)|set(after)):
                    if Path(p).relative_to(self.root).as_posix() in ignored:continue
                    old=before.get(p);new=self.store._blob(key,after.get(p))
                    if old!=new:entries.append(dict(path=p,before=old,after=new))
                cp.update(files=entries,state='applied',skipped=sorted(ignored));cp.pop('external_snapshot',None);self.store.save(cp)
                return dict(id=key,file_count=len(entries),skipped=sorted(ignored),coverage=cp['coverage'])
        finally:
            with _GUARD:_ACTIVE.discard(self.token)
