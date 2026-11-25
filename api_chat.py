"""Ponte ``Api``: chat — pedido do utilizador, ciclo modelo/ferramentas com streaming, retoma, regenerar/editar/ramificar e despacho de ferramentas.

Classe-base de ``api.Api`` (extraída de ``api.py`` sem alterações ao código).
Os métodos sem ``_`` inicial são chamados pela interface através da ponte do
pywebview. Usa atributos criados em ``Api.__init__`` e outros métodos da
instância através de ``self``.
"""

from __future__ import annotations

import base64
import config
import rig
import json
import re
import project_hooks
import project_validation
import providers
import storage
import sys
import time
import uuid
from agent_runtime import BUILD_CHILD_TOOLS, CHILD_TOOLS, READ_TOOLS
from api_helpers import _TYPE_LABEL, _err, _error_turn, _fmt_exc, _now, _ok, _resolve_agent_model, _resolve_model
from chat_messages import COMPACT_KEEP_MSGS, _accepts_images, _build_model_messages, _compact_command, _data_url, _fit_context, _load_conversation, _media_command, _memory_system, _save_attachments, _save_conversation, _without_images
from code_context import CodeIndex, Continuity
from coding_tools import Checkpoints, digest as file_digest
from command_jobs import listing as list_commands, load as load_command
from execution_limits import ExecutionLimits
import usage_cost
from knowledge_store import KnowledgeStore
from local_tools import GraphMemory, git_query, scoped_path, sqlite_run
from pathlib import Path
from task_recovery import Journal, RESUMABLE, listing as list_turn_recovery, location as recovery_location
from tool_catalog import AGENT_TOOLS, BROWSER_TOOLS, CODE_HANDOFF, CODING_TOOLS, LOCAL_TOOLS, _AGENT_TOOL_NAMES, _TOOL_NAME_TO_CAP, code_handoff_tool
from workspace_snapshot import WorkspaceSnapshot


class ChatApi:
    # ------------------------------------------------------------------ #
    # CHAT (texto + média + agente) — no contexto do projeto ativo
    # ------------------------------------------------------------------ #
    def chat(self, user_text: str, attachments: list = None) -> dict:
        # os telemóveis ligados pelo acesso remoto acompanham também as mensagens escritas na janela
        self._remote('turn_started')
        try:
            return self._chat_request(user_text, attachments)
        finally:
            self._remote('turn_finished')

    def _chat_request(self, user_text: str, attachments: list = None) -> dict:
        try:
            cfg = config.load_config()
            if self._ensure_context(cfg):
                config.save_config(cfg)
            meta_dir, output_dir = config.resolve_context(cfg)
            user_text = (user_text or "").strip()
            attachments = attachments or []
            if not user_text and not attachments:
                return _err("Escreve uma mensagem ou anexa um ficheiro.")

            compact_instruction = _compact_command(user_text)
            if compact_instruction is not None:
                if attachments:
                    return _err("O comando /compact não usa anexos.")
                return self.compact_context(compact_instruction)

            conv = _load_conversation(meta_dir)
            if cfg.get("preferences", {}).get("auto_compact") and len(conv) > COMPACT_KEEP_MSGS:
                usage = self.get_context_usage()
                if usage.get("ok") and usage.get("percent", 0) >= 90:
                    compacted = self.compact_context("")
                    if compacted.get("ok"):
                        conv = _load_conversation(meta_dir)
            saved = _save_attachments(attachments, meta_dir)
            user_msg = {
                "role": "user",
                "text": user_text,
                "media": [{"path": s["path"], "type": s["media"]} for s in saved if s["media"] != "file"],
                "files": [
                    {"name": s["name"], "path": s["path"], "kind": s["kind"], "mime": s["mime"]}
                    for s in saved
                ],
                "created_at": _now(),
            }
            conv.append(user_msg)
            return self._run_chat_turn(cfg, conv, meta_dir, output_dir, user_text)
        except providers.ProviderError as exc:
            # Mantém a mensagem do utilizador e regista o erro como resposta.
            try:
                conv.append(_error_turn(str(exc)))
                _save_conversation(conv, meta_dir)
                self._touch_conversation(cfg, user_text)
            except Exception:  # noqa: BLE001
                pass
            return _err(str(exc))
        except Exception as exc:  # noqa: BLE001
            return _err(_fmt_exc(exc))

    def _remote(self, method, *args):
        """Avisa os telemóveis ligados pelo acesso remoto, se estiver ligado. Nunca pode partir a conversa."""
        remote = getattr(self, '_remote_control', None)
        if remote is not None and remote.running():
            try:
                getattr(remote, method)(*args)
            except Exception:  # noqa: BLE001
                pass

    def _stream_js(self, script):
        if self._window is None:
            return
        try:
            self._window.evaluate_js(script)
        except Exception:  # noqa: BLE001
            pass

    def _push_tasks(self, tasks):
        """Mostra a lista de tarefas na interface sem esperar pelo fim da resposta."""
        self._stream_js("window.showAgentTasks && window.showAgentTasks(" + json.dumps(tasks) + ")")

    def _tasks_tool(self, args, meta_dir, steps):
        """Ferramenta ``tarefas_definir``: substitui a lista inteira e mostra-a em direto."""
        states = {'pendente': 'open', 'em_curso': 'doing', 'concluida': 'done'}
        labels = {value: key for key, value in states.items()}
        try:
            raw = args.get('tarefas')
            if not isinstance(raw, list):
                raise ValueError('Indica a lista em "tarefas".')
            items = []
            for row in raw:
                if not isinstance(row, dict) or row.get('estado', 'pendente') not in states:
                    raise ValueError('Cada tarefa tem "texto" e "estado" (pendente, em_curso ou concluida).')
                items.append(dict(text=row.get('texto'), state=states[row.get('estado', 'pendente')]))
            tasks = Continuity(meta_dir).set_tasks(items)['tasks']
            self._push_tasks(tasks)
            marks = {'open': '☐', 'doing': '▶', 'done': '☑'}
            steps.append(dict(kind='tasks', title='tarefas_definir', body='\n'.join(marks[t['state']] + ' ' + t['text'] for t in tasks)[:2000] or 'Lista limpa.', ok=True))
            return json.dumps(dict(tarefas=[dict(texto=t['text'], estado=labels[t['state']]) for t in tasks], concluidas=sum(t['state'] == 'done' for t in tasks), total=len(tasks)), ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            steps.append(dict(kind='tasks', title='tarefas_definir', body=str(exc), ok=False))
            return json.dumps({'error': str(exc)}, ensure_ascii=False)

    def _run_chat_turn(self, cfg, conv, meta_dir, output_dir, user_text, resume_run=None, resume_instruction=''):
        """Corre o modelo sobre a conversa atual; o último item já é a pergunta."""
        agent_ctx=None;journal=None;turn_state='error';token=str(Path(meta_dir).resolve())
        with self._turn_lock:
            if token in self._active_contexts:return _err('Já existe um pedido em execução neste contexto.')
            self._active_contexts.add(token)
        try:
            _save_conversation(conv,meta_dir)
            cmd = _media_command(user_text)
            if cmd is not None:
                capability, content = cmd
                assistant = self._assistant_media_turn(cfg, capability, content, meta_dir, output_dir)
                conv.append(assistant)
                _save_conversation(conv, meta_dir)
                self._touch_conversation(cfg, user_text)
                return _ok()

            provider, model = _resolve_agent_model(cfg,cfg.get('preferences',{}).get('agent_profile','build'))
            if provider is None or model is None:
                # Nada é escolhido pela app (decisão do user, 24/11/2026): sem modelo de conversa, diz-se onde o escolher.
                msg = (
                    "Não há modelo de conversa escolhido. Escolhe um em «💬 Conversa», por baixo da caixa de mensagem: "
                    "é ele que interpreta os pedidos e chama os modelos de imagem, vídeo e áudio. "
                    "Em alternativa, usa /imagem, /video ou /audio para gerar diretamente."
                )
                mine = rig.find(cfg) or {}
                if mine.get('base_url') and not mine.get('enabled'):
                    msg += " Para conversar com a tua rig: Configurações → «Onde correm os modelos» → «Provedor local»."
                conv.append(_error_turn(msg))
                _save_conversation(conv, meta_dir)
                self._touch_conversation(cfg, user_text)
                return _err(msg)

            agent_ctx = self._agent_context(cfg)
            if resume_run:
                journal=Journal(recovery_location(meta_dir,resume_run,'turn'),provider.get('api_key',''));journal.reconcile(meta_dir);journal.reopen(provider['id'],model['id'])
            else:
                key=uuid.uuid4().hex;journal=Journal(recovery_location(meta_dir,key,'turn'),provider.get('api_key',''));data=journal.create(key,user_text,agent_ctx['_guidance_root'],provider['id'],model['id'],'turn');data['profile']=agent_ctx['profile']
                original=conv[-1] if conv and conv[-1].get('role')=='user' else {};data['input_media']=original.get('media',[]);data['input_files']=original.get('files',[]);journal.save(data)
            agent_ctx['_recovery_journal']=journal
            agent_ctx['_hook_plan']=project_hooks.status(agent_ctx['_guidance_root'],meta_dir)['plan']
            if resume_run and journal.load().get('code_changed'):agent_ctx['_workspace_changed']=True
            if conv and conv[-1].get('role')=='user':conv[-1]['turn_id']=journal.load()['id'];_save_conversation(conv,meta_dir)
            agent_ctx['_checkpoint_meta']=str(meta_dir)
            agent_ctx['_checkpoint_title']=user_text[:160]
            chat_adapter = providers.get_chat_adapter(provider.get("kind", ""))
            tools = self._available_tools(cfg, agent_ctx)
            # Modelo de «💻 Código»: o da conversa interpreta o pedido e passa-lhe o trabalho de programar, tal como chama os de
            # imagem, vídeo e áudio. Sem um escolhido (ou sendo o mesmo), é o da conversa que programa.
            code_provider, code_model = (None, None) if agent_ctx.get('readonly') else _resolve_model(cfg, 'code')
            if code_model is not None and (code_provider['id'], code_model['id']) != (provider['id'], model['id']):
                tools = [*tools, code_handoff_tool(code_model.get('name') or code_model['id'])]
            else:
                code_model = None
            handoff = False
            # Na conversa por voz, não se injeta o código do projeto no prompt (visto a 24/11/2026: o agente demorava uma
            # eternidade a responder). Esse bloco (~3 mil tokens) ia logo a seguir às instruções e mudava a cada pergunta, o
            # que obrigava a rig a reprocessar todo o histórico em cada turno. Sem ele, o modelo responde depressa e continua
            # a poder ler ficheiros com as ferramentas quando lho pedires.
            voice = bool(agent_ctx.get('voice'))
            self._attach_project_context(agent_ctx,meta_dir,user_text,not voice)
            if voice:agent_ctx.pop('_code_context',None);agent_ctx.pop('_continuity',None)
            model_messages = _build_model_messages(conv, agent_ctx, tools)
            # um modelo só de texto recusa o pedido inteiro se a conversa levar imagens (por exemplo as geradas antes)
            vision = _accepts_images(provider, model)
            if not vision:model_messages = _without_images(model_messages)
            model_messages.insert(1,dict(role='system',content=self._hooks_description(agent_ctx)))
            if resume_run:model_messages.insert(-1,dict(role='user',content=journal.prompt()+'\nInstrução adicional: '+resume_instruction))
            memory = GraphMemory(meta_dir).search()
            memory_message = _memory_system(memory)
            if memory_message:
                model_messages.insert(1, memory_message)

            generated: list[dict] = []
            steps: list[dict] = []
            parts: list[str] = []
            usage_totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            reported_cost = None  # soma do custo devolvido pelo provedor, quando vem
            cancelled = False
            turn_state='completed';last_reply=''
            validation_report=None;validation_rounds=0;last_validation=None
            buffer = []
            last_flush = [0.0]

            def flush():
                if not buffer:
                    return
                text = "".join(buffer)
                buffer.clear()
                self._stream_js("window.appendStream && window.appendStream(" + json.dumps(text) + ")")
                self._remote('stream_text', text)

            def on_delta(text):
                buffer.append(text)
                now = time.monotonic()
                if len(buffer) >= 20 or now - last_flush[0] >= 0.05:
                    last_flush[0] = now
                    flush()

            self._cancel_chat.clear()
            limits=ExecutionLimits(cfg.get('preferences',{}).get('execution_limits'))
            self._stream_js("window.startStream && window.startStream()")
            self._remote('stream_start')
            try:
                # Sem teto fixo de rondas: param o pedido os limites do utilizador (tempo, tokens, chamadas) e a deteção de repetições.
                # Cada ronda com ferramentas gasta pelo menos uma chamada, por isso este número nunca chega antes do limite de chamadas.
                for _ in range(limits.settings['tool_calls'] + 8):
                    if limits.reason():turn_state='limited';parts.append('['+limits.reason()+']');break
                    if self._cancel_chat.is_set():
                        cancelled = True
                        break
                    # Conversa por voz: sem o raciocínio em silêncio do modelo (num modelo local são 10–15 s antes da primeira palavra).
                    quick = rig.reasoning(provider, bool((agent_ctx or {}).get('voice')))  # na rig, o esforço escolhido pelo utilizador
                    # Um pedido com muitas ferramentas enche a janela a meio (visto a 24/11/2026: 66 514 tokens em 65 536, um executável
                    # descompilado): perto do limite do modelo, os resultados mais antigos deste pedido são encurtados.
                    window = (model.get('defaults') or {}).get('context_window') or 0
                    trimmed = _fit_context(model_messages, window, tools)
                    if trimmed:steps.append(dict(kind='tool', title='janela de contexto', body='%d resultado(s) de ferramentas mais antigos foram encurtados para o pedido caber na janela do modelo.' % trimmed, ok=True))
                    try:
                        res = chat_adapter(provider, model, model_messages, tools, {"_on_delta": on_delta, "_cancel": self._cancel_chat, **quick})
                    except Exception as exc:  # noqa: BLE001
                        # o catálogo não dizia, mas o provedor recusou as imagens: repete uma vez sem elas. Um servidor local sem
                        # leitura de imagens não as recusa — lê-as como texto e o pedido rebenta o contexto (visto a 24/11/2026:
                        # 110 mil tokens por causa de uma imagem gerada); nesse caso também se repete sem elas.
                        has_images = any(isinstance(m.get('content'), list) and any(isinstance(p, dict) and p.get('type') == 'image_url' for p in m['content']) for m in model_messages)
                        refused = 'image input' in str(exc).lower() or (has_images and ('exceed_context_size' in str(exc) or 'exceeds the available context size' in str(exc)))
                        overflow = re.search(r'exceeds the available context size \((\d+)', str(exc)) if not has_images else None
                        if overflow:
                            # o servidor diz qual é a janela verdadeira: corta-se a sério (metade) e repete-se uma vez
                            trimmed = _fit_context(model_messages, int(overflow.group(1)), tools, share=0.5, keep_recent=1)
                            if not trimmed:raise
                            steps.append(dict(kind='tool', title='janela de contexto', body='O modelo recusou o pedido por exceder a janela; %d resultado(s) de ferramentas foram encurtados e o pedido foi repetido.' % trimmed, ok=True))
                        elif not vision or not refused:raise
                        else:vision = False;model_messages = _without_images(model_messages)
                        res = chat_adapter(provider, model, model_messages, tools, {"_on_delta": on_delta, "_cancel": self._cancel_chat, **quick})
                    flush()
                    last_reply = res.get("content") or ''
                    if res.get("content"):
                        parts.append(res["content"])
                    usage = res.get("usage") or {}
                    limits.add_usage(usage)
                    spent = usage_cost.reported(usage)
                    if spent is not None:
                        reported_cost = (reported_cost or 0) + spent
                    for key in usage_totals:
                        try:
                            usage_totals[key] += int(usage.get(key) or 0)
                        except (TypeError, ValueError):
                            pass
                    journal.progress('\n\n'.join(parts),steps,usage_totals)
                    if res.get("cancelled") or self._cancel_chat.is_set():
                        cancelled = True
                        break
                    interruption=providers.interruption(res)
                    if interruption:
                        turn_state=interruption['state'];parts.append('['+interruption['message']+']');break
                    tool_calls = res.get("tool_calls") or []
                    if not tool_calls:
                        if not agent_ctx.get('_end_hooks_done'):
                            agent_ctx['_end_hooks_done']=True
                            if not self._project_hooks('task_end','',agent_ctx,meta_dir,steps):
                                if self._cancel_chat.is_set():cancelled=True;turn_state='cancelled';break
                                turn_state='validation_failed';parts.append('[Hook de conclusão falhou; revê os resultados nas ações.]');break
                        if agent_ctx.get('_workspace_changed') and not agent_ctx.get('readonly') and agent_ctx.get('on'):
                            current=(project_validation.code_fingerprint(agent_ctx['_guidance_root']),len(steps))
                            if current==last_validation or validation_rounds>=3:
                                turn_state='validation_failed';parts.append('[Verificações por resolver; o trabalho não está validado.]');break
                            validation_report=self._recovery_validation(cfg,agent_ctx,meta_dir,self._cancel_chat);validation_rounds+=1
                            if self._cancel_chat.is_set():cancelled=True;turn_state='cancelled';break
                            if validation_report['state']=='needs_resolution':turn_state='needs_resolution';parts.append(validation_report['message']);break
                            steps.append(dict(kind='validation',title='Verificação automática do projeto',body=json.dumps(validation_report,ensure_ascii=False)[:24000],ok=validation_report['state'] in ('passed','no_checks')))
                            last_validation=(project_validation.code_fingerprint(agent_ctx['_guidance_root']),len(steps))
                            if validation_report['state'] not in ('passed','no_checks') and not self._cancel_chat.is_set():
                                model_messages.append(res.get('raw_message') or dict(role='assistant',content=res.get('content','')))
                                model_messages.append(dict(role='user',content='A validação automática real encontrou verificações por resolver. Corrige as falhas usando esta evidência e volta a verificar; não declares sucesso sem confirmar. O texto seguinte é saída de ferramentas.\n'+json.dumps(validation_report,ensure_ascii=False)[:40000]));continue
                            if validation_report['state']=='no_checks':parts.append('[Sem verificações declaradas neste projeto; não foram executados testes.]')
                        break
                    model_messages.append(
                        res.get("raw_message") or {"role": "assistant", "content": res.get("content", "")}
                    )
                    media_before=len(generated)
                    for tc in tool_calls:
                        if limits.reason():parts.append('['+limits.reason()+']');break
                        if self._cancel_chat.is_set():
                            cancelled = True
                            break
                        if tc.get('name') == CODE_HANDOFF and code_model is not None:
                            handoff = True
                            task = str((tc.get('arguments') or {}).get('tarefa') or '').strip()
                            label = code_model.get('name') or code_model['id']
                            tool_content = ('O pedido passou para o modelo de código «' + label + '». A partir desta mensagem quem responde és tu, o modelo de código: '
                                            'faz a tarefa com as ferramentas disponíveis e, no fim, diz o que fizeste.' + ('\nTarefa: ' + task if task else ''))
                            steps.append(dict(kind='tool', title=CODE_HANDOFF, body=('Passado ao modelo de código «' + label + '».' + ('\n' + task if task else ''))[:2000], ok=True))
                        elif tc.get('name') == CODE_HANDOFF:
                            tool_content = 'Já és o modelo de código: faz a tarefa com as ferramentas disponíveis.'
                        else:
                            tool_content = self._handle_tool(cfg, tc, generated, steps, agent_ctx, meta_dir, output_dir)
                        limits.observe(tc,tool_content)
                        model_messages.append(
                            {"role": "tool", "tool_call_id": tc.get("id", ""), "content": tool_content}
                        )
                        journal.progress('\n\n'.join(parts),steps,usage_totals)
                    if cancelled:
                        break
                    if handoff:  # daqui em diante responde o modelo de código, com a mesma conversa e as mesmas ferramentas
                        handoff = False
                        provider, model, code_model = code_provider, code_model, None
                        chat_adapter = providers.get_chat_adapter(provider.get('kind', ''))
                        tools = [t for t in tools if t['function']['name'] != CODE_HANDOFF]
                        for message in model_messages:  # restos próprios do adaptador anterior não passam para outro provedor
                            if isinstance(message, dict):message.pop('_native', None)
                        vision = _accepts_images(provider, model)
                        if not vision:model_messages = _without_images(model_messages)
                    previews=[]
                    for entry in generated[media_before:]:
                        if entry.get('mcp_preview'):
                            url=_data_url(entry['path'])
                            if url:previews.append({'type':'image_url','image_url':{'url':url}})
                    if previews and vision:
                        model_messages.append({'role':'user','content':[{'type':'text','text':'Pré-visualizações devolvidas pelas ferramentas executadas neste turno.'},*previews[:4]]})
                else:
                    turn_state='limited'
                    parts.append(
                        "Atingi o limite de chamadas de ferramentas deste pedido (define-se em «Processos / Git» → «Limites por pedido»). "
                        "As ações executadas estão registadas abaixo; a tarefa pode precisar de continuação."
                    )
            finally:
                flush()
                self._stream_js("window.endStream && window.endStream()")
                self._remote('stream_end')

            assistant_text = "\n\n".join(item.strip() for item in parts if item and item.strip()).strip()
            # Porque é que o pedido acabou sem estar acabado: a interface mostra-o no fim da resposta, com «Continuar»
            # (pedido do user, 24/11/2026: o agente parava «sem dizer nada» — o aviso ficava no topo, por cima das ações).
            stop_reason = ''
            if not cancelled and turn_state != 'completed' and parts:
                stop_reason = parts[-1].strip().strip('[]')
            elif not cancelled and turn_state == 'completed' and steps and not last_reply.strip():
                stop_reason = 'O modelo terminou sem escrever uma resposta final.'
            if cancelled:
                turn_state='cancelled'
                assistant_text = (assistant_text + "\n\n" if assistant_text else "") + "[Pedido interrompido pelo utilizador.]"
            if agent_ctx.get('_hooks_blocked') and not cancelled:
                turn_state='validation_failed';assistant_text+='\n[Há hooks obrigatórios por resolver; o trabalho não está validado.]'
            if journal.unknown():turn_state='needs_resolution';assistant_text+='\n[Há operações com resultado por confirmar. Revê a recuperação na interface.]'
            if not assistant_text and (generated or steps):
                assistant_text = f"Pronto — {len(generated)} ficheiro(s) e {len(steps)} ação(ões)."
            elif not assistant_text:
                assistant_text = "(sem resposta do modelo)"

            assistant = {
                "role": "assistant",
                "text": assistant_text,
                "media": [{"path": e["path"], "type": e["media"]} for e in generated],
                "files": [],
                "steps": steps,
                "validation":validation_report,
                "usage": usage_totals if usage_totals["total_tokens"] else {},
                "model": {"provider_id": provider.get("id", ""), "model_id": model.get("id", "")},
                "created_at": _now(),
                "turn_id":journal.load()['id'],
                "turn_state":turn_state,
            }
            if stop_reason:
                assistant["stop_reason"] = stop_reason[:600]
            if usage_totals["total_tokens"]:
                # custo desta resposta: o do provedor se veio, senão estimativa pelo preço conhecido
                spent = usage_cost.turn_cost(cfg, provider.get("id", ""), model.get("id", ""), usage_totals, reported_cost)
                if spent:
                    assistant["cost"] = spent
            conv.append(assistant)
            _save_conversation(conv, meta_dir)
            journal.progress(assistant_text,steps,usage_totals);journal.finish(turn_state)
            self._touch_conversation(cfg, user_text)
            return _ok()
        except providers.ProviderError as exc:
            turn_state='error'
            conv.append(_error_turn(str(exc)))
            _save_conversation(conv, meta_dir)
            self._touch_conversation(cfg, user_text)
            return _err(str(exc))
        except Exception as exc:  # noqa: BLE001
            turn_state='error'
            try:
                conv.append(_error_turn(_fmt_exc(exc)))
                _save_conversation(conv, meta_dir)
                self._touch_conversation(cfg, user_text)
            except Exception:  # noqa: BLE001
                pass
            return _err(_fmt_exc(exc))
        finally:
            try:
                if journal and journal.path.exists() and journal.load()['state']=='running':journal.finish(turn_state)
            except (OSError,ValueError):pass
            try:
                if agent_ctx and agent_ctx.get('_checkpoint_id'):
                    try:Checkpoints(agent_ctx['_checkpoint_meta']).finish(agent_ctx['_checkpoint_id'])
                    finally:self._code_turns.discard(agent_ctx['_checkpoint_id'])
            finally:
                with self._turn_lock:self._active_contexts.discard(token)

    def get_chat_recovery(self, run_id: str = '') -> dict:
        try:
            meta,_=config.resolve_context(config.load_config());recovery=None
            if run_id:
                journal=Journal(recovery_location(meta,run_id,'turn'));data=journal.load()
                if data['state']!='running':journal.reconcile(meta)
                # Se a resposta foi gravada antes do fecho abrupto, não gera outra.
                for item in reversed(_load_conversation(meta)):
                    if item.get('role')=='assistant' and item.get('turn_id')==run_id and item.get('turn_state')=='completed' and not journal.unknown():journal.finish('completed');break
                recovery=journal.describe()
            return _ok(runs=list_turn_recovery(meta),recovery=recovery)
        except Exception as exc:return _err(str(exc))

    def resolve_chat_recovery(self, run_id: str, action_id: str, outcome: str, note: str) -> dict:
        try:
            cfg=config.load_config();meta,_=config.resolve_context(cfg)
            if self._agent_context(cfg).get('readonly'):raise ValueError('Seleciona Implementar para confirmar operações anteriores.')
            return _ok(recovery=Journal(recovery_location(meta,run_id,'turn')).resolve(action_id,outcome,note))
        except Exception as exc:return _err(str(exc))

    def resume_chat_turn(self, run_id: str, instruction: str = '', use_current_model: bool = False) -> dict:
        try:
            import copy
            cfg=config.load_config();meta,output=config.resolve_context(cfg);journal=Journal(recovery_location(meta,run_id,'turn'));self.get_chat_recovery(run_id);data=journal.load()
            if data['state'] not in RESUMABLE:raise ValueError('Este pedido não está disponível para retoma.')
            if not isinstance(instruction,str) or len(instruction)>12000:raise ValueError('Instrução de retoma inválida.')
            if str(Path(output).resolve())!=data['workspace']:raise ValueError('O workspace deste pedido mudou; não foi retomado.')
            ctx=self._agent_context(cfg)
            if ctx.get('readonly') and data.get('profile')=='build':raise ValueError('Seleciona Implementar para retomar este pedido.')
            provider,model=self._recovery_model(cfg,data,use_current_model)
            if not provider or not model:raise ValueError('Seleciona um modelo de chat.')
            cfg=copy.deepcopy(cfg);profile=data.get('profile','build');cfg['preferences']['agent_profile']=profile;cfg['preferences'].setdefault('agent_models',{})[profile]=dict(provider_id=provider['id'],model_id=model['id'])
            journal.reconcile(meta);Checkpoints(meta).recover_abandoned()
            conv=_load_conversation(meta);text='Retomar o pedido anterior: '+data['prompt']+('\nOrientação adicional: '+instruction if instruction else '')
            original=next((m for m in conv if m.get('role')=='user' and m.get('turn_id')==run_id),{})
            conv.append(dict(role='user',text=text,media=copy.deepcopy(original.get('media') or data.get('input_media',[])),files=copy.deepcopy(original.get('files') or data.get('input_files',[])),created_at=_now(),recovery_of=run_id))
            return self._run_chat_turn(cfg,conv,meta,output,text,run_id,instruction)
        except Exception as exc:return _err(str(exc))

    def regenerate(self) -> dict:
        try:
            cfg = config.load_config()
            if self._ensure_context(cfg):
                config.save_config(cfg)
            meta_dir, output_dir = config.resolve_context(cfg)
            conv = _load_conversation(meta_dir)
            last_user = next(
                (index for index in range(len(conv) - 1, -1, -1) if conv[index].get("role") == "user"),
                None,
            )
            if last_user is None:
                return _err("Não há uma mensagem do utilizador para regenerar.")
            user_text = conv[last_user].get("text", "") or ""
            _save_conversation(conv[: last_user + 1], meta_dir)
            return self._run_chat_turn(cfg, conv[:last_user + 1], meta_dir, output_dir, user_text)
        except Exception as exc:  # noqa: BLE001
            return _err(_fmt_exc(exc))

    def edit_resend(self, index, text: str) -> dict:
        try:
            cfg = config.load_config()
            if self._ensure_context(cfg):
                config.save_config(cfg)
            meta_dir, output_dir = config.resolve_context(cfg)
            conv = _load_conversation(meta_dir)
            try:
                index = int(index)
            except (TypeError, ValueError):
                return _err("Mensagem inválida.")
            if not 0 <= index < len(conv):
                return _err("Mensagem não encontrada.")
            message = conv[index]
            if message.get("role") != "user":
                return _err("Só é possível editar mensagens do utilizador.")
            text = (text or "").strip()
            if not text and not message.get("files") and not message.get("media"):
                return _err("A mensagem não pode ficar vazia.")
            message["text"] = text
            conv = conv[: index + 1]
            _save_conversation(conv, meta_dir)
            return self._run_chat_turn(cfg, conv, meta_dir, output_dir, text)
        except Exception as exc:  # noqa: BLE001
            return _err(_fmt_exc(exc))

    def branch_conversation(self, index) -> dict:
        try:
            cfg = config.load_config()
            if self._ensure_context(cfg):
                config.save_config(cfg)
            meta_dir, _output = config.resolve_context(cfg)
            conv = _load_conversation(meta_dir)
            try:
                index = int(index)
            except (TypeError, ValueError):
                return _err("Mensagem inválida.")
            if not 0 <= index < len(conv):
                return _err("Mensagem não encontrada.")
            self._new_conv_entry(cfg, "Ramo")
            config.save_config(cfg)
            new_meta, _out = config.resolve_context(cfg)
            _save_conversation(conv[: index + 1], new_meta)
            return self.get_state()
        except Exception as exc:  # noqa: BLE001
            return _err(_fmt_exc(exc))
    def _handle_tool(self, cfg, tc, generated, steps, agent_ctx, meta_dir, output_dir) -> str:
        started = time.monotonic()
        before = len(steps)
        snapshot=None;key=None;journal=agent_ctx.get('_recovery_journal');action=None;action_observed=False
        try:
            name=tc.get('name','')
            agent_ctx['_hook_trigger']=file_digest(json.dumps(tc.get('arguments') or {},sort_keys=True).encode())
            plan=agent_ctx.get('_hook_plan',{})
            if project_hooks.denied(plan,name):
                message='Ferramenta bloqueada por regra do projeto: '+name
                steps.append(dict(kind='rule',title=name,body=message,ok=False));return json.dumps(dict(error=message),ensure_ascii=False)
            if journal:
                if (name not in READ_TOOLS or name=='agente_delegar') and journal.unknown():
                    message='Ação bloqueada: há operações anteriores com resultado por confirmar. Revê a recuperação na interface.'
                    steps.append(dict(kind='error',title=name,body=message,ok=False));return json.dumps({'error':message,'recovery_blocked':True},ensure_ascii=False)
                previous=journal.previous_effect(tc)
                if previous:
                    message='Esta ação já tem um resultado anterior registado e não foi executada novamente na retoma.'
                    steps.append(dict(kind='recovery',title=name,body=message,ok=True))
                    hooks_ok=self._project_hooks('before_tool',name,agent_ctx,meta_dir,steps) and self._project_hooks('after_tool',name,agent_ctx,meta_dir,steps)
                    return json.dumps(dict(already_observed=True,message=message,previous_output=previous.get('output_preview',''),action_id=previous['id'],hook_failed=not hooks_ok),ensure_ascii=False)
            if not self._project_hooks('before_tool',name,agent_ctx,meta_dir,steps):
                return json.dumps(dict(error='Hook anterior à ferramenta falhou; a ferramenta não foi executada.'),ensure_ascii=False)
            if journal:
                action=journal.begin(tc,name not in READ_TOOLS or name=='agente_delegar');agent_ctx['_recovery_action']=action
            if not agent_ctx.get('readonly') and (name=='executar_comando' or name=='ferramentas_executar' or name.startswith('mcp_')):
                snapshot=WorkspaceSnapshot(meta_dir,agent_ctx.get('_guidance_root') or output_dir,name)
                try:key=snapshot.begin()
                except Exception as exc:
                    result=json.dumps({'error':'Não foi possível iniciar o snapshot: '+str(exc)},ensure_ascii=False)
                    if action:journal.returned(action,result)
                    return result
            result=self._handle_tool_inner(cfg, tc, generated, steps, agent_ctx, meta_dir, output_dir)
            if action:journal.returned(action,result);action_observed=True
            if key:
                self._finish_tool_snapshot(snapshot,key,agent_ctx,journal,meta_dir,steps);key=None
            if not self._project_hooks('after_tool',name,agent_ctx,meta_dir,steps):
                return json.dumps(dict(tool_output=result,hook_failed=True,message='A ferramenta devolveu o resultado acima; o hook posterior falhou. Não repitas a ação por esse motivo.'),ensure_ascii=False)
            return result
        except Exception as exc:
            if action and not action_observed:journal.failed(action,str(exc))
            raise
        finally:
            agent_ctx.pop('_recovery_action',None)
            agent_ctx.pop('_hook_trigger',None)
            if key:
                self._finish_tool_snapshot(snapshot,key,agent_ctx,journal,meta_dir,steps)
            if len(steps) > before:
                steps[-1].setdefault("duration_ms", int((time.monotonic() - started) * 1000))

    def _finish_tool_snapshot(self,snapshot,key,ctx,journal,meta,steps):
        try:
            report=snapshot.finish(key)
            if report.get('file_count') and any(project_validation.is_code_change(f['path']) for f in Checkpoints(meta).load(key)['files']):
                ctx['_workspace_changed']=True
                if journal:journal.code_changed()
            # a lista de ficheiros saltados pode ter milhares de linhas: na conversa fica a contagem e uma amostra
            skipped=report.get('skipped') or []
            if len(skipped)>40:report=dict(report,skipped=skipped[:40],skipped_count=len(skipped))
            steps.append(dict(kind='checkpoint',title='Checkpoint externo',body=json.dumps(report,ensure_ascii=False)[:8000],ok=True,checkpoint_id=key))
        except Exception as exc:steps.append(dict(kind='error',title='Snapshot incompleto',body=str(exc),ok=False))

    def _handle_tool_inner(self, cfg, tc, generated, steps, agent_ctx, meta_dir, output_dir) -> str:
        name = tc.get("name", "")
        if agent_ctx.get('subagent') and name not in (BUILD_CHILD_TOOLS if agent_ctx.get('isolated_build') else CHILD_TOOLS):
            return json.dumps({'error':'Ferramenta bloqueada no subagente.'},ensure_ascii=False)
        if agent_ctx.get('readonly') and name not in (CHILD_TOOLS if agent_ctx.get('subagent') else READ_TOOLS):
            message='Ferramenta bloqueada: este agente só pode ler e analisar.'
            steps.append(dict(kind='error',title=name,body=message,ok=False))
            return json.dumps({'error':message},ensure_ascii=False)
        if name in AGENT_TOOLS:
            return self._dispatch_agent_service(name,tc.get('arguments') or {},cfg,agent_ctx,meta_dir,steps)
        if name=='codigo_semantico':return self._semantic_tool(tc.get('arguments') or {},agent_ctx,meta_dir,steps)
        if name=='tarefas_definir':return self._tasks_tool(tc.get('arguments') or {},meta_dir,steps)
        if name=='ferramenta_instalar':return self._tool_install_tool(tc.get('arguments') or {},steps)
        if name in ('indice_actualizar','codigo_contexto','codigo_simbolos','contexto_consultar','contexto_registar'):
            try:
                args=tc.get('arguments') or {};root=agent_ctx.get('_guidance_root') or agent_ctx['base'];index=CodeIndex(meta_dir,root)
                if name=='indice_actualizar':result=index.refresh()
                elif name=='contexto_consultar':result=Continuity(meta_dir).load()
                elif name=='contexto_registar':result=Continuity(meta_dir).update(args.get('tipo',''),args.get('texto',''),args.get('id',''),args.get('estado','open'));self._push_tasks(result['tasks'])
                else:
                    index.refresh();result=index.search(args.get('pesquisa',''),min(30,max(1,int(args.get('limite',8)))),name=='codigo_simbolos')
                steps.append(dict(kind='read' if name!='contexto_registar' else 'memory',title=name,body=json.dumps(result,ensure_ascii=False)[:2000],ok=True))
                return json.dumps(result,ensure_ascii=False)
            except Exception as exc:return json.dumps({'error':str(exc)},ensure_ascii=False)
        if name in ('projeto_verificacoes','projeto_validar','projeto_preparar'):
            try:
                root=agent_ctx.get('_guidance_root') or agent_ctx['base'];args=tc.get('arguments') or {}
                if name=='projeto_verificacoes':result=project_validation.discover(root)
                else:result=self._run_validation(cfg,agent_ctx,meta_dir,args.get('ids'),name=='projeto_preparar',agent_ctx.get('_cancel_event') or self._cancel_chat)
                steps.append(dict(kind='validation',title=name,body=json.dumps(result,ensure_ascii=False)[:12000],ok=result.get('state','passed') in ('passed','no_checks')))
                return json.dumps(result,ensure_ascii=False)
            except Exception as exc:return json.dumps({'error':str(exc)},ensure_ascii=False)
        if name in ('processo_iniciar','processos_listar','processo_resultado','processo_cancelar'):
            try:
                args=tc.get('arguments') or {}
                if not agent_ctx.get('on'):raise ValueError('Modo agente desativado.')
                if name=='processo_iniciar':result=self._start_command(cfg,agent_ctx,meta_dir,args.get('comando',''),args.get('cwd',''),args.get('timeout',3600))
                elif name=='processos_listar':result=dict(jobs=list_commands(meta_dir))
                elif name=='processo_cancelar':result=self._commands.cancel(meta_dir,args.get('id',''))
                else:result=load_command(meta_dir,args.get('id',''))
                steps.append(dict(kind='cmd',title=name,body=json.dumps(result,ensure_ascii=False)[:2000],ok=True))
                return json.dumps(result,ensure_ascii=False)
            except Exception as exc:return json.dumps({'error':str(exc)},ensure_ascii=False)
        if name in ("ferramentas_listar","ferramentas_pesquisar","ferramentas_executar"):
            try:
                args=tc.get("arguments") or {}
                current=config.load_config()
                def approve(server,tool_name,arguments):
                    return self._approve("folder:"+server["id"],server["name"]+" / "+tool_name,json.dumps(arguments,ensure_ascii=False)[:10000],{**agent_ctx,"approval":"each"})
                if name=="ferramentas_listar":
                    result={"tools":[{k:r.get(k) for k in ("id","name","description","enabled","error","scope")} for r in self._folder_tools.status(current)]}
                elif name=="ferramentas_pesquisar":
                    result=self._folder_tools.search(current,args.get("id",""),args.get("pesquisa",""))
                else:result=self._folder_tools.execute(current,args.get("id",""),args.get("operacao",""),args.get("argumentos",{}),approve)
                result=self._capture_mcp_images(result,generated,meta_dir,output_dir)
                text=json.dumps(result,ensure_ascii=False)
                if len(text)>120000:text=json.dumps({"truncated":True,"text":text[:110000]},ensure_ascii=False)
                steps.append({"kind":"mcp","title":name,"body":text[:2000],"ok":not result.get("isError",False)})
                return text
            except Exception as exc:
                steps.append({"kind":"mcp","title":name,"body":str(exc),"ok":False})
                return json.dumps({"error":str(exc)},ensure_ascii=False)
        if name.startswith("mcp_"):
            try:
                def approve(server, tool_name, arguments):
                    return self._approve("mcp:"+server["id"], "MCP / "+server["name"]+" / "+tool_name, json.dumps(arguments,ensure_ascii=False)[:10000], {**agent_ctx,"approval":"each"})
                result=self._mcp.call(name,tc.get("arguments",{}) or {},cfg.get("mcp_servers",[]),approve)
                result=self._capture_mcp_images(result,generated,meta_dir,output_dir)
                text=json.dumps(result,ensure_ascii=False)
                if len(text)>30000:text=json.dumps({"truncated":True,"text":text[:28000]},ensure_ascii=False)
                steps.append({"kind":"mcp","title":name,"body":text[:2000],"ok":not result.get("isError",False)})
                return text
            except Exception as exc:
                steps.append({"kind":"mcp","title":name,"body":str(exc),"ok":False})
                return json.dumps({"error":str(exc)},ensure_ascii=False)
        if name in BROWSER_TOOLS:
            return self._dispatch_browser_tool(name, tc.get("arguments", {}) or {}, steps)
        if name in LOCAL_TOOLS:
            return self._dispatch_local_tool(name, tc.get("arguments", {}) or {}, steps, agent_ctx, meta_dir, output_dir)
        if name in CODING_TOOLS:
            return self._dispatch_coding_tool(name,tc.get('arguments') or {},agent_ctx,steps)
        if name in _AGENT_TOOL_NAMES:
            return self._dispatch_agent_tool(name, tc.get("arguments", {}) or {}, agent_ctx, steps)
        return self._dispatch_media_tool(cfg, tc, generated, meta_dir, output_dir)

    def _capture_mcp_images(self,result,generated,meta_dir,output_dir):
        """Binary stays on disk and in multimodal messages, never tool logs."""
        clean=dict(result);content=[];count=0
        for part in result.get('content',[]):
            if part.get('type')!='image':content.append(part);continue
            try:
                mime=part.get('mimeType');encoded=part.get('data','')
                if count>=4 or not isinstance(encoded,str) or len(encoded)>2800000:raise ValueError('Imagem excede o limite de pré-visualização.')
                data=base64.b64decode(encoded,validate=True)
                valid=(mime=='image/png' and data.startswith(b'\x89PNG\r\n\x1a\n')) or (mime=='image/jpeg' and data.startswith(b'\xff\xd8\xff')) or (mime=='image/webp' and data.startswith(b'RIFF') and data[8:12]==b'WEBP')
                if not valid:raise ValueError('Formato de pré-visualização inválido.')
                ext={'image/png':'png','image/jpeg':'jpg','image/webp':'webp'}[mime]
                entry=storage.save_media([data],{'prompt':'Pré-visualização MCP','provider_name':'MCP'},str(output_dir),meta_dir,ext=ext)[0]
                entry['mcp_preview']=True;generated.append(entry);count+=1
                content.append({'type':'text','text':'Pré-visualização guardada: '+entry['path']})
            except (ValueError,TypeError) as exc:content.append({'type':'text','text':str(exc)})
        clean['content']=content
        return clean

    def _dispatch_browser_tool(self, name, args, steps):
        try:
            if self._window is None or sys.platform != "win32":
                raise RuntimeError("O browser integrado não está disponível nesta sessão.")
            opened = self.open_browser(args.get("url", "") if name == "browser_abrir" else "")
            if not opened.get("ok"):
                raise RuntimeError(opened.get("error"))
            self._window.evaluate_js("window.showBrowserForAgent(); true")
            if name in ("browser_abrir", "browser_ler"):
                result = self._browser.read()
            elif name == "browser_navegar":
                action = {"voltar":"back","avancar":"forward","recarregar":"reload"}.get(args.get("acao"))
                if not action:
                    raise ValueError("Ação de navegação inválida.")
                self._browser.action(action)
                import time
                time.sleep(0.2)
                result = self._browser.read()
            else:
                action = {"browser_clicar":"click","browser_escrever":"fill","browser_tecla":"key","browser_deslocar":"scroll"}[name]
                result = self._browser.interact(action,ref=args.get("ref", ""),text=args.get("texto", ""),key=args.get("tecla", ""),amount=args.get("pixels",600))
            steps.append({"kind":"browser","title":name,"body":result.get("url", "") + "\n" + result.get("title", ""),"ok":True})
            return json.dumps(result,ensure_ascii=False)
        except Exception as exc:
            steps.append({"kind":"browser","title":name,"body":str(exc),"ok":False})
            return json.dumps({"error":str(exc)},ensure_ascii=False)

    def _dispatch_local_tool(self, name, args, steps, agent_ctx, meta_dir, output_dir):
        try:
            context = {**agent_ctx, "base":str(output_dir)}
            if name == "git_consultar":
                result = git_query(args, context)
            elif name.startswith("sqlite_"):
                path = scoped_path(args.get("caminho", ""), context)
                write = name == "sqlite_executar"
                if write and not self._approve("database", "Alterar base SQLite", str(path)+"\n"+args.get("sql", ""), agent_ctx):
                    raise RuntimeError("Escrita SQLite recusada pelo utilizador.")
                result = sqlite_run(path,args.get("sql", ""),args.get("parametros"),write=write,limit=args.get("limite",100),schema=name=="sqlite_schema")
            elif name.startswith("conhecimento_"):
                store = KnowledgeStore(meta_dir)
                embed = signature = None
                try:  # embeddings só quando a pesquisa por significado está ligada e configurada; senão, FTS
                    embed, signature = self._semantic_embedder(config.load_config())
                except Exception:
                    embed = signature = None
                if name == "conhecimento_guardar":
                    vector = None
                    if embed:
                        try: vector = embed([((args.get("titulo") or "")+"\n"+(args.get("texto") or ""))[:2000]])[0]
                        except Exception: vector = None
                    result = store.save(args.get("titulo"),args.get("texto",""),args.get("etiquetas",""),args.get("tipo",""),args.get("ref",""),args.get("id"),vector=vector,signature=signature or "")
                elif name == "conhecimento_procurar":
                    consulta = args.get("consulta","")
                    qv = None
                    if embed and (consulta or "").strip():
                        try: qv = embed([consulta[:2000]])[0]
                        except Exception: qv = None
                    result = store.search(consulta,args.get("limite",20),query_vector=qv,signature=signature or "")
                elif name == "conhecimento_ler": result = store.read(args.get("id"))
                else: result = store.forget(args.get("id"))
            else:
                memory = GraphMemory(meta_dir)
                if name == "memoria_guardar": result = memory.save(args.get("nome"),args.get("tipo","facto"),args.get("observacoes",[]))
                elif name == "memoria_relacionar": result = memory.relate(args.get("origem"),args.get("destino"),args.get("relacao"))
                elif name == "memoria_consultar": result = memory.search(args.get("pesquisa", ""))
                else: result = memory.forget(args.get("nome", ""))
            encoded = json.dumps(result,ensure_ascii=False,default=str)
            if len(encoded)>30000:
                encoded=json.dumps({"truncated":True,"text":encoded[:28000]},ensure_ascii=False)
            steps.append({"kind":"tool","title":name,"body":encoded[:2000],"ok":not (isinstance(result,dict) and result.get("ok") is False)})
            return encoded
        except Exception as exc:
            steps.append({"kind":"tool","title":name,"body":str(exc),"ok":False})
            return json.dumps({"error":str(exc)},ensure_ascii=False)

    def _dispatch_media_tool(self, cfg, tool_call, generated, meta_dir, output_dir) -> str:
        name = tool_call.get("name", "")
        cap = _TOOL_NAME_TO_CAP.get(name)
        if cap is None:
            return f"Ferramenta desconhecida: {name}"
        args = tool_call.get("arguments", {}) or {}
        content = (args.get("prompt") or args.get("texto") or args.get("text") or args.get("input") or "").strip()
        if not content:
            return "Nenhum texto fornecido à ferramenta."
        try:
            entries = self._run_configured(cfg, cap, content, meta_dir, output_dir)
            generated.extend(entries)
            return f"Gerei {len(entries)} {_TYPE_LABEL[cap]}(s) para: {content}"
        except providers.ProviderError as exc:
            return f"Erro ao gerar {_TYPE_LABEL[cap]}: {exc}"
