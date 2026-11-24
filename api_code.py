"""Ponte ``Api``: código — checkpoints, diagnósticos, patches e ferramentas de ficheiros/comandos do agente.

Classe-base de ``api.Api`` (extraída de ``api.py`` sem alterações ao código).
Os métodos sem ``_`` inicial são chamados pela interface através da ponte do
pywebview. Usa atributos criados em ``Api.__init__`` e outros métodos da
instância através de ``self``.
"""

from __future__ import annotations

import config
import difflib
import json
import project_guidance
import project_validation
import subprocess
from agent_runtime import READ_TOOLS
from api_helpers import AGENT_CMD_TIMEOUT, MAX_CMD_OUTPUT, MAX_LIST_ENTRIES, MAX_READ_CHARS, _agent_cwd, _err, _ok, _rel, _resolve_in_scope
from coding_tools import Checkpoints, difference as code_diff, digest as file_digest, read as read_code_bytes, search as search_code
from command_jobs import load as load_command
from pathlib import Path
from workspace_snapshot import active as snapshot_active, recover as recover_snapshots


class CodeApi:
    def get_code_changes(self, checkpoint_id: str = '') -> dict:
        try:
            meta,workspace=config.resolve_context(config.load_config())
            store=Checkpoints(meta)
            recover_snapshots(meta)
            store.recover_abandoned()
            return _ok(checkpoints=store.list(),checkpoint=store.preview(checkpoint_id) if checkpoint_id else None,
                       lsp=self._lsp.status(),workspace=str(workspace),coverage='Edições diretas e snapshots de comandos/MCP no workspace. Exclui dependências, .git, dados da app e alterações fora do workspace; limites indicados em cada snapshot.')
        except Exception as exc:return _err(str(exc))

    def restore_code_checkpoint(self, checkpoint_id: str, redo: bool = False) -> dict:
        try:
            if not isinstance(redo,bool):return _err('Operação inválida.')
            with self._code_lock:
                if checkpoint_id in self._code_turns:return _err('O pedido ainda está em execução.')
                meta,workspace=config.resolve_context(config.load_config())
                if snapshot_active(workspace):return _err('Aguarda o processo ou ferramenta em curso antes de restaurar ficheiros.')
                result=Checkpoints(meta).restore(checkpoint_id,redo)
                for item in result['files']:self._code_reads.pop(item['path'],None)
            return _ok(checkpoint=result)
        except Exception as exc:return _err(str(exc))

    def get_code_diagnostics(self, caminho: str) -> dict:
        try:
            cfg=config.load_config();ctx=self._agent_context(cfg)
            if not ctx.get('on'):return _err('Ativa o modo agente e seleciona o projeto para consultar código.')
            target,err=_resolve_in_scope(caminho,ctx)
            if err:return _err(err)
            return _ok(result=self._lsp.diagnose(ctx['base'],target))
        except Exception as exc:return _err(str(exc))

    def _commit_code(self,updates,ctx,steps):
        with self._code_lock:
            if snapshot_active(ctx.get('_guidance_root') or ctx['base']):raise ValueError('Aguarda o processo ou ferramenta em execução antes de editar este workspace.')
            meta=ctx.get('_checkpoint_meta') or ctx.get('_standalone_checkpoint_meta')
            if not meta:meta,_=config.resolve_context(config.load_config())
            store=Checkpoints(meta);key=ctx.get('_checkpoint_id');standalone=not bool(ctx.get('_checkpoint_meta'))
            if not key:
                key=store.begin(ctx.get('_checkpoint_title','Edição de ficheiros'))
                if ctx.get('_recovery_action'):
                    cp=store.load(key);cp['recovery_action']=ctx['_recovery_action'];store.save(cp)
                if not standalone:ctx['_checkpoint_id']=key;self._code_turns.add(key)
            try:
                store.apply(key,updates)
                if any(project_validation.is_code_change(path) for path,before,after in updates):
                    ctx['_workspace_changed']=True
                    if ctx.get('_recovery_journal'):ctx['_recovery_journal'].code_changed()
                for path,before,after in updates:
                    self._code_reads[str(Path(path).resolve())]=file_digest(after)
                    steps.append(dict(kind='write',title='✎ '+_rel(str(path),ctx),body='Gravado em '+str(Path(path).resolve())+' (checkpoint '+key[:8]+')',ok=True,diff=code_diff(path,before,after)[:12000],checkpoint_id=key))
            finally:
                if standalone:store.finish(key)
        diagnostics=[]
        for path,_,after in updates[:5]:
            if after is not None and Path(path).suffix.lower() in self._lsp.installed_extensions():
                try:diagnostics.append(self._lsp.diagnose(ctx['base'],path,timeout=8))
                except Exception as exc:diagnostics.append(dict(path=str(path),status='error',message=str(exc),diagnostics=[]))
        return dict(checkpoint_id=key,files=[dict(path=str(p),sha256=file_digest(a)) for p,b,a in updates],diagnostics=diagnostics)

    def _dispatch_coding_tool(self,name,args,ctx,steps):
        try:
            if not ctx.get('on'):raise ValueError('Modo agente desativado.')
            if ctx.get('readonly') and name not in READ_TOOLS:raise ValueError('Este agente só pode ler e analisar.')
            if name in ('pesquisar_ficheiros','pesquisar_conteudo'):
                target,err=_resolve_in_scope(args.get('pasta') or '.',ctx)
                if err:raise ValueError(err)
                if not Path(target).is_dir():raise ValueError('A pasta não existe.')
                needle=args.get('texto') if name=='pesquisar_conteudo' else None
                if name=='pesquisar_conteudo' and (not isinstance(needle,str) or not needle):raise ValueError('Fornece texto para pesquisar.')
                result=search_code(target,args.get('padrao') or '*',needle,bool(args.get('distinguir_maiusculas')))
                steps.append(dict(kind='read',title=name,body=str(len(result['results']))+' resultados',ok=True))
            elif name=='ler_codigo':
                target,err=_resolve_in_scope(args.get('caminho',''),ctx)
                if err:raise ValueError(err)
                data=read_code_bytes(target)
                if data is None:raise ValueError('Ficheiro não encontrado.')
                content=data.decode('utf-8-sig');lines=content.splitlines();start=max(1,int(args.get('linha',1)));limit=max(1,min(400,int(args.get('limite',200))))
                self._code_reads[str(Path(target).resolve())]=file_digest(data)
                shown=[];budget=30000;clipped=False
                for i,line in enumerate(lines[start-1:start-1+limit],start-1):
                    part=line[:min(2000,budget)];shown.append(dict(line=i+1,text=part));budget-=len(part);clipped|=len(part)<len(line)
                    if budget<=0:break
                result=dict(path=target,sha256=file_digest(data),total_lines=len(lines),start_line=start,lines=shown,truncated=clipped or start-1+len(shown)<len(lines),instructions=project_guidance.rules(ctx.get('_guidance_root') or ctx['base'],target))
                steps.append(dict(kind='read',title='👁 '+_rel(target,ctx),body='Linhas '+str(start)+'–'+str(min(start+limit-1,len(lines))),ok=True))
            elif name=='lsp_navegar':
                target,err=_resolve_in_scope(args.get('caminho',''),ctx)
                if err:raise ValueError(err)
                result=self._lsp.navigate(ctx.get('_guidance_root') or ctx['base'],target,args.get('acao','symbols'),args.get('linha',1),args.get('coluna',1))
                steps.append(dict(kind='read',title='Navegação LSP',body=json.dumps(result,ensure_ascii=False)[:3000],ok=result['status']=='complete'))
            elif name=='lsp_diagnosticos':
                target,err=_resolve_in_scope(args.get('caminho',''),ctx)
                if err:raise ValueError(err)
                result=self._lsp.diagnose(ctx['base'],target)
                steps.append(dict(kind='read',title='Diagnósticos LSP',body=json.dumps(result,ensure_ascii=False)[:4000],ok=result['status']=='complete'))
            elif name=='aplicar_patch':
                edits=args.get('alteracoes');updates=[];seen=set()
                if not isinstance(edits,list) or not 1<=len(edits)<=20:raise ValueError('Fornece entre 1 e 20 alterações.')
                for edit in edits:
                    target,err=_resolve_in_scope(edit.get('caminho',''),ctx)
                    if err:raise ValueError(err)
                    if target in seen:raise ValueError('Agrupa a alteração de cada ficheiro numa única entrada.')
                    seen.add(target);before=read_code_bytes(target)
                    if before is None:raise ValueError('Para criar ficheiros novos usa escrever_ficheiro.')
                    if edit.get('sha256')!=file_digest(before):raise ValueError('Conflito: SHA-256 desatualizado em '+target+'. Volta a ler o ficheiro.')
                    old=edit.get('trecho_antigo');new=edit.get('trecho_novo')
                    if not isinstance(old,str) or not old or not isinstance(new,str):raise ValueError('Trechos inválidos.')
                    text=before.decode('utf-8-sig').replace('\r\n','\n');old=old.replace('\r\n','\n');new=new.replace('\r\n','\n')
                    if text.count(old)!=1:raise ValueError('O trecho antigo tem de existir exatamente uma vez em '+target+'.')
                    changed=text.replace(old,new,1)
                    if b'\r\n' in before:changed=changed.replace('\n','\r\n')
                    after=(b'\xef\xbb\xbf' if before.startswith(b'\xef\xbb\xbf') else b'')+changed.encode('utf-8')
                    if after!=before:updates.append((target,before,after))
                if not updates:result=dict(message='Sem alterações.')
                else:
                    detail='\n\n'.join(code_diff(p,b,a) for p,b,a in updates)[:12000]
                    if not self._approve('write','Aplicar patch em '+str(len(updates))+' ficheiro(s)',detail,ctx):raise ValueError('Patch recusado pelo utilizador.')
                    result=self._commit_code(updates,ctx,steps)
            else:raise ValueError('Ferramenta desconhecida.')
            return json.dumps(result,ensure_ascii=False)
        except Exception as exc:
            steps.append(dict(kind='error',title=name,body=str(exc),ok=False))
            return json.dumps(dict(error=str(exc)),ensure_ascii=False)

    def _agent_list(self, caminho, agent_ctx, steps) -> str:
        target, err = _resolve_in_scope(caminho or ".", agent_ctx)
        if err:
            steps.append({"kind": "list", "title": f"📁 {caminho}", "body": err, "ok": False})
            return err
        p = Path(target)
        if not p.exists():
            msg = f"Não existe: {target}"
            steps.append({"kind": "list", "title": f"📁 {_rel(target, agent_ctx)}", "body": msg, "ok": False})
            return msg
        if p.is_file():
            return self._agent_read(caminho, agent_ctx, steps)
        lines = []
        for i, child in enumerate(sorted(p.iterdir(), key=lambda c: (c.is_file(), c.name.lower()))):
            if i >= MAX_LIST_ENTRIES:
                lines.append("… (mais ficheiros não listados)")
                break
            lines.append(child.name + ("/" if child.is_dir() else ""))
        body = "\n".join(lines) or "(pasta vazia)"
        steps.append({"kind": "list", "title": f"📁 {_rel(target, agent_ctx)}", "body": body, "ok": True})
        return f"Conteúdo de {_rel(target, agent_ctx)}:\n{body}"

    def _agent_read(self, caminho, agent_ctx, steps) -> str:
        target, err = _resolve_in_scope(caminho, agent_ctx)
        if err:
            steps.append({"kind": "read", "title": f"👁 {caminho}", "body": err, "ok": False})
            return err
        p = Path(target)
        if not p.is_file():
            msg = f"Não é um ficheiro: {target}"
            steps.append({"kind": "read", "title": f"👁 {_rel(target, agent_ctx)}", "body": msg, "ok": False})
            return msg
        try:
            data=read_code_bytes(p)
            text=data.decode('utf-8-sig')
            self._code_reads[str(p.resolve())]=file_digest(data)
        except OSError as exc:
            msg = f"Não consegui ler: {exc}"
            steps.append({"kind": "read", "title": f"👁 {_rel(target, agent_ctx)}", "body": msg, "ok": False})
            return msg
        truncated = len(text) > MAX_READ_CHARS
        shown = text[:MAX_READ_CHARS] + ("\n… (truncado)" if truncated else "")
        steps.append({"kind": "read", "title": f"👁 {_rel(target, agent_ctx)}", "body": f"{len(text)} chars", "ok": True})
        instructions=project_guidance.rules(agent_ctx.get('_guidance_root') or agent_ctx['base'],target)
        return f"Conteúdo de {_rel(target, agent_ctx)} (sha256={file_digest(data)}):\n{shown}"+('\nInstruções locais aplicáveis:\n'+json.dumps(instructions,ensure_ascii=False) if instructions else '')

    def _agent_write(self, caminho, conteudo, agent_ctx, steps) -> str:
        target, err = _resolve_in_scope(caminho, agent_ctx)
        if err:
            steps.append({"kind": "write", "title": f"✎ {caminho}", "body": err, "ok": False})
            return err
        rel = _rel(target, agent_ctx)
        conteudo = conteudo or ""
        p = Path(target)
        before=read_code_bytes(p)
        if before is not None and self._code_reads.get(str(p.resolve()))!=file_digest(before):
            raise ValueError('Lê primeiro a versão atual do ficheiro; foi alterado ou ainda não foi lido.')
        old=(before or b'').decode('utf-8-sig')
        if before and b'\r\n' in before:conteudo=conteudo.replace('\r\n','\n').replace('\n','\r\n')
        after=(b'\xef\xbb\xbf' if before and before.startswith(b'\xef\xbb\xbf') else b'')+conteudo.encode('utf-8')
        if before==after:return 'Sem alterações: '+rel
        diff = ""
        if old != conteudo:
            diff = "\n".join(difflib.unified_diff(old.splitlines(), conteudo.splitlines(), fromfile="antes", tofile="depois", lineterm=""))[:12000]
        detail = f"{rel}\n({len(conteudo)} bytes)"
        if diff:
            detail += "\n\n" + diff[:6000]
        ok = self._approve("write", "Escrever ficheiro", detail, agent_ctx)
        if not ok:
            steps.append({"kind": "write", "title": f"✎ {rel}", "body": "(recusado pelo utilizador)", "ok": False})
            return f"Ação recusada pelo utilizador: escrever {rel}."
        try:
            result=self._commit_code([(target,before,after)],agent_ctx,steps)
        except (OSError,ValueError) as exc:
            steps.append({"kind": "write", "title": f"✎ {rel}", "body": f"erro: {exc}", "ok": False})
            return f"Não consegui escrever {rel}: {exc}"
        return json.dumps(result,ensure_ascii=False)

    def _agent_exec(self, comando, cwd, agent_ctx, steps) -> str:
        comando = (comando or "").strip()
        if not comando:
            return "Nenhum comando fornecido."
        run_cwd = _agent_cwd(agent_ctx, cwd)
        detail = comando + (f"\n(em {run_cwd})" if run_cwd else "")
        ok = self._approve_command(comando, "Executar comando", detail, agent_ctx)
        if not ok:
            steps.append({"kind": "cmd", "title": f"$ {comando}", "body": "(recusado pelo utilizador)", "ok": False})
            return f"Comando recusado pelo utilizador: {comando}"
        try:
            meta=agent_ctx.get('_checkpoint_meta')
            if not meta:meta,_=config.resolve_context(config.load_config())
            job=self._commands.start(meta,comando,run_cwd or agent_ctx['base'],AGENT_CMD_TIMEOUT,origin_action=agent_ctx.get('_recovery_action'))
            while True:
                result=load_command(meta,job['id'])
                if result['state'] not in ('starting','running','cancelling'):break
                if self._cancel_chat.wait(.1):self._commands.cancel(meta,job['id'])
            out = result.get('output') or result.get('message') or '(sem output)'
            if len(out) > MAX_CMD_OUTPUT:
                out = out[:MAX_CMD_OUTPUT] + "\n… (output truncado)"
            code=result.get('returncode');state=result['state']
            steps.append({"kind": "cmd", "title": f"$ {comando}", "body": f"[{state}; código {code}]\n{out}", "ok": state=='completed','job_id':job['id']})
            return f"Comando: {state}; código {code}.\n{out}"
        except subprocess.TimeoutExpired:
            steps.append({"kind": "cmd", "title": f"$ {comando}", "body": f"tempo esgotado ({AGENT_CMD_TIMEOUT}s)", "ok": False})
            return f"O comando excedeu {AGENT_CMD_TIMEOUT}s e foi interrompido."
        except Exception as exc:  # noqa: BLE001
            steps.append({"kind": "cmd", "title": f"$ {comando}", "body": f"erro: {exc}", "ok": False})
            return f"Erro ao executar: {exc}"
