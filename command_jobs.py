"""Processos acompanhados, com histórico persistente e saída limitada em disco."""
from __future__ import annotations
import json,os,subprocess,threading,time,uuid
from pathlib import Path
from coding_tools import atomic,read_json,owner_alive,process_identity

def path(meta,key):
    if not isinstance(key,str) or len(key)!=32 or any(c not in '0123456789abcdef' for c in key):raise ValueError('Processo inválido.')
    return Path(meta)/'command-jobs'/key
def load(meta,key):
    folder=path(meta,key);data=read_json(folder/'job.json')
    if data['state'] in ('starting','running','cancelling') and not owner_alive(data):
        data.update(state='interrupted',message='A aplicação encerrou. O estado final do processo anterior não foi confirmado; não será repetido automaticamente.')
        atomic(folder/'job.json',json.dumps(data,ensure_ascii=False).encode())
    log=folder/'output.log'
    if log.exists():
        with log.open('rb') as stream:stream.seek(max(0,log.stat().st_size-48000));data['output']=stream.read().decode('utf-8',errors='replace')
    return data
def listing(meta):
    root=Path(meta)/'command-jobs';rows=[]
    if root.exists():
        for p in root.glob('*/job.json'):
            try:rows.append({k:v for k,v in load(meta,p.parent.name).items() if k!='output'})
            except (OSError,ValueError):continue
    return sorted(rows,key=lambda r:r['created_at'],reverse=True)[:100]

class CommandJobs:
    def __init__(self):self.lock=threading.RLock();self.jobs={};self.closed=False
    def start(self,meta,command,cwd,timeout=3600,observer=None,argv=None,origin_action=None):
        if not isinstance(command,str) or not command.strip() or len(command)>20000:raise ValueError('Comando vazio ou demasiado longo.')
        cwd=str(Path(cwd).resolve())
        if not Path(cwd).is_dir():raise ValueError('Pasta de trabalho inexistente.')
        timeout=max(1,min(86400,int(timeout)))
        with self.lock:
            if self.closed:raise ValueError('A aplicação está a encerrar.')
            if len(self.jobs)>=4:raise ValueError('Já existem quatro processos em execução.')
            key=uuid.uuid4().hex;folder=path(meta,key);folder.mkdir(parents=True)
            data=dict(id=key,command=command,cwd=cwd,timeout=timeout,state='starting',created_at=time.time(),owner_pid=os.getpid(),owner_identity=process_identity(),pid=None,returncode=None,origin_action=origin_action)
            item=dict(meta=str(meta),data=data,event=threading.Event(),done=threading.Event(),process=None,persist=True,argv=argv)
            self.jobs[key]=item;self._save(item)
            threading.Thread(target=self._run,args=(item,observer),daemon=True).start()
            return dict(data)
    def _save(self,item):
        if item['persist']:atomic(path(item['meta'],item['data']['id'])/'job.json',json.dumps(item['data'],ensure_ascii=False).encode())
    def _run(self,item,observer):
        data=item['data'];snapshot=None;proc=None;reader=None
        try:
            if item['event'].is_set():data['state']='cancelled';return
            if observer:snapshot=observer.begin()
            args=item.get('argv') or (['powershell.exe','-NoLogo','-NoProfile','-NonInteractive','-Command',"[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); $OutputEncoding = [Console]::OutputEncoding; "+data['command']] if os.name=='nt' else ['/bin/sh','-c',data['command']])
            env=os.environ.copy();env.update(CI='1',PYTHONUNBUFFERED='1',NO_COLOR='1',PIP_DISABLE_PIP_VERSION_CHECK='1',PYTHONDONTWRITEBYTECODE='1',PYTHONPYCACHEPREFIX=str(path(item['meta'],data['id'])/'unused-pycache'))
            if item.get('argv') and Path(args[0]).is_absolute():env['PATH']=str(Path(args[0]).parent)+os.pathsep+env.get('PATH','')
            proc=subprocess.Popen(args,cwd=data['cwd'],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0,start_new_session=os.name!='nt')
            with self.lock:item['process']=proc;data.update(state='running',pid=proc.pid);self._save(item)
            folder=path(item['meta'],data['id']);size=[0]
            def drain():
                with (folder/'output.log').open('wb') as out:
                    while True:
                        chunk=proc.stdout.read(4096)
                        if not chunk:break
                        if size[0]<8*1024*1024:out.write(chunk[:8*1024*1024-size[0]]);out.flush()
                        size[0]+=len(chunk)
            reader=threading.Thread(target=drain,daemon=True);reader.start();deadline=time.monotonic()+data['timeout'];timed=False
            while proc.poll() is None:
                if item['event'].wait(.1) or time.monotonic()>deadline:
                    timed=not item['event'].is_set();self._kill(proc);break
            proc.wait();reader.join(3)
            if not reader.is_alive():proc.stdout.close()
            data.update(returncode=proc.returncode,state='timed_out' if timed else 'cancelled' if item['event'].is_set() else 'completed' if proc.returncode==0 else 'failed',output_truncated=size[0]>8*1024*1024)
        except Exception as exc:data.update(state='failed',message=str(exc)[:2000])
        finally:
            if proc and proc.poll() is None:self._kill(proc)
            if proc:
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=5)
                if reader:reader.join(3)
                if proc.stdout and (not reader or not reader.is_alive()):proc.stdout.close()
            if snapshot is not None:
                try:
                    if item['persist']:data['checkpoint']=observer.finish(snapshot)
                    else:observer.abandon()
                except Exception as exc:data['checkpoint_error']=str(exc)
            data['finished_at']=time.time()
            with self.lock:
                try:self._save(item)
                finally:self.jobs.pop(data['id'],None);item['done'].set()
    @staticmethod
    def _kill(proc):
        if proc.poll() is not None:return
        if os.name=='nt':subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW,timeout=15)
        else:
            import signal
            os.killpg(proc.pid,signal.SIGKILL)
    def cancel(self,meta,key):
        with self.lock:
            item=self.jobs.get(key)
            if item and Path(item['meta']).resolve()==Path(meta).resolve():item['event'].set()
        return load(meta,key)
    def detach_context(self,meta):
        with self.lock:
            for item in self.jobs.values():
                if Path(item['meta']).resolve().is_relative_to(Path(meta).resolve()):item['persist']=False;item['event'].set()
    def close(self):
        with self.lock:self.closed=True;items=list(self.jobs.values())
        for item in items:item['event'].set()
        for item in items:item['done'].wait(5)
