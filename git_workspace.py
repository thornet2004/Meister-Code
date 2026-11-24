"""Operações Git estruturadas, sem interpolação de comandos shell."""
from pathlib import Path
import subprocess

def run(root,*args):
    result=subprocess.run(['git','-C',str(root),*args],capture_output=True,encoding='utf-8',errors='replace',timeout=40,creationflags=subprocess.CREATE_NO_WINDOW if __import__('os').name=='nt' else 0)
    if result.returncode:raise ValueError(result.stderr.strip() or result.stdout.strip() or 'Operação Git falhou.')
    return result.stdout[:200000]
def root_for(workspace):return Path(run(workspace,'rev-parse','--show-toplevel').strip()).resolve()
def status(workspace):
    root=root_for(workspace);raw=run(root,'status','--porcelain=v1','-z','--untracked-files=normal');tokens=iter(raw.split('\0'));changes=[]
    for row in tokens:
        if not row:continue
        code=row[:2];name=row[3:];old=next(tokens,'') if 'R' in code or 'C' in code else None
        changes.append(dict(path=name,status=code,original_path=old,conflict=code in ('DD','AU','UD','UA','DU','AA','UU')))
    try:history=run(root,'log','-12','--format=%h %s')
    except ValueError:history='Sem commits.'
    return dict(root=str(root),branch=run(root,'branch','--show-current').strip(),changes=changes,branches=run(root,'for-each-ref','--format=%(refname:short)','refs/heads').splitlines(),history=history,worktrees=run(root,'worktree','list','--porcelain'))
def selected_paths(root,paths):
    if not isinstance(paths,list) or not paths or len(paths)>100:raise ValueError('Seleciona entre 1 e 100 ficheiros.')
    result=[]
    for name in paths:
        if not isinstance(name,str) or not name or name.startswith('-'):raise ValueError('Caminho inválido.')
        p=(root/name).resolve()
        if not p.is_relative_to(root):raise ValueError('Caminho fora do repositório.')
        result.append(p.relative_to(root).as_posix())
    return result
def action(workspace,operation,options):
    root=root_for(workspace)
    if operation=='diff':
        paths=selected_paths(root,options['paths']) if options.get('paths') else []
        return dict(text=run(root,'diff','--no-ext-diff',*(['--cached'] if options.get('staged') else []),'--',*paths))
    if operation in ('stage','unstage'):
        paths=selected_paths(root,options.get('paths'))
        text=run(root,'add','--',*paths) if operation=='stage' else run(root,'restore','--staged','--',*paths)
    elif operation=='commit':
        message=options.get('message','').strip()
        if not message or len(message)>10000:raise ValueError('Escreve uma mensagem de commit até 10000 caracteres.')
        text=run(root,'commit','-m',message)
    elif operation in ('branch','switch','worktree'):
        branch=options.get('branch','').strip()
        if not branch or branch.startswith('-'):raise ValueError('Branch inválida.')
        run(root,'check-ref-format','--branch',branch)
        if operation=='branch':text=run(root,'branch',branch)
        elif operation=='switch':
            if run(root,'status','--porcelain'):raise ValueError('Guarda as alterações num commit antes de trocar de branch.')
            text=run(root,'switch',branch)
        else:
            destination=Path(options.get('path','')).expanduser()
            if not destination.is_absolute():raise ValueError('Indica um caminho absoluto para a worktree.')
            destination=destination.resolve()
            if destination.exists():raise ValueError('Escolhe uma pasta nova para a worktree.')
            text=run(root,'worktree','add',str(destination),branch)
    else:raise ValueError('Operação Git desconhecida.')
    return dict(text=text)
