"""Gravação de média (imagem/vídeo/áudio) em disco e leitura do histórico.

Cada geração produz, para cada ficheiro:
  - <pasta_saida>/<timestamp>-<slug>.<ext>       (o ficheiro)
  - <pasta_saida>/<timestamp>-<slug>.<ext>.json  (sidecar com metadados)

O índice (history.json) é POR CONTEXTO: fica em `meta_dir` (a subpasta
`.studio/` do projeto ativo, ou a pasta de config quando não há projeto).
Cada entrada tem um campo `media` ("image" | "video" | "audio") e `ext`.
"""

from __future__ import annotations

import base64
import json
import re
import threading
from datetime import datetime
from pathlib import Path

import config

_LOCK = threading.RLock()

# Limite de leitura para a ponte JS (evita bloquear a app com ficheiros enormes).
MAX_MEDIA_BYTES = 100 * 1024 * 1024

# extensão -> (media, mime)
_MEDIA_TYPES = {
    "png": ("image", "image/png"),
    "jpg": ("image", "image/jpeg"),
    "jpeg": ("image", "image/jpeg"),
    "webp": ("image", "image/webp"),
    "gif": ("image", "image/gif"),
    "bmp": ("image", "image/bmp"),
    "mp4": ("video", "video/mp4"),
    "webm": ("video", "video/webm"),
    "mov": ("video", "video/quicktime"),
    "mp3": ("audio", "audio/mpeg"),
    "wav": ("audio", "audio/wav"),
    "ogg": ("audio", "audio/ogg"),
    "opus": ("audio", "audio/ogg"),
    "pcm": ("audio", "audio/pcm"),
    "m4a": ("audio", "audio/mp4"),
}


def media_info(path_or_ext: str) -> tuple[str, str]:
    """Devolve (media, mime) a partir de um caminho ou extensão."""
    ext = path_or_ext.rsplit(".", 1)[-1].lower().lstrip(".")
    return _MEDIA_TYPES.get(ext, ("image", "application/octet-stream"))


def _slug(text: str, max_len: int = 40) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:max_len] or "ficheiro"


def save_media(bytes_list, meta: dict, output_dir: str, meta_dir, ext: str = "png") -> list[dict]:
    """Grava uma lista de ficheiros (bytes) + sidecars e atualiza o histórico.

    `output_dir` -> onde ficam os ficheiros gerados.
    `meta_dir`   -> onde fica o history.json desse contexto.
    `meta` deve conter: prompt, provider_id, provider_name, model_id,
    model_name, params. A data/hora e o tipo de média são acrescentados aqui.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    ext = (ext or "png").lstrip(".").lower()
    media, _ = media_info("x." + ext)

    now = datetime.now()
    stamp = now.strftime("%Y%m%d-%H%M%S")
    slug = _slug(meta.get("prompt", ""))

    entries: list[dict] = []
    for index, data in enumerate(bytes_list, start=1):
        suffix = f"-{index}" if len(bytes_list) > 1 else ""
        base_name = f"{stamp}-{slug}{suffix}"
        filename = f"{base_name}.{ext}"
        file_path = out / filename
        counter = 2
        while file_path.exists() or file_path.with_suffix(file_path.suffix + ".json").exists():
            filename = f"{base_name}-{counter}.{ext}"
            file_path = out / filename
            counter += 1
        file_path.write_bytes(data)

        entry = {
            "filename": filename,
            "path": str(file_path),
            "media": media,
            "ext": ext,
            "prompt": meta.get("prompt", ""),
            "provider_id": meta.get("provider_id", ""),
            "provider_name": meta.get("provider_name", ""),
            "model_id": meta.get("model_id", ""),
            "model_name": meta.get("model_name", ""),
            "params": meta.get("params", {}),
            "created_at": now.isoformat(timespec="seconds"),
        }

        sidecar = file_path.with_suffix(file_path.suffix + ".json")
        sidecar.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
        entries.append(entry)

    _append_history(entries, meta_dir)
    return entries


def save_images(image_bytes_list, meta: dict, output_dir: str, meta_dir) -> list[dict]:
    """Atalho de compatibilidade: grava imagens PNG."""
    return save_media(image_bytes_list, meta, output_dir, meta_dir, ext="png")


def _append_history(entries: list[dict], meta_dir) -> None:
    with _LOCK:
        path = config.history_path(meta_dir)
        history = _read_history_raw(meta_dir)
        history = entries + history  # mais recentes primeiro
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)


def _read_history_raw(meta_dir) -> list[dict]:
    path = config.history_path(meta_dir)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def load_history(meta_dir, limit: int = 200) -> list[dict]:
    """Histórico (mais recentes primeiro), só entradas cujo ficheiro existe."""
    with _LOCK:
        history = _read_history_raw(meta_dir)
    alive = []
    for e in history:
        if e.get("path") and Path(e["path"]).exists():
            e.setdefault("media", media_info(e.get("path", ""))[0])
            e.setdefault("ext", (e.get("path", "x.png").rsplit(".", 1)[-1]))
            alive.append(e)
    return alive[:limit]


def read_media_b64(path: str) -> str | None:
    """Lê um ficheiro do disco e devolve-o como base64."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        if p.stat().st_size > MAX_MEDIA_BYTES:
            raise ValueError("O ficheiro é demasiado grande para ser enviado à interface.")
        return base64.b64encode(p.read_bytes()).decode("ascii")
    except OSError:
        return None


# Compatibilidade com o nome antigo.
read_image_b64 = read_media_b64
