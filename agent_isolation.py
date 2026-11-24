"""Propostas de implementação isoladas e aplicação com hashes verificados."""
from pathlib import Path
import json,shutil
from coding_tools import Checkpoints,atomic,files,read,digest,difference,read_json
from workspace_snapshot import WorkspaceSnapshot
import project_validation
import git_workspace

def folder(meta,key):
    if not isinstance(key,str) or len(key)!=32 or any(c not in '0123456789abcdef' for c in key):raise ValueError('Proposta inválida.')
    return Path(meta)/'agent-sandboxes'/key
def prepare(meta,workspace,key):
    workspace=Path(workspace).resolve();target=folder(meta,key);target.mkdir(parents=True,exist_ok=False);work=target/'workspace';store=Checkpoints(target);cp=store.begin('Base da proposta')
    data,skipped=WorkspaceSnapshot(meta,workspace,'base').scan()
    if skipped:raise ValueError('A cópia isolada excede os limites ou encontrou ficheiros ilegíveis. Divide o projeto.')
    repo=None;revision=None
    if shutil.which('git'):
        try:repo=git_workspace.root_for(workspace);revision=git_workspace.run(repo,'rev-parse','--verify','HEAD').strip()
        except ValueError:repo=None
    if repo:
        checkout=(target/'git-worktree').resolve();git_workspace.run(repo,'worktree','add','--detach',str(checkout),revision);work=checkout/workspace.relative_to(repo);work.mkdir(parents=True,exist_ok=True)
        # Remove apenas ficheiros da área acabada de criar, nunca do projeto original.
        for p,rel in files(work):
            if str(workspace/rel) not in data:
                if not p.resolve().is_relative_to(checkout):raise ValueError('Caminho fora da worktree criada.')
                p.unlink()
    else:work.mkdir()
    manifest=dict(root=str(workspace),workspace=str(work),isolation='git-worktree' if repo else 'copy',git_root=str(repo) if repo else None,git_revision=revision,checkpoint=cp,baseline={},state='draft',validation_required=True,coverage='Worktree Git independente com alterações locais sobrepostas.' if repo else 'Cópia de código (sem commit Git disponível).')
    manifest['coverage']+=' Até 64 MiB de código; dependências não são partilhadas por symlinks. Preparação e verificações usam as aprovações configuradas; não constituem uma sandbox do sistema operativo.'
    for path,content in data.items():
        rel=Path(path).relative_to(workspace).as_posix();manifest['baseline'][rel]=store._blob(cp,content);atomic(work/rel,content)
    atomic(target/'proposal.json',json.dumps(manifest,ensure_ascii=False).encode());return work
def changes(meta,key):
    target=folder(meta,key);manifest=read_json(target/'proposal.json');store=Checkpoints(target);work=Path(manifest.get('workspace') or target/'workspace');current={rel:p for p,rel in files(work)};updates=[];rows=[]
    for rel in sorted(set(manifest['baseline'])|set(current)):
        before=store._bytes(manifest['checkpoint'],manifest['baseline'].get(rel));after=read(work/rel)
        if before==after:continue
        original=Path(manifest['root'])/rel;conflict=digest(read(original))!=digest(before)
        updates.append((original,before,after));rows.append(dict(path=rel,diff=difference(rel,before,after),conflict=conflict))
    return manifest,updates,rows
def workspace(meta,key):
    target=folder(meta,key);manifest=read_json(target/'proposal.json');work=Path(manifest.get('workspace') or target/'workspace').resolve()
    if not work.is_relative_to(target.resolve()):raise ValueError('Workspace isolado inválido.')
    return work
def validation(meta,key):
    runs=[r for r in project_validation.listing(folder(meta,key)/'metadata') if not r.get('prepare') and r.get('workspace')==str(workspace(meta,key))]
    if not runs:return dict(state='not_run',stale=False,checks=[])
    latest=runs[0];latest['stale']=latest.get('after_fingerprint')!=project_validation.code_fingerprint(workspace(meta,key))
    required={c['id'] for c in project_validation.discover(workspace(meta,key))['checks'] if c.get('recommended')}
    if latest['state'] in ('passed','no_checks') and set(latest.get('requested',[]))!=required:latest['state']='partial'
    return latest
def review(meta,key):
    manifest,_,rows=changes(meta,key);v=validation(meta,key) if manifest.get('validation_required') else dict(state='legacy',checks=[],stale=False)
    allowed=not manifest.get('validation_required') or (v['state'] in ('passed','no_checks') and not v['stale'])
    return dict(id=key,state=manifest['state'],files=rows,coverage=manifest['coverage'],workspace=str(workspace(meta,key)),isolation=manifest.get('isolation','copy'),validation=v,can_apply=allowed and not any(r['conflict'] for r in rows))
def apply(meta,key):
    manifest,updates,rows=changes(meta,key)
    if manifest['state']=='applied':raise ValueError('A proposta já foi aplicada.')
    if manifest.get('validation_required'):
        v=validation(meta,key)
        if v['state'] not in ('passed','no_checks') or v['stale']:raise ValueError('Executa as verificações atuais da proposta e corrige as falhas antes de aplicar.')
    if any(r['conflict'] for r in rows):raise ValueError('O projeto mudou desde a delegação. Revê os conflitos antes de aplicar.')
    if not updates:raise ValueError('A proposta não contém alterações.')
    store=Checkpoints(meta);cp=store.begin('Aplicar proposta '+key[:8]);store.apply(cp,updates);store.finish(cp)
    manifest.update(state='applied',applied_checkpoint=cp);atomic(folder(meta,key)/'proposal.json',json.dumps(manifest,ensure_ascii=False).encode())
    return dict(checkpoint_id=cp,file_count=len(updates))
