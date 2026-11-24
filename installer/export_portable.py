"""Create an independent local delivery. Sources are copied, never moved/deleted."""
from __future__ import annotations
import argparse,hashlib,json,os,re,shutil,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import config,integration_catalog
from coding_tools import atomic,read_json

TEXT={'.json','.cfg','.ini','.toml','.ps1','.bat','.cmd','.pth','.properties','.yaml','.yml','.xml','.conf','.txt','.sh','.cache','.rc'}
def copy_folder(source,target):
    if source.is_dir():shutil.copytree(source,target,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__') if source.name=='providers' else None)

def replace_paths(text,mappings):
    for old,new in sorted(mappings,key=lambda p:len(str(p[0])),reverse=True):
        for a,b in [(json.dumps(str(old))[1:-1],json.dumps(str(new))[1:-1]),(str(old),str(new)),(Path(old).as_posix(),Path(new).as_posix())]:
            text=re.sub(re.escape(a),lambda match:b,text,flags=re.IGNORECASE)
    return text

def rebase_tree(root,mappings):
    changed=0
    for folder,dirs,names in os.walk(root):
        dirs[:]=[d for d in dirs if not (Path(folder)/d).is_symlink() and not (Path(folder)/d).is_junction()]
        for name in names:
            path=Path(folder)/name
            if path.suffix.lower() not in TEXT or path.stat().st_size>8*1024*1024:continue
            try:raw=path.read_bytes();text=raw.decode('utf-8-sig')
            except (OSError,UnicodeError):continue
            new=replace_paths(text,mappings)
            if path.suffix.lower()=='.json':
                try:
                    data=json.loads(new)
                    if isinstance(data,dict) and 'owner_pid' in data and data.get('state') in ('running','queued','starting','cancelling'):
                        data.update(state='interrupted',owner_pid=0,owner_identity=None,message='Contexto copiado para a entrega; operação anterior não foi repetida.');new=json.dumps(data,ensure_ascii=False,indent=2)
                except ValueError:pass
            if new!=text:atomic(path,new.encode('utf-8'));changed+=1
    return changed

def export(destination,tools_ready=False):
    root=Path(__file__).resolve().parents[1];destination=Path(destination).resolve();settings=config.config_dir().resolve();cfg=read_json(config.config_path());before=hashlib.sha256(config.config_path().read_bytes()).hexdigest()
    if destination==root or destination.is_relative_to(root) or root.is_relative_to(destination):raise ValueError('O destino final tem de estar separado da pasta de desenvolvimento.')
    if (destination/'meistercode-portable.json').exists():raise ValueError('O destino já foi finalizado; escolhe outra pasta para preservar a cópia existente.')
    destination.mkdir(parents=True,exist_ok=True)
    for name in ('Conversas','Projectos','Ferramentas','Configuracao','Recursos','Codigo'):(destination/name).mkdir(exist_ok=True)
    if not tools_ready:copy_folder(root/'Ferramentas',destination/'Ferramentas')
    elif not any((destination/'Ferramentas').iterdir()):raise ValueError('A cópia prévia de ferramentas está vazia.')
    old_root=Path(cfg.get('storage_root') or root).resolve();mappings=[(root,destination),(old_root,destination),(settings,destination/'Configuracao')]
    copy_folder(old_root/'Conversas',destination/'Conversas');copy_folder(old_root/'Projectos',destination/'Projectos')
    copy_folder(root/'.integrations',destination/'.integrations');copy_folder(root/'Skills',destination/'Skills')
    for p in settings.iterdir():
        if p.name=='updates':continue
        if p.is_dir():copy_folder(p,destination/'Configuracao'/p.name)
        elif p.is_file():shutil.copy2(p,destination/'Configuracao'/p.name)
    for item in cfg.get('projects',[]):
        source=Path(item.get('path','')).resolve()
        if not source.is_dir():continue
        if source.is_relative_to(old_root/'Projectos'):target=destination/'Projectos'/source.relative_to(old_root/'Projectos')
        else:target=destination/'Projectos'/re.sub(r'[^A-Za-z0-9_-]','_',item.get('id') or source.name)
        copy_folder(source,target);mappings.append((source,target))
    # Preserve generated assets referenced by older global histories.
    for name in ('imagens-geradas','outputs'):
        copy_folder(root/name,destination/name)
    for folder in ('providers','web','installer'):
        copy_folder(root/folder,destination/'Codigo'/folder)
    for p in root.glob('*.py'):shutil.copy2(p,destination/'Codigo'/p.name)
    for name in ('Studio de Media.spec','requirements.txt','requirements-bench.txt','build-exe.bat','README.md'):
        if (root/name).exists():shutil.copy2(root/name,destination/'Codigo'/name)
    if (root/'recursos/logo.svg').exists():shutil.copy2(root/'recursos/logo.svg',destination/'Recursos/logo.svg')
    for name in ('meistercode.png','meistercode.ico'):shutil.copy2(root/'web/assets'/name,destination/'Recursos'/name)
    changed=rebase_tree(destination,mappings)
    rewritten=json.loads(replace_paths(json.dumps(cfg,ensure_ascii=False),mappings));rewritten.update(storage_layout=2,storage_root=str(destination),output_dir=str(destination/'imagens-geradas'))
    executable=destination/'MeisterCode.exe'
    for server in rewritten.get('mcp_servers',[]):
        kind=server.get('preset');args=server.get('args') or []
        if kind in integration_catalog.CATALOG and integration_catalog.CATALOG[kind]['mode']=='bundled':
            server.update(command=str(executable),args=['--integration-server',kind,str(destination/'Configuracao')])
        elif any(str(arg).endswith('mcp_demo.py') for arg in args):server.update(command=str(executable),args=['--mcp-demo-server'])
    overrides=rewritten.get('folder_tools',{})
    for old_tools in {root/'Ferramentas',old_root/'Ferramentas'}:
        if not old_tools.exists():continue
        for manifest in old_tools.glob('*/ferramenta.json'):
            old_id='folder_'+hashlib.sha256(os.path.normcase(str(manifest.resolve())).encode()).hexdigest()[:20]
            new_path=destination/'Ferramentas'/manifest.relative_to(old_tools);new_id='folder_'+hashlib.sha256(os.path.normcase(str(new_path.resolve())).encode()).hexdigest()[:20]
            if old_id in overrides:overrides[new_id]=overrides.pop(old_id)
    atomic(destination/'Configuracao/config.json',json.dumps(rewritten,ensure_ascii=False,indent=2).encode())
    atomic(destination/'meistercode-portable.json',b'{"version":1,"configuration":"Configuracao"}')
    after=hashlib.sha256(config.config_path().read_bytes()).hexdigest()
    report=dict(created_at=time.time(),source_config_unchanged=before==after,rebased_files=changed,conversations=len(rewritten.get('conversations',[])),projects=len(rewritten.get('projects',[])),tool_manifests=len(list((destination/'Ferramentas').glob('*/ferramenta.json'))),configuration='Configuracao/config.json')
    atomic(destination/'entrega.json',json.dumps(report,indent=2).encode());print(json.dumps(report),flush=True)
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('destination');p.add_argument('--tools-ready',action='store_true');a=p.parse_args();export(a.destination,a.tools_ready)
