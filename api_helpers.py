"""Funções de apoio da ponte ``Api`` (sem estado).

Extraídas de ``api.py``:
  - respostas ``{"ok": ...}`` e cópias seguras para o frontend (sem chaves);
  - âmbito e caminhos do modo agente;
  - procura de provedor/modelo/projeto e ids únicos;
  - salvaguardas para apagar pastas e abrir o gestor de ficheiros.

``api.py`` reimporta estes nomes, por isso continuam acessíveis como
``api._resolve_model`` etc.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path

import config
import providers

# Tipos de modelo (== capacidades == slots de seleção na config).
MODEL_TYPES = ("chat", "image", "video", "audio")
# Seletores da barra de modelos: um por coisa. «code» é um modelo de conversa escolhido para programar (pedido do user,
# 24/11/2026: «quero distinguir chat com código»); os outros coincidem com o tipo do modelo.
MODEL_SLOTS = ("chat", "code", "image", "video", "audio")
_TYPE_LABEL = {"chat": "chat", "code": "código", "image": "imagem", "video": "vídeo", "audio": "áudio"}


def _slot_type(slot: str) -> str:
    return "chat" if slot == "code" else slot


def _local_mode(cfg: dict) -> bool:
    """«Provedor local» ligado: só contam os modelos da rig (os online nem aparecem na barra)."""
    return any(isinstance(p, dict) and p.get("rig") and p.get("enabled") for p in cfg.get("providers", []))

# Ciclo de ferramentas do chat
# O teto fixo de 25 rondas por pedido saiu a 24/11/2026 (pedido do user): mandam os limites que ele define em
# «Processos / Git» → «Limites por pedido» (execution_limits.py).

# Modo agente
AGENT_CMD_TIMEOUT = 120          # segundos por comando
MAX_CMD_OUTPUT = 12000           # chars de output devolvidos ao modelo
MAX_READ_CHARS = 20000           # chars ao ler um ficheiro
MAX_LIST_ENTRIES = 400           # entradas por listagem
APPROVAL_TIMEOUT = 300           # segundos à espera da aprovação do utilizador



def _slug(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "item"


def _ok(**kwargs) -> dict:
    return {"ok": True, **kwargs}


def _err(message: str) -> dict:
    return {"ok": False, "error": message}


def _sanitize_provider(provider: dict) -> dict:
    """Cópia segura para o frontend: sem a chave, só se existe ou não."""
    models = [
        {
            "id": m.get("id", ""),
            "name": m.get("name", ""),
            "type": m.get("type", "image"),
            "defaults": m.get("defaults", {}),
            "categories": m.get("categories", []),
            "catalog_available": m.get("catalog_available", True),
            **({"voices": m["voices"]} if m.get("type") == "audio" and m.get("voices") else {}),  # para o seletor de voz
        }
        for m in provider.get("models", [])
    ]
    return {
        "id": provider.get("id", ""),
        "name": provider.get("name", ""),
        "kind": provider.get("kind", ""),
        "base_url": provider.get("base_url", ""),
        "has_key": bool((provider.get("api_key") or "").strip()),
        "models": models,
        "catalog_updated_at": provider.get("catalog_updated_at", 0),
        "catalog": provider.get("catalog", []),
        "rig": bool(provider.get("rig")),
    }


def _sanitize_project(pr: dict) -> dict:
    path = pr.get("path", "") or ""
    return {
        "id": pr.get("id", ""),
        "name": pr.get("name", ""),
        "path": path,
        "created_at": pr.get("created_at", ""),
        "exists": bool(path) and Path(path).exists(),
        "migration_error": pr.get("migration_error", ""),
        "pinned": bool(pr.get("pinned", False)),
    }


def _sanitize_conv(c: dict) -> dict:
    return {
        "id": c.get("id", ""),
        "title": c.get("title", "") or "Conversa",
        "created_at": c.get("created_at", ""),
        "updated_at": c.get("updated_at", ""),
        "path": str(config.conversations_root() / c.get("id", "")),
        "pinned": bool(c.get("pinned", False)),
    }


# ---------------------------------------------------------------------- #
# Âmbito / caminhos do agente
# ---------------------------------------------------------------------- #
def _resolve_in_scope(path: str, agent_ctx: dict) -> tuple[str | None, str | None]:
    """Resolve um caminho respeitando o âmbito. Devolve (abspath, erro)."""
    base = agent_ctx.get("base")
    raw = (path or "").strip() or "."
    p = Path(raw)
    if not p.is_absolute():
        root = base or os.getcwd()
        p = Path(root) / raw
    ap = str(p.resolve())

    if agent_ctx.get("scope") == "project":
        if not base:
            return None, "Modo agente limitado ao projeto, mas não há projeto ativo."
        baseN = str(Path(base).resolve())
        a, b = os.path.normcase(ap), os.path.normcase(baseN)
        if a == b or a.startswith(b + os.sep):
            return ap, None
        return None, f"Fora da pasta do projeto (não permitido): {path}"
    return ap, None


def _agent_cwd(agent_ctx: dict, requested: str) -> str | None:
    base = agent_ctx.get("base")
    requested = (requested or "").strip()
    if requested:
        target, err = _resolve_in_scope(requested, {**agent_ctx,"scope":"computer"})
        if not err and target and Path(target).is_dir():
            return target
    return base or str(Path.home())


def _rel(path: str, agent_ctx: dict) -> str:
    base = agent_ctx.get("base")
    if base:
        try:
            rel = os.path.relpath(path, base)
            if not rel.startswith(".."):
                return rel
        except (ValueError, OSError):
            pass
    return path


# ---------------------------------------------------------------------- #
# Auxiliares de módulo
# ---------------------------------------------------------------------- #
def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _error_turn(message: str) -> dict:
    # «notice»: é um aviso da app para o utilizador, não uma resposta do modelo — não entra no histórico que o modelo lê
    return {"role": "assistant", "text": f"⚠️ {message}", "media": [], "files": [], "steps": [], "created_at": _now(), "notice": True}


def _conv_title_from_text(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    if not t:
        return "Conversa"
    return t[:40] + ("…" if len(t) > 40 else "")


def _find_provider(cfg: dict, provider_id: str):
    for p in cfg.get("providers", []):
        if p.get("id") == provider_id:
            return p
    return None


def _find_model(provider: dict, model_id: str, model_type: str = ''):
    for m in provider.get("models", []):
        if m.get("id") == model_id and (not model_type or m.get('type') == model_type):
            return m
    return None


def _find_project(cfg: dict, project_id: str):
    for p in cfg.get("projects", []):
        if p.get("id") == project_id:
            return p
    return None


def _resolve_model(cfg: dict, slot: str):
    sel = cfg.get(slot) or {}
    provider = _find_provider(cfg, sel.get("provider_id"))
    if provider is None:
        return None, None
    if _local_mode(cfg) and not provider.get("rig"):  # em modo local os modelos online não se usam
        return None, None
    model = _find_model(provider, sel.get("model_id"), _slot_type(slot))
    if model is None:
        return None, None
    return provider, model


def _resolve_agent_model(cfg,profile):
    selections=cfg.get('preferences',{}).get('agent_models') or {}
    selection=selections.get(profile) or {}
    if not selection:return _resolve_model(cfg,'chat')
    provider=_find_provider(cfg,selection.get('provider_id',''))
    model=_find_model(provider,selection.get('model_id',''),'chat') if provider else None
    if not model or model.get('type')!='chat':raise providers.ProviderError('O modelo configurado para o perfil '+str(profile)+' já não está disponível. Revê Tarefas / Skills → Modelos por perfil.')
    return provider,model


def _unique_id(base: str, cfg: dict) -> str:
    existing = {p.get("id") for p in cfg.get("providers", [])}
    return _dedupe(base, existing)


def _unique_project_id(base: str, cfg: dict) -> str:
    existing = {p.get("id") for p in cfg.get("projects", [])}
    return _dedupe(base, existing)


def _dedupe(base: str, existing: set) -> str:
    if base not in existing:
        return base
    i = 2
    while f"{base}-{i}" in existing:
        i += 1
    return f"{base}-{i}"


def _same_path(a: str, b: str) -> bool:
    try:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))
    except (OSError, ValueError):
        return False


def _is_safe_to_delete(path: str) -> tuple[bool, str]:
    """Salvaguardas antes de apagar uma pasta do disco."""
    try:
        p = Path(path).resolve()
    except (OSError, ValueError) as exc:
        return False, f"caminho inválido ({exc})."
    if not p.exists():
        return True, ""
    if len(p.parts) <= 1:
        return False, "é a raiz da unidade."
    home = Path.home().resolve()
    if p == home:
        return False, "é a tua pasta pessoal."
    try:
        if home.is_relative_to(p):
            return False, "contém a tua pasta pessoal."
    except AttributeError:  # Python < 3.9
        if str(home).startswith(str(p) + os.sep):
            return False, "contém a tua pasta pessoal."
    return True, ""


def _dispose_folder(path: str) -> str:
    """Envia a pasta para a Reciclagem; uma falha nunca causa remoção definitiva."""
    target = str(Path(path))
    try:
        import send2trash  # opcional

        send2trash.send2trash(target)
        return "trash"
    except Exception as exc:
        raise RuntimeError(f"Não foi possível enviar a pasta para a Reciclagem. Os ficheiros foram mantidos: {exc}") from exc


def _open_in_file_manager(path: Path) -> None:
    if sys.platform.startswith("win"):
        os.startfile(str(path))  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)
    else:
        subprocess.run(["xdg-open", str(path)], check=False)


def _media_allowed(cfg: dict, path: str) -> bool:
    """Só permite ler média dentro das pastas geridas pela app."""
    if not isinstance(path, str) or not path.strip():
        return False
    try:
        target = Path(path).expanduser().resolve()
    except (OSError, ValueError):
        return False
    roots = [config.projects_root(), config.conversations_root()]
    try:
        meta_dir, output_dir = config.resolve_context(cfg)
        roots += [Path(meta_dir), Path(output_dir)]
    except Exception:  # noqa: BLE001
        pass
    configured = (cfg.get("output_dir") or "").strip()
    if configured:
        roots.append(Path(configured))
    for root in roots:
        try:
            base = Path(root).expanduser().resolve()
        except (OSError, ValueError):
            continue
        if target == base or target.is_relative_to(base):
            return True
    return False


def _fmt_exc(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}"
