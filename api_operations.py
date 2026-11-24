"""Ponte ``Api``: operações do projeto — comandos em segundo plano, hooks, validação, limites de execução e painel Git.

Classe-base de ``api.Api`` (extraída de ``api.py`` sem alterações ao código).
Os métodos sem ``_`` inicial são chamados pela interface através da ponte do
pywebview. Usa atributos criados em ``Api.__init__`` e outros métodos da
instância através de ``self``.
"""

from __future__ import annotations

import agent_isolation
import config
import git_workspace
import json
import project_hooks
import project_validation
import subprocess
from agent_runtime import get_task
from api_helpers import _agent_cwd, _err, _ok
from coding_tools import digest as file_digest, read as read_code_bytes
from command_jobs import listing as list_commands, load as load_command
from execution_limits import DEFAULTS as LIMIT_DEFAULTS, validate as validate_limits
from workspace_snapshot import WorkspaceSnapshot, active as snapshot_active


class OperationsApi:
    def get_command_jobs(self, job_id: str = '') -> dict:
        try:
            meta,_=config.resolve_context(config.load_config())
            return _ok(jobs=list_commands(meta),job=load_command(meta,job_id) if job_id else None)
        except Exception as exc:return _err(str(exc))

    def get_project_hooks(self) -> dict:
        try:
            cfg=config.load_config();meta,root=config.resolve_context(cfg)
            return _ok(configuration=project_hooks.status(root,meta),runs=project_hooks.listing(meta),workspace=str(root))
        except Exception as exc:return _err(str(exc))

    def save_project_hooks(self, text: str, enabled: bool = True) -> dict:
        try:
            cfg=config.load_config();meta,root=config.resolve_context(cfg);ctx=self._agent_context(cfg)
            if ctx.get('readonly') or not ctx.get('on'):raise ValueError('Ativa Implementar e o modo agente para configurar hooks.')
            if not enabled:
                project_hooks.trust_path(meta).unlink(missing_ok=True)
                return self.get_project_hooks()
            project_hooks.activate(root,meta,text);return self.get_project_hooks()
        except Exception as exc:return _err(str(exc))

    def _hooks_description(self,ctx):
        plan=ctx.get('_hook_plan',{})
        return 'Regras de ferramentas do projeto (padrões bloqueados): '+json.dumps(plan.get('deny_tools',[]),ensure_ascii=False)+'. Hooks ativados pela app: '+json.dumps([dict(id=h['id'],event=h['event'],tool=h.get('tool','*')) for h in plan.get('hooks',[])],ensure_ascii=False)+'. A app executa-os automaticamente; não os invoques ou repitas manualmente. Hooks de comandos não correm nos perfis de leitura.'

    def _project_hooks(self,event,name,ctx,meta,steps):
        cancel=ctx.get('_cancel_event') or self._cancel_chat
        plan=ctx.get('_hook_plan',{});root=ctx.get('_guidance_root') or ctx.get('base')
        approve=lambda h:self._approve('hook:'+h['id'],'Hook do projeto: '+h['id'],subprocess.list2cmdline(h['argv']),ctx)
        if event=='task_end' and not ctx.get('readonly'):
            for h,args in project_hooks.pending(plan,ctx.get('_recovery_journal')):
                ctx['_hook_trigger']=args.get('trigger','')
                try:passed=project_hooks.run(dict(hooks=[h]),args['event'],args['tool'],root,meta,self._commands,ctx,steps,approve,cancel)
                finally:ctx.pop('_hook_trigger',None)
                if not passed:ctx['_hooks_blocked']=True;return False
        result=project_hooks.run(plan,event,name,root,meta,self._commands,ctx,steps,approve,cancel)
        if not result:ctx['_hooks_blocked']=True
        return result

    def get_project_validation(self, run_id: str = '') -> dict:
        try:
            cfg=config.load_config();meta,root=config.resolve_context(cfg)
            return _ok(plan=project_validation.discover(root),runs=project_validation.listing(meta),run=project_validation.load(meta,run_id) if run_id else None)
        except Exception as exc:return _err(str(exc))

    def _validation_approval(self,ctx):
        return lambda check:self._approve('validation','Preparar ambiente' if check['id'].startswith('setup:') else 'Verificar projeto',subprocess.list2cmdline(check['argv'])+'\n'+check['cwd'],ctx)

    def _run_validation(self,cfg,ctx,meta,ids=None,prepare=False,cancel=None):
        if not ctx.get('on') or ctx.get('readonly'):raise ValueError('Ativa o perfil Implementar e o modo agente para executar verificações.')
        root=ctx.get('_guidance_root') or ctx['base']
        run=self._validations.start(meta,root,ids,prepare,self._validation_approval(ctx),cancel)
        return self._validations.wait(meta,run['id'],cancel)

    def _recovery_validation(self,cfg,ctx,meta,cancel):
        if project_hooks.denied(ctx.get('_hook_plan',{}),'projeto_validar'):
            return dict(state='failed',checks=[],message='A validação automática foi bloqueada por deny_tools: projeto_validar.')
        journal=ctx.get('_recovery_journal');action=None
        if journal:
            if journal.unknown():return dict(state='needs_resolution',checks=[],message='Existem operações com resultado desconhecido. Confirma-as na interface antes de executar novas verificações.')
            action=journal.begin(dict(name='projeto_validar',arguments={'automatic':True}),True)
        try:
            report=self._run_validation(cfg,ctx,meta,None,False,cancel)
            if action:journal.returned(action,json.dumps(report,ensure_ascii=False))
            return report
        except Exception as exc:
            if action:journal.failed(action,str(exc))
            raise

    def start_project_validation(self, ids: list = None, prepare: bool = False) -> dict:
        try:
            cfg=config.load_config();meta,root=config.resolve_context(cfg);ctx=self._agent_context(cfg)
            if not ctx.get('on') or ctx.get('readonly'):raise ValueError('Ativa o perfil Implementar e o modo agente.')
            return _ok(run=self._validations.start(meta,root,ids,prepare,self._validation_approval(ctx)))
        except Exception as exc:return _err(str(exc))

    def cancel_project_validation(self, run_id: str) -> dict:
        try:
            meta,_=config.resolve_context(config.load_config());return _ok(run=self._validations.cancel(meta,run_id))
        except Exception as exc:return _err(str(exc))

    def validate_agent_proposal(self, task_id: str, prepare: bool = False) -> dict:
        try:
            cfg=config.load_config();meta,_=config.resolve_context(cfg);task=get_task(meta,task_id);ctx=self._agent_context(cfg)
            if task['state'] in ('queued','running','cancelling'):raise ValueError('Aguarda a conclusão da tarefa.')
            if ctx.get('readonly') or not ctx.get('on'):raise ValueError('Ativa o perfil Implementar e o modo agente.')
            root=agent_isolation.workspace(meta,task_id);return _ok(run=self._validations.start(agent_isolation.folder(meta,task_id)/'metadata',root,None,prepare,self._validation_approval(ctx)))
        except Exception as exc:return _err(str(exc))

    def get_execution_limits(self) -> dict:
        cfg=config.load_config();return _ok(limits={**LIMIT_DEFAULTS,**cfg.get('preferences',{}).get('execution_limits',{})})

    def set_execution_limits(self, values: dict) -> dict:
        try:
            limits=validate_limits(values)
            if limits['cost'] and not (limits['input_per_million'] or limits['output_per_million']):raise ValueError('Configura preços por milhão de tokens para limitar custo estimado.')
            cfg=config.load_config();cfg.setdefault('preferences',{})['execution_limits']=limits;config.save_config(cfg);return _ok(limits=limits)
        except Exception as exc:return _err(str(exc))

    def get_git_workspace(self) -> dict:
        try:
            _,workspace=config.resolve_context(config.load_config());return _ok(git=git_workspace.status(workspace))
        except Exception as exc:return _err(str(exc))

    def git_workspace_action(self, operation: str, options: dict) -> dict:
        try:
            cfg=config.load_config();_,workspace=config.resolve_context(cfg)
            if operation!='diff':
                if self._agent_context(cfg).get('readonly'):raise ValueError('Seleciona Implementar antes de alterar o repositório.')
                if snapshot_active(workspace):raise ValueError('Aguarda a operação em curso no workspace.')
            return _ok(result=git_workspace.action(workspace,operation,options))
        except Exception as exc:return _err(str(exc))

    def read_git_conflict(self, filename: str) -> dict:
        try:
            _,workspace=config.resolve_context(config.load_config());root=git_workspace.root_for(workspace)
            rel=git_workspace.selected_paths(root,[filename])[0];data=read_code_bytes(root/rel)
            if data is None:raise ValueError('Ficheiro inexistente.')
            return _ok(content=data.decode('utf-8-sig'),sha256=file_digest(data))
        except Exception as exc:return _err(str(exc))

    def save_git_conflict(self, filename: str, content: str, sha256: str) -> dict:
        try:
            cfg=config.load_config();ctx=self._agent_context(cfg)
            if ctx.get('readonly'):raise ValueError('Seleciona Implementar antes de resolver conflitos.')
            _,workspace=config.resolve_context(cfg);root=git_workspace.root_for(workspace);rel=git_workspace.selected_paths(root,[filename])[0];target=root/rel;before=read_code_bytes(target)
            if file_digest(before)!=sha256:raise ValueError('O ficheiro mudou entretanto. Volta a ler.')
            after=content.encode('utf-8');return _ok(result=self._commit_code([(target,before,after)],ctx,[]))
        except Exception as exc:return _err(str(exc))

    def _start_command(self,cfg,ctx,meta,command,cwd='',timeout=3600):
        if ctx.get('readonly') or not ctx.get('on'):raise ValueError('Este perfil não pode executar comandos.')
        run_cwd=_agent_cwd(ctx,cwd)
        if not self._approve_command(command,'Executar em segundo plano',command+'\n'+str(run_cwd),ctx):raise ValueError('Comando recusado.')
        _,workspace=config.resolve_context(cfg)
        return self._commands.start(meta,command,run_cwd or workspace,timeout,WorkspaceSnapshot(meta,workspace,'Processo: '+command[:100]),origin_action=ctx.get('_recovery_action'))

    def start_command_job(self, command: str, cwd: str = '', timeout: int = 3600) -> dict:
        try:
            cfg=config.load_config();meta,_=config.resolve_context(cfg)
            return _ok(job=self._start_command(cfg,self._agent_context(cfg),meta,command,cwd,timeout))
        except Exception as exc:return _err(str(exc))

    def cancel_command_job(self, job_id: str) -> dict:
        try:
            meta,_=config.resolve_context(config.load_config())
            return _ok(job=self._commands.cancel(meta,job_id))
        except Exception as exc:return _err(str(exc))
