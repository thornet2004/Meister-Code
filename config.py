"""Leitura/gravação da config e definição de caminhos por sistema operativo.

A config GLOBAL vive numa pasta própria do utilizador:
  - Windows: %APPDATA%\\gerador-imagens\\
  - Linux/Mac: ~/.config/gerador-imagens/

Guarda (global, partilhado por todos os projetos):
  - config.json -> provedores, modelos, seleção de modelos por tipo,
                   preferências, lista de projetos e projeto ativo.

Cada PROJETO fica numa subpasta de Projectos, junto à aplicação. Dentro dela, numa
subpasta `.studio/`, ficam a conversa e o histórico desse projeto:
  - <projeto>/.studio/conversation.json
  - <projeto>/.studio/history.json
  - <projeto>/.studio/attachments/
  - <projeto>/...                         (os ficheiros gerados ficam na raiz)

Cada conversa solta fica em Conversas/<id>/, incluindo mensagens, anexos e média.

A chave de API fica em texto no config.json (avisado na UI). Nunca é
devolvida ao frontend por métodos que possam escrevê-la em logs ou no HTML.
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import shutil
import uuid
from pathlib import Path
from coding_tools import atomic,read_json

APP_DIR_NAME = "gerador-imagens"
STUDIO_DIR_NAME = ".studio"
MCP_PROFILES = ("all", "coding", "research", "work")

# Lock para evitar escritas concorrentes no mesmo ficheiro.
_LOCK = threading.RLock()
# Cache do último conteúdo gravado por ficheiro de metadados, para não reescrever
# conversation-info.json/project-info.json quando nada mudou.
_ITEM_META_CACHE = {}


def portable_root() -> Path | None:
    folder=Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent
    if (folder/'meistercode-portable.json').is_file():return folder
    source=folder.parent if folder.name=='Codigo' else folder.parent.parent if folder.name=='dist' and folder.parent.name=='Codigo' else None
    return source if source is not None and (source/'meistercode-portable.json').is_file() else None


def config_dir() -> Path:
    """Pasta de config/dados do utilizador, criada se não existir."""
    portable=portable_root()
    if portable is not None:
        path=portable/'Configuracao';path.mkdir(parents=True,exist_ok=True);return path
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        path = Path(base) / APP_DIR_NAME
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
        path = Path(base) / APP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return config_dir() / "config.json"


def application_root() -> Path:
    """Dados portáteis junto ao código, ou junto ao executável distribuído."""
    portable=portable_root()
    if portable is not None:return portable
    if getattr(sys, "frozen", False):
        folder = Path(sys.executable).resolve().parent
        if (folder/'studio-install.json').is_file():
            # Installed binaries may be replaced/uninstalled; user data must survive.
            try:
                saved=read_json(config_path());previous=Path(saved.get('storage_root',''))
                if saved.get('storage_layout')==2 and previous.is_absolute() and previous.is_dir() and previous.resolve()!=folder:return previous.resolve()
            except (OSError,ValueError,TypeError):pass
            return Path(os.environ.get('LOCALAPPDATA') or config_dir().parent)/'Meister IA IDE'
        if folder.name.lower() == "dist" and (folder.parent / "app.py").exists():
            return folder.parent
        return folder
    return Path(__file__).resolve().parent


def projects_root() -> Path:
    path = application_root() / "Projectos"
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------------- #
# Caminhos por contexto (projeto ativo ou pasta de config)
# ---------------------------------------------------------------------- #
def project_studio_dir(project_path: str) -> Path:
    """Subpasta `.studio` de um projeto (criada se não existir)."""
    path = Path(project_path) / STUDIO_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def conversations_root() -> Path:
    """Pasta na raiz da app onde ficam as conversas soltas (sem projeto)."""
    path = application_root() / "Conversas"
    path.mkdir(parents=True, exist_ok=True)
    return path


def conversation_dir(conv_id: str) -> Path:
    """Pasta de uma conversa solta (uma por conversa)."""
    safe = re.sub(r"[^A-Za-z0-9_-]+", "", conv_id or "") or "default"
    path = conversations_root() / safe
    path.mkdir(parents=True, exist_ok=True)
    return path


def active_conversation(cfg: dict) -> dict | None:
    """Metadados da conversa solta ativa, ou None."""
    cid = (cfg.get("active_conversation_id") or "").strip()
    if not cid:
        return None
    for c in cfg.get("conversations", []):
        if c.get("id") == cid:
            return c
    return None


def conversation_path(meta_dir) -> Path:
    """Conversa de chat ativa (persistida entre arranques) do contexto."""
    return Path(meta_dir) / "conversation.json"


def history_path(meta_dir) -> Path:
    """Índice dos ficheiros gerados do contexto."""
    return Path(meta_dir) / "history.json"


def attachments_dir(meta_dir) -> Path:
    """Pasta onde se guardam os ficheiros anexados no chat (do contexto)."""
    path = Path(meta_dir) / "attachments"
    path.mkdir(parents=True, exist_ok=True)
    return path


def active_project(cfg: dict) -> dict | None:
    """Devolve o dict do projeto ativo, ou None se não houver/não existir."""
    pid = (cfg.get("active_project_id") or "").strip()
    if not pid:
        return None
    for pr in cfg.get("projects", []):
        if pr.get("id") == pid:
            return pr
    return None


def resolve_context(cfg: dict) -> tuple[Path, Path]:
    """Devolve (meta_dir, output_dir) conforme o projeto ativo.

    - Com projeto ativo e pasta existente: ( <projeto>/.studio , <projeto> ).
    - Sem projeto (ou pasta em falta): ( config_dir() , output_dir/padrão ).
    """
    pr = active_project(cfg)
    if pr and (pr.get("path") or "").strip():
        base = Path(pr["path"])
        if base.exists():
            return project_studio_dir(pr["path"]), base
    # Conversa solta ativa: a sua pasta é meta_dir E pasta de saída.
    conv_id = (cfg.get("active_conversation_id") or "").strip()
    if conv_id:
        base = conversation_dir(conv_id)
        return base, base
    # Rede de segurança (nada ativo): bucket por omissão.
    base = conversation_dir("default")
    return base, base


def _desktop_dir() -> Path:
    """Tenta localizar o Ambiente de Trabalho; cai para a home se não existir."""
    candidates = [Path.home() / "Desktop", Path.home() / "Ambiente de Trabalho"]
    for c in candidates:
        if c.exists():
            return c
    return Path.home()


def default_output_dir() -> str:
    return str(_desktop_dir() / "imagens-geradas")


def default_config() -> dict:
    return {
        "providers": [],
        "mcp_servers": [],
        "mcp_preset_settings": {},
        "folder_tools": {},
        # Projetos (workspaces). Cada um: {id, name, path, created_at}
        "projects": [],
        "active_project_id": "",
        # Conversas soltas (sem projeto). Cada uma: {id, title, created_at, updated_at}
        "conversations": [],
        "active_conversation_id": "",
        # Pasta de saída usada quando NÃO há projeto ativo.
        "output_dir": default_output_dir(),
        # Seleção atual de modelos por tipo: {"provider_id": ..., "model_id": ...}
        "chat": {},
        "image": {},
        "video": {},
        "audio": {},
        "preferences": {
            # Se True, a app tenta usar o cofre do SO (keyring) para a chave.
            "use_keyring": False,
            # Aparência
            "theme": "system",
            "density": "comfortable",
            "auto_compact": False,
            "agent_profile": "build",
            "agent_models": {},
            # Filtro de apresentação das integrações MCP (não altera servidores).
            "mcp_profile": "all",
            # Modo agente: ler/escrever ficheiros e correr comandos.
            # Vem ligado numa instalação nova (decisão do user, 21/11/2026: gravar
            # ficheiros é vital); a escrita e os comandos pedem confirmação.
            "agent": {
                "enabled": True,
                # "project" = só na pasta do projeto ativo; "computer" = todo o PC
                "scope": "computer",
                # "each" = confirmar cada ação; "writes" = confirmar só
                # escrita/comandos (uma vez por categoria); "auto" = sem confirmar
                "approval": "writes",
                # Comandos com padrões perigosos (command_safety) pedem sempre
                # confirmação, mesmo em "auto" ou depois de "permitir na sessão".
                "confirm_dangerous": True,
            },
        },
    }


_AGENT_SCOPES = ("project", "computer")
_AGENT_APPROVALS = ("each", "writes", "auto")


def normalize_agent(prefs: dict) -> dict:
    """Garante que preferences['agent'] existe e é válido."""
    base = default_config()["preferences"]["agent"]
    ag = prefs.get("agent")
    if not isinstance(ag, dict):
        ag = {}
    out = {
        "enabled": bool(ag.get("enabled", base["enabled"])),
        "scope": ag.get("scope") if ag.get("scope") in _AGENT_SCOPES else base["scope"],
        "approval": ag.get("approval") if ag.get("approval") in _AGENT_APPROVALS else base["approval"],
        "confirm_dangerous": bool(ag.get("confirm_dangerous", base["confirm_dangerous"])),
    }
    prefs["agent"] = out
    return out


def load_config() -> dict:
    """Lê o config.json, preenchendo chaves em falta com os defaults."""
    with _LOCK:
        path = config_path()
        if not path.exists():
            cfg = default_config()
            _migrate_storage(cfg)
            _write_json(path, cfg)
            return cfg
        try:
            cfg = read_json(path)
        except json.JSONDecodeError:
            # Config corrompida: não apaga, faz backup e recomeça.
            try:
                path.rename(path.with_suffix(".json.bak"))
            except OSError:
                pass
            cfg = default_config()
            _write_json(path, cfg)
            return cfg

        # Preenche defaults em falta sem destruir o que já existe.
        base = default_config()
        for key, value in base.items():
            cfg.setdefault(key, value)
        if not isinstance(cfg.get("providers"), list):
            cfg["providers"] = []
        else:
            cfg["providers"] = [p for p in cfg["providers"] if isinstance(p, dict)]
        if not isinstance(cfg.get("projects"), list):
            cfg["projects"] = []
        else:
            cfg["projects"] = [p for p in cfg["projects"] if isinstance(p, dict)]
        if not isinstance(cfg.get("active_project_id"), str):
            cfg["active_project_id"] = ""
        if not isinstance(cfg.get("conversations"), list):
            cfg["conversations"] = []
        else:
            cfg["conversations"] = [c for c in cfg["conversations"] if isinstance(c, dict)]
        if not isinstance(cfg.get("active_conversation_id"), str):
            cfg["active_conversation_id"] = ""
        if not isinstance(cfg.get("mcp_servers"), list):
            cfg["mcp_servers"] = []
        else:
            cfg["mcp_servers"] = [s for s in cfg["mcp_servers"] if isinstance(s, dict)]
        if not isinstance(cfg.get("mcp_preset_settings"), dict):
            cfg["mcp_preset_settings"] = {}
        if not isinstance(cfg.get("folder_tools"), dict):
            cfg["folder_tools"] = {}
        if not isinstance(cfg.get("preferences"), dict):
            cfg["preferences"] = base["preferences"]
        else:
            for key, value in base["preferences"].items():
                cfg["preferences"].setdefault(key, value)
        if cfg["preferences"].get("mcp_profile") not in MCP_PROFILES:
            cfg["preferences"]["mcp_profile"] = "all"
        if cfg["preferences"].get("theme") not in ("system", "dark", "light"):
            cfg["preferences"]["theme"] = "system"
        if cfg["preferences"].get("density") not in ("comfortable", "compact"):
            cfg["preferences"]["density"] = "comfortable"
        cfg["preferences"]["auto_compact"] = bool(cfg["preferences"].get("auto_compact", False))
        # Limites por pedido guardados com o valor antigo por omissão (200 mil tokens) passam para o novo (4 milhões):
        # pedido do user, 24/11/2026 — não quer ter de o mudar à mão em cada instalação.
        saved_limits = cfg["preferences"].get("execution_limits")
        if isinstance(saved_limits, dict) and saved_limits.get("tokens") == 200000:
            saved_limits["tokens"] = 4000000
        normalize_agent(cfg["preferences"])
        if _migrate_storage(cfg):
            _write_json(path, cfg)
        return cfg


def save_config(cfg: dict) -> None:
    with _LOCK:
        _write_json(config_path(), cfg)
        _save_item_metadata(cfg)


def _save_item_metadata(cfg):
    current = set()
    for item in cfg.get("conversations", []):
        if not isinstance(item, dict) or not item.get("id"):
            continue
        path = conversation_dir(item["id"]) / "conversation-info.json"
        _write_item_metadata(path, item)
        current.add(str(path))
    for item in cfg.get("projects", []):
        if not isinstance(item, dict) or not item.get("path"):
            continue
        folder = Path(item["path"])
        if folder.is_dir():
            path = project_studio_dir(str(folder)) / "project-info.json"
            _write_item_metadata(path, item)
            current.add(str(path))
    for key in list(_ITEM_META_CACHE):
        if key not in current:
            _ITEM_META_CACHE.pop(key, None)


def _write_item_metadata(path: Path, item: dict) -> None:
    payload = json.dumps(item, ensure_ascii=False, sort_keys=True)
    key = str(path)
    if _ITEM_META_CACHE.get(key) == payload and path.exists():
        return
    _write_json(path, item)
    _ITEM_META_CACHE[key] = payload


def _rebase(value, source, target):
    if isinstance(value, dict):
        return {k: _rebase(v, source, target) for k, v in value.items()}
    if isinstance(value, list):
        return [_rebase(v, source, target) for v in value]
    if isinstance(value, str):
        normalized = value.replace("\\", "/")
        prefix = str(source).replace("\\", "/").rstrip("/")
        if normalized.lower() == prefix.lower():
            return str(target)
        if normalized.lower().startswith(prefix.lower() + "/"):
            return str(target / Path(normalized[len(prefix) + 1:]))
    return value


def _copy_context(source, target, project=False):
    """Copia para staging e só publica a pasta depois de ajustar os índices."""
    if not source.is_dir():
        raise FileNotFoundError(f"Pasta original não encontrada: {source}")
    if source.resolve() == target.resolve():
        return
    if source.resolve() in target.resolve().parents:
        raise ValueError(f"A pasta original contém o destino da transferência: {source}")
    staging = target.with_name(".transfer-" + uuid.uuid4().hex)
    shutil.copytree(source, staging, symlinks=True)
    metadata = list((staging / STUDIO_DIR_NAME).rglob("*.json")) if project else [staging / "conversation.json", staging / "history.json"]
    metadata += [p for p in staging.glob("*.json") if p.stem.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".mp4", ".webm", ".mp3", ".wav", ".ogg"))]
    for path in metadata:
        if path.is_file() and not path.is_symlink():
            data = json.loads(path.read_text(encoding="utf-8"))
            _write_json(path, _rebase(data, source, target))
    staging.rename(target)


def _migrate_storage(cfg):
    root = application_root().resolve()
    if cfg.get("storage_layout") == 2 and cfg.get("storage_root") == str(root):
        return False
    # Os originais e um backup do índice ficam intactos.
    backup = config_path().with_name("config.before-managed-storage.json")
    if config_path().exists() and not backup.exists():
        _write_json(backup, cfg)
    old_conversations = config_dir() / "conversations"
    for item in cfg.get("conversations", []):
        cid = str(item.get("id", "")).strip()
        if not cid:
            item["migration_error"] = "Conversa sem identificador."
            continue
        target = conversations_root() / re.sub(r"[^A-Za-z0-9_-]", "_", cid)
        source = old_conversations / cid
        if cfg.get('storage_layout')==2 and cfg.get('storage_root'):
            managed=Path(cfg['storage_root'])/'Conversas'/re.sub(r'[^A-Za-z0-9_-]','',cid)
            if managed.is_dir():source=managed
        if not target.exists():
            if source.is_dir():
                try:
                    _copy_context(source, target)
                except (OSError, ValueError) as exc:
                    item["migration_error"] = "Não foi possível migrar: " + str(exc)[:300]
            else:
                target.mkdir(parents=True, exist_ok=True)
    for item in cfg.get("projects", []):
        raw = str(item.get("path", "")).strip()
        if not raw:
            item["migration_error"] = "Projeto sem pasta."
            continue
        source = Path(raw)
        try:
            already_managed = source.parent.resolve() == projects_root().resolve()
        except OSError:
            already_managed = False
        if already_managed:
            continue
        if not source.is_dir():
            # Um projeto cuja pasta foi apagada não deve impedir o arranque.
            item["migration_error"] = "A pasta original já não existe."
            continue
        target = projects_root() / (re.sub(r"[^A-Za-z0-9_-]", "_", str(item.get("id", ""))) or uuid.uuid4().hex)
        if target.exists():
            target = target.with_name(target.name + "-" + uuid.uuid4().hex[:8])
        try:
            _copy_context(source, target, project=True)
        except (OSError, ValueError) as exc:
            item["migration_error"] = "Não foi possível migrar: " + str(exc)[:300]
            continue
        item.pop("migration_error", None)
        item["previous_path"] = str(source)
        item["path"] = str(target)
    cfg["storage_layout"] = 2
    cfg["storage_root"] = str(root)
    _save_item_metadata(cfg)
    return True


def _write_json(path: Path, data: dict) -> None:
    """Escrita atómica: grava para ficheiro temporário e substitui."""
    atomic(path,json.dumps(data,ensure_ascii=False,indent=2).encode('utf-8'))
