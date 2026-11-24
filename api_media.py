"""Ponte ``Api``: média — geração direta de imagem/vídeo/áudio, histórico e galeria.

Classe-base de ``api.Api`` (extraída de ``api.py`` sem alterações ao código).
Os métodos sem ``_`` inicial são chamados pela interface através da ponte do
pywebview. Usa atributos criados em ``Api.__init__`` e outros métodos da
instância através de ``self``.
"""

from __future__ import annotations

import base64
import config
import providers
import storage
from api_helpers import _TYPE_LABEL, _local_mode, _err, _fmt_exc, _media_allowed, _now, _ok, _resolve_model


class MediaApi:
    # ------------------------------------------------------------------ #
    # Geração directa (single-shot)
    # ------------------------------------------------------------------ #
    def generate(self, capability: str, prompt: str, params: dict = None) -> dict:
        try:
            prompt = (prompt or "").strip()
            if capability not in ("image", "video", "audio"):
                return _err(f"Capacidade inválida: {capability}")
            if not prompt:
                return _err("Escreve um prompt.")
            cfg = config.load_config()
            if self._ensure_context(cfg):
                config.save_config(cfg)
            meta_dir, output_dir = config.resolve_context(cfg)
            entries = self._run_configured(cfg, capability, prompt, meta_dir, output_dir, params)
            return _ok(items=entries, output_dir=str(output_dir))
        except providers.ProviderError as exc:
            return _err(str(exc))
        except Exception as exc:  # noqa: BLE001
            return _err(_fmt_exc(exc))

    # ------------------------------------------------------------------ #
    # Histórico / galeria (do contexto ativo)
    # ------------------------------------------------------------------ #
    def get_history(self, limit: int = 200) -> dict:
        try:
            cfg = config.load_config()
            if self._ensure_context(cfg):
                config.save_config(cfg)
            meta_dir, _out = config.resolve_context(cfg)
            return _ok(history=storage.load_history(meta_dir, limit=limit))
        except Exception as exc:  # noqa: BLE001
            return _err(_fmt_exc(exc))

    def get_media(self, path: str) -> dict:
        try:
            cfg = config.load_config()
            if not _media_allowed(cfg, path):
                return _err("Ficheiro fora das pastas geridas pela aplicação.")
            b64 = storage.read_media_b64(path)
            if b64 is None:
                return _err("Ficheiro não encontrado no disco.")
            media, mime = storage.media_info(path)
            return _ok(b64=b64, mime=mime, media=media)
        except ValueError as exc:
            return _err(str(exc))
        except Exception as exc:  # noqa: BLE001
            return _err(_fmt_exc(exc))

    def get_image(self, path: str) -> dict:
        return self.get_media(path)

    # ------------------------------------------------------------------ #
    # Internos de geração de média
    # ------------------------------------------------------------------ #
    def _run_configured(self, cfg, capability, content, meta_dir, output_dir, params=None) -> list[dict]:
        provider, model = _resolve_model(cfg, capability)
        if provider is None or model is None:
            if _local_mode(cfg):
                raise providers.ProviderError(
                    f"Em «Provedor local» só se usam os modelos da rig, e ela não tem modelo de {_TYPE_LABEL[capability]}. "
                    "Para gerar, muda para «Online» em Configurações → «Onde correm os modelos»."
                )
            raise providers.ProviderError(
                f"Não há modelo de {_TYPE_LABEL[capability]} escolhido. "
                f"Escolhe um na barra de modelos."
            )
        adapter = providers.get_adapter(provider.get("kind", ""), capability)
        values = dict(model.get("defaults") or {})
        if isinstance(params, dict):
            values.update(params)
        return self._run_media(
            provider, model, adapter, content, values, meta_dir, output_dir
        )

    def _run_media(self, provider, model, adapter, content, params, meta_dir, output_dir) -> list[dict]:
        bytes_list, meta_extra = adapter(provider, model, content, params or {})
        if not bytes_list:
            raise providers.ProviderError("O provedor não devolveu nenhum ficheiro.")
        ext = (meta_extra or {}).get("ext", "png")
        meta = {
            "prompt": content,
            "provider_id": provider.get("id", ""),
            "provider_name": provider.get("name", ""),
            "model_id": model.get("id", ""),
            "model_name": model.get("name", ""),
            "params": {k: v for k, v in (params or {}).items() if not str(k).startswith("_")},
        }
        entries = storage.save_media(bytes_list, meta, str(output_dir), meta_dir, ext=ext)
        result = []
        for data, entry in zip(bytes_list, entries):
            item = dict(entry)
            item["b64"] = base64.b64encode(data).decode("ascii")
            result.append(item)
        return result

    def _assistant_media_turn(self, cfg, capability, content, meta_dir, output_dir) -> dict:
        try:
            entries = self._run_configured(cfg, capability, content, meta_dir, output_dir)
            text = f"Aqui está — {_TYPE_LABEL[capability]} gerado para: {content}"
            media = [{"path": e["path"], "type": e["media"]} for e in entries]
        except providers.ProviderError as exc:
            text = f"⚠️ Não consegui gerar o {_TYPE_LABEL[capability]}: {exc}"
            media = []
        return {"role": "assistant", "text": text, "media": media, "files": [], "steps": [], "created_at": _now()}
