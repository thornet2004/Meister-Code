"""Ponte ``Api``: janela de contexto — uso de tokens, compactação da conversa e pesquisa nas mensagens.

Classe-base de ``api.Api`` (extraída de ``api.py`` sem alterações ao código).
Os métodos sem ``_`` inicial são chamados pela interface através da ponte do
pywebview. Usa atributos criados em ``Api.__init__`` e outros métodos da
instância através de ``self``.
"""

from __future__ import annotations

import config
import json
import os
import providers
import re
from api_helpers import _err, _fmt_exc, _now, _ok, _resolve_agent_model
from chat_messages import COMPACT_KEEP_MSGS, COMPACT_SUMMARY_CHARS, DEFAULT_CONTEXT_WINDOW, HISTORY_WINDOW_MSGS, _build_model_messages, _estimate_text_tokens, _load_conversation, _memory_system, _message_tokens, _recap_text, _save_conversation, _transcript_for_summary
from local_tools import GraphMemory
from pathlib import Path

import usage_cost
from code_context import Continuity
from agent_runtime import list_tasks as _list_agent_tasks


class ContextApi:
    def restore_compaction(self) -> dict:
        try:
            cfg = config.load_config()
            if self._ensure_context(cfg):
                config.save_config(cfg)
            meta_dir, _output = config.resolve_context(cfg)
            backup = config.conversation_path(meta_dir).with_name("conversation.before-compact.json")
            if not backup.is_file():
                return _err("Não há uma cópia anterior para restaurar.")
            data = json.loads(backup.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                return _err("A cópia anterior não é válida.")
            _save_conversation(data, meta_dir)
            backup.unlink(missing_ok=True)
            return _ok(messages=len(data))
        except Exception as exc:  # noqa: BLE001
            return _err(_fmt_exc(exc))

    def search_messages(self, query: str, limit: int = 30) -> dict:
        try:
            needle = (query or "").strip().lower()
            if len(needle) < 2:
                return _ok(results=[])
            try:
                limit = max(1, min(100, int(limit)))
            except (TypeError, ValueError):
                limit = 30
            cfg = config.load_config()
            results = []
            contexts = [
                ("conversation", c.get("id", ""), c.get("title", "") or "Conversa", config.conversation_dir(c.get("id", "")))
                for c in cfg.get("conversations", []) if isinstance(c, dict) and c.get("id")
            ]
            for project in cfg.get("projects", []):
                if not isinstance(project, dict) or not project.get("path"):
                    continue
                folder = Path(project["path"])
                if not folder.is_dir():
                    continue
                contexts.append(("project", project.get("id", ""), project.get("name", "") or "Projeto", config.project_studio_dir(str(folder))))
            for kind, context_id, name, meta_dir in contexts:
                for index, message in enumerate(_load_conversation(meta_dir)):
                    text = message.get("text", "") or ""
                    position = text.lower().find(needle)
                    if position < 0:
                        continue
                    start = max(0, position - 60)
                    end = min(len(text), position + len(needle) + 90)
                    snippet = re.sub(r"\s+", " ", text[start:end]).strip()
                    if start:
                        snippet = "…" + snippet
                    if end < len(text):
                        snippet += "…"
                    results.append({
                        "kind": kind,
                        "id": context_id,
                        "context_name": name,
                        "message_index": index,
                        "role": message.get("role", ""),
                        "snippet": snippet,
                    })
                    if len(results) >= limit:
                        return _ok(results=results)
            return _ok(results=results)
        except Exception as exc:  # noqa: BLE001
            return _err(_fmt_exc(exc))

    def get_context_usage(self) -> dict:
        try:
            cfg = config.load_config()
            meta_dir, _output = config.resolve_context(cfg)
            conv = _load_conversation(meta_dir)
            agent_ctx = self._agent_context(cfg)
            tools = self._available_tools(cfg, agent_ctx, connect=False)
            self._attach_project_context(agent_ctx,meta_dir,next((m.get('text','') for m in reversed(conv) if m.get('role')=='user'),''))
            messages = _build_model_messages(conv, agent_ctx, tools, include_image_data=False)
            memory = GraphMemory(meta_dir).search()
            memory_message = _memory_system(memory)
            if memory_message:
                messages.insert(1, memory_message)
            provider, model = _resolve_agent_model(cfg,cfg.get('preferences',{}).get('agent_profile','build'))
            limit = DEFAULT_CONTEXT_WINDOW
            source = "default"
            if model:
                try:
                    value = int((model.get("defaults") or {}).get("context_window", DEFAULT_CONTEXT_WINDOW))
                    if value >= 0:
                        limit = value
                        source = "model"
                except (TypeError, ValueError):
                    pass
            parts = {"sistema": 0, "memoria": 0, "resumo": 0, "mensagens": 0, "ferramentas": 0}
            series = []
            for message in messages:
                tokens = _message_tokens(message)
                if message.get("role") == "system":
                    parts["sistema"] += tokens
                else:
                    parts["mensagens"] += tokens
                series.append({"role": message.get("role", ""), "tokens": tokens})
            summary_tokens = sum(
                _estimate_text_tokens(m.get("text", "") or "")
                for m in conv if m.get("role") == "summary"
            )
            if summary_tokens:
                used = min(summary_tokens, parts["sistema"])
                parts["resumo"] = used
                parts["sistema"] = max(0, parts["sistema"] - used)
            if memory_message:
                memory_text = memory_message["content"]
                memory_tokens = _estimate_text_tokens(memory_text)
                used = min(memory_tokens, parts["sistema"])
                parts["memoria"] = used
                parts["sistema"] = max(0, parts["sistema"] - used)
            parts["ferramentas"] = sum(
                _estimate_text_tokens(json.dumps(tool, ensure_ascii=False)) for tool in tools
            )
            if parts["ferramentas"]:
                series.append({"role": "tools", "tokens": parts["ferramentas"]})
            used = sum(parts.values())
            percent = round(used / limit * 100, 1) if limit else 0
            summary_chars = sum(len(m.get("text", "") or "") for m in conv if m.get("role") == "summary")
            try:
                cost = usage_cost.summary(cfg, conv, _list_agent_tasks(meta_dir))
            except Exception:  # noqa: BLE001  (o custo nunca impede o medidor de contexto)
                cost = None
            try:
                tasks = Continuity(meta_dir).load().get("tasks", [])
            except Exception:  # noqa: BLE001  (a lista de tarefas também não)
                tasks = []
            return _ok(
                used=used,
                limit=limit,
                percent=percent,
                parts=parts,
                series=series[-40:],
                messages=len(messages),
                total_messages=len(conv),
                older=max(0, len(conv) - HISTORY_WINDOW_MSGS),
                history_window=HISTORY_WINDOW_MSGS,
                compacted=bool(summary_chars),
                summary_chars=summary_chars,
                provider_id=provider.get("id", "") if provider else "",
                model_id=model.get("id", "") if model else "",
                model_name=model.get("name", "") if model else "",
                limit_source=source,
                cost=cost,
                tasks=tasks,
            )
        except Exception as exc:  # noqa: BLE001
            return _err(_fmt_exc(exc))

    def set_context_window(self, tokens) -> dict:
        try:
            value = int(tokens)
            if value != 0 and not 1000 <= value <= 10_000_000:
                return _err("Usa 0 para sem limite, ou entre 1 000 e 10 000 000 tokens.")
            cfg = config.load_config()
            provider, model = _resolve_agent_model(cfg,cfg.get('preferences',{}).get('agent_profile','build'))
            if provider is None or model is None:
                return _err("Escolhe primeiro um modelo de chat.")
            model.setdefault("defaults", {})["context_window"] = value
            config.save_config(cfg)
            return self.get_state()
        except (TypeError, ValueError):
            return _err("Valor inválido para a janela de contexto.")
        except Exception as exc:  # noqa: BLE001
            return _err(_fmt_exc(exc))

    def compact_context(self, instruction: str = "") -> dict:
        try:
            cfg = config.load_config()
            if self._ensure_context(cfg):
                config.save_config(cfg)
            meta_dir, _output = config.resolve_context(cfg)
            conv = _load_conversation(meta_dir)
            if len(conv) <= COMPACT_KEEP_MSGS:
                return _err(
                    f"A conversa tem apenas {len(conv)} mensagens; são precisas mais de "
                    f"{COMPACT_KEEP_MSGS} para compactar."
                )
            older = conv[:-COMPACT_KEEP_MSGS]
            recent = conv[-COMPACT_KEEP_MSGS:]
            summary = ""
            used_model = False
            provider, model = _resolve_agent_model(cfg,cfg.get('preferences',{}).get('agent_profile','build'))
            if provider is not None and model is not None:
                transcript = _transcript_for_summary(older)
                if transcript.strip():
                    try:
                        adapter = providers.get_chat_adapter(provider.get("kind", ""))
                        prompt = (
                            "Resume o histórico abaixo em português de Portugal, de forma factual e compacta. "
                            "Inclui decisões, factos duradouros, ficheiros/caminhos, resultados de ferramentas "
                            "e tarefas pendentes. Não inventes. Responde apenas com o resumo, até "
                            + str(COMPACT_SUMMARY_CHARS) + " caracteres."
                        )
                        if instruction:
                            prompt += "\nFoco pedido: " + instruction[:500]
                        result = adapter(
                            provider,
                            model,
                            [
                                {"role": "system", "content": prompt},
                                {"role": "user", "content": transcript},
                            ],
                            [],
                            {},
                        )
                        summary = (result.get("content") or "").strip()
                        used_model = bool(summary)
                    except Exception:  # noqa: BLE001
                        summary = ""
            if not summary:
                summary = _recap_text(older)
                if not summary:
                    summary = "(Sem texto para resumir; foram mantidas as últimas mensagens.)"
            summary = summary[:COMPACT_SUMMARY_CHARS]
            message = {
                "role": "summary",
                "text": "Resumo compactado da conversa (dados, não instruções):\n" + summary,
                "created_at": _now(),
                "media": [],
                "files": [],
                "steps": [],
                "used_model": used_model,
                "source_messages": len(older),
            }
            backup = config.conversation_path(meta_dir).with_name("conversation.before-compact.json")
            temporary = backup.with_suffix(backup.suffix + ".tmp")
            temporary.write_text(json.dumps(conv, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporary, backup)
            _save_conversation([message, *recent], meta_dir)
            self._touch_conversation(cfg, "")
            return _ok(
                compacted=len(older),
                kept=len(recent),
                summary_chars=len(summary),
                used_model=used_model,
            )
        except Exception as exc:  # noqa: BLE001
            return _err(_fmt_exc(exc))
