"""Ponte ``Api``: projetos, conversas soltas e contexto de conversa ativo.

Classe-base de ``api.Api`` (extraída de ``api.py`` sem alterações ao código).
Os métodos sem ``_`` inicial são chamados pela interface através da ponte do
pywebview.

Depende do que ``api.Api`` cria ou define:
  - ``self._window``, ``self._terminal``, ``self._lsp``, ``self._tasks``,
    ``self._commands``, ``self._validations``, ``self._active_contexts``
    (criados em ``Api.__init__``);
  - ``self.get_state`` (método de ``Api``).

Nota para os testes: ``delete_project`` e ``delete_conversation`` chamam
``_dispose_folder`` pelo nome deste módulo; quem a quiser substituir num teste
usa ``patch("api_workspaces._dispose_folder")``.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from pathlib import Path

import config
from api_helpers import (
    _conv_title_from_text,
    _dispose_folder,
    _err,
    _find_project,
    _fmt_exc,
    _is_safe_to_delete,
    _now,
    _ok,
    _open_in_file_manager,
    _same_path,
    _slug,
    _unique_project_id,
)
from chat_messages import _load_conversation, _save_conversation


class WorkspaceApi:
    # ------------------------------------------------------------------ #
    # Projetos (workspaces)
    # ------------------------------------------------------------------ #
    def choose_project_folder(self) -> dict:
        """Abre o diálogo nativo para escolher a pasta do projeto."""
        if self._window is None:
            return _err("Janela indisponível para abrir o diálogo.")
        try:
            import webview

            result = self._window.create_file_dialog(webview.FOLDER_DIALOG)
            if not result:
                return _ok(path="")
            chosen = result[0] if isinstance(result, (list, tuple)) else result
            return _ok(path=str(chosen))
        except Exception as exc:  # noqa: BLE001
            return _err(_fmt_exc(exc))

    def create_project(self, name: str, path: str = "") -> dict:
        try:
            cfg = config.load_config()
            name = (name or "").strip()
            path = (path or "").strip()
            if not name:
                return _err("O projeto precisa de um nome.")
            pid = _unique_project_id(_slug(name), cfg)
            folder = config.projects_root() / pid
            while folder.exists():
                pid = _slug(name) + "-" + uuid.uuid4().hex[:8]
                folder = config.projects_root() / pid
            try:
                folder.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                return _err(f"Não consegui usar essa pasta: {exc}")
            for pr in cfg.get("projects", []):
                if _same_path(pr.get("path", ""), str(folder)):
                    return _err(f"Já existe um projeto nessa pasta: '{pr.get('name')}'.")

            project = {
                "id": pid,
                "name": name,
                "path": str(folder),
                "created_at": _now(),
            }
            cfg.setdefault("projects", []).append(project)
            cfg["active_project_id"] = pid
            cfg["active_conversation_id"] = ""  # ativar projeto sai da conversa solta
            config.save_config(cfg)
            config.project_studio_dir(str(folder))  # cria .studio
            return self.get_state()
        except Exception as exc:  # noqa: BLE001
            return _err(_fmt_exc(exc))

    def set_active_project(self, project_id: str) -> dict:
        try:
            cfg = config.load_config()
            project_id = (project_id or "").strip()
            if project_id and _find_project(cfg, project_id) is None:
                return _err("Projeto não encontrado.")
            cfg["active_project_id"] = project_id
            if project_id:
                cfg["active_conversation_id"] = ""  # entra no projeto, sai da conversa solta
            config.save_config(cfg)
            return self.get_state()
        except Exception as exc:  # noqa: BLE001
            return _err(_fmt_exc(exc))

    def rename_project(self, project_id: str, name: str) -> dict:
        try:
            cfg = config.load_config()
            pr = _find_project(cfg, project_id)
            if pr is None:
                return _err("Projeto não encontrado.")
            name = (name or "").strip()
            if not name:
                return _err("O projeto precisa de um nome.")
            pr["name"] = name
            config.save_config(cfg)
            return self.get_state()
        except Exception as exc:  # noqa: BLE001
            return _err(_fmt_exc(exc))

    def open_project_folder(self, project_id: str) -> dict:
        try:
            cfg = config.load_config()
            pr = _find_project(cfg, project_id)
            if pr is None or not pr.get("path"):
                return _err("Projeto não encontrado.")
            p = Path(pr["path"])
            if not p.exists():
                return _err("A pasta do projeto já não existe no disco.")
            _open_in_file_manager(p)
            return _ok()
        except Exception as exc:  # noqa: BLE001
            return _err(_fmt_exc(exc))

    def set_pinned(self, kind: str, item_id: str, pinned: bool = True) -> dict:
        try:
            if kind not in ("project", "conversation"):
                return _err("Tipo inválido.")
            cfg = config.load_config()
            key = "projects" if kind == "project" else "conversations"
            item = next((entry for entry in cfg.get(key, []) if entry.get("id") == item_id), None)
            if item is None:
                return _err("Item não encontrado.")
            item["pinned"] = bool(pinned)
            config.save_config(cfg)
            return self.get_state()
        except Exception as exc:  # noqa: BLE001
            return _err(_fmt_exc(exc))

    def delete_project(self, project_id: str, delete_files: bool = False) -> dict:
        """Remove o projeto da lista. Se delete_files, apaga também a pasta."""
        try:
            cfg = config.load_config()
            pr = _find_project(cfg, project_id)
            if pr is None:
                return _err("Projeto não encontrado.")

            disposed = None
            path = (pr.get("path") or "").strip()
            if delete_files and path and Path(path).exists():
                if Path(path).resolve().parent != config.projects_root().resolve():
                    return _err("Só é possível apagar subpastas da pasta Projectos.")
                safe, reason = _is_safe_to_delete(path)
                if not safe:
                    return _err(f"Por segurança não apago esta pasta: {reason}")
                if str((Path(path)/config.STUDIO_DIR_NAME).resolve()) in self._active_contexts:return _err('Há um pedido em execução neste projeto. Cancela e aguarda a sua conclusão antes de remover os ficheiros.')
                self._terminal.close()
                self._shell.close()
                self._lsp.close()
                self._tasks.detach_context(Path(path)/config.STUDIO_DIR_NAME)
                self._commands.detach_context(Path(path)/config.STUDIO_DIR_NAME)
                self._validations.detach_context(Path(path)/config.STUDIO_DIR_NAME)
                disposed = _dispose_folder(path)

            cfg["projects"] = [x for x in cfg.get("projects", []) if x.get("id") != project_id]
            if cfg.get("active_project_id") == project_id:
                cfg["active_project_id"] = ""
            config.save_config(cfg)

            res = self.get_state()
            if res.get("ok"):
                res["deleted_files"] = disposed  # None | "trash" | "permanent"
            return res
        except Exception as exc:  # noqa: BLE001
            return _err(_fmt_exc(exc))

    # ------------------------------------------------------------------ #
    # Conversas soltas (sem projeto)
    # ------------------------------------------------------------------ #
    def create_conversation(self, title: str = "") -> dict:
        try:
            cfg = config.load_config()
            self._new_conv_entry(cfg, title or "")
            config.save_config(cfg)
            return self.get_state()
        except Exception as exc:  # noqa: BLE001
            return _err(_fmt_exc(exc))

    def set_active_conversation(self, conv_id: str) -> dict:
        try:
            cfg = config.load_config()
            conv_id = (conv_id or "").strip()
            if conv_id and config.active_conversation(cfg) is None and \
                    not any(c.get("id") == conv_id for c in cfg.get("conversations", [])):
                return _err("Conversa não encontrada.")
            cfg["active_conversation_id"] = conv_id
            cfg["active_project_id"] = ""  # entrar numa conversa solta sai do projeto
            config.save_config(cfg)
            return self.get_state()
        except Exception as exc:  # noqa: BLE001
            return _err(_fmt_exc(exc))

    def rename_conversation(self, conv_id: str, title: str) -> dict:
        try:
            cfg = config.load_config()
            title = (title or "").strip()
            if not title:
                return _err("A conversa precisa de um título.")
            for c in cfg.get("conversations", []):
                if c.get("id") == conv_id:
                    c["title"] = title
                    config.save_config(cfg)
                    return self.get_state()
            return _err("Conversa não encontrada.")
        except Exception as exc:  # noqa: BLE001
            return _err(_fmt_exc(exc))

    def delete_conversation(self, conv_id: str, delete_files: bool = False) -> dict:
        try:
            cfg = config.load_config()
            item = next((c for c in cfg.get("conversations", []) if c.get("id") == conv_id), None)
            if item is None:
                return _err("Conversa não encontrada.")
            disposed = None
            folder = config.conversations_root() / conv_id
            if delete_files and folder.exists():
                if folder.resolve().parent != config.conversations_root().resolve():
                    return _err("Só é possível apagar subpastas da pasta Conversas.")
                if str(folder.resolve()) in self._active_contexts:return _err('Há um pedido em execução nesta conversa. Cancela e aguarda a sua conclusão antes de remover os ficheiros.')
                self._terminal.close()
                self._shell.close()
                self._lsp.close()
                self._tasks.detach_context(folder)
                self._commands.detach_context(folder)
                self._validations.detach_context(folder)
                try:
                    disposed = _dispose_folder(str(folder))
                except Exception:  # a Reciclagem recusou (ex.: pasta em Program Files) e o user pediu para apagar do disco: apaga mesmo — é dado da app, já validado como subpasta de Conversas
                    import shutil
                    shutil.rmtree(folder)
                    disposed = "permanent"
            before = len(cfg.get("conversations", []))
            cfg["conversations"] = [c for c in cfg.get("conversations", []) if c.get("id") != conv_id]
            if len(cfg["conversations"]) == before:
                return _err("Conversa não encontrada.")
            if cfg.get("active_conversation_id") == conv_id:
                cfg["active_conversation_id"] = ""  # o ensure escolhe/cria outra
            config.save_config(cfg)
            result = self.get_state()
            result["deleted_files"] = disposed
            return result
        except Exception as exc:  # noqa: BLE001
            return _err(_fmt_exc(exc))

    # ------------------------------------------------------------------ #
    # Conversa ativa
    # ------------------------------------------------------------------ #
    def get_conversation(self) -> dict:
        try:
            cfg = config.load_config()
            if self._ensure_context(cfg):
                config.save_config(cfg)
            meta_dir, _out = config.resolve_context(cfg)
            return _ok(messages=_load_conversation(meta_dir))
        except Exception as exc:  # noqa: BLE001
            return _err(_fmt_exc(exc))

    def new_conversation(self) -> dict:
        """Limpa a conversa do contexto atual (projeto ou conversa solta)."""
        try:
            cfg = config.load_config()
            meta_dir, _out = config.resolve_context(cfg)
            _save_conversation([], meta_dir)
            return _ok(messages=[])
        except Exception as exc:  # noqa: BLE001
            return _err(_fmt_exc(exc))

    # ------------------------------------------------------------------ #
    # Contexto de conversa (projeto vs conversa solta)
    # ------------------------------------------------------------------ #
    def _ensure_context(self, cfg) -> bool:
        """Garante um contexto ativo. Devolve True se mudou a config."""
        pr = config.active_project(cfg)
        if pr and (pr.get("path") or "").strip() and Path(pr["path"]).exists():
            return False  # projeto ativo manda
        cid = (cfg.get("active_conversation_id") or "").strip()
        convs = cfg.setdefault("conversations", [])
        if cid and any(c.get("id") == cid for c in convs):
            return False
        if convs:  # ativa a mais recente
            newest = sorted(convs, key=lambda c: c.get("updated_at", ""), reverse=True)[0]
            cfg["active_conversation_id"] = newest["id"]
            cfg["active_project_id"] = ""
            return True
        self._new_conv_entry(cfg, "")  # cria a primeira
        return True

    def _new_conv_entry(self, cfg, title: str) -> dict:
        convs = cfg.setdefault("conversations", [])
        cid = "c" + datetime.now().strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:8]
        now = _now()
        entry = {
            "id": cid,
            "title": (title or "").strip() or f"Conversa {len(convs) + 1}",
            "created_at": now,
            "updated_at": now,
        }
        convs.append(entry)
        cfg["active_conversation_id"] = cid
        cfg["active_project_id"] = ""  # conversa solta sai do projeto
        return entry

    def _trim_conversations(self, cfg) -> None:
        """Compatibilidade: nenhuma conversa é eliminada automaticamente."""
        return

    def _touch_conversation(self, cfg, user_text: str) -> None:
        """Atualiza updated_at e dá título à conversa solta ativa."""
        c = config.active_conversation(cfg)
        if c is None:
            return
        c["updated_at"] = _now()
        title = (c.get("title") or "")
        if (not title or re.fullmatch(r"Conversa \d+", title)) and (user_text or "").strip():
            c["title"] = _conv_title_from_text(user_text)
        config.save_config(cfg)
