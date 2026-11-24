"""Registo de adaptadores de provedores por `kind` (família).

Cada família de provedor pode oferecer duas capacidades:
  - "image": gerar(provider, model, prompt, params) -> (bytes PNG[], meta)
  - "chat":  chat(provider, model, messages, tools, params) -> dict normalizado

Assim um único provedor (ex.: OpenRouter) serve modelos de chat e de imagem
com a mesma chave. Cada *modelo* tem um campo `type` ("chat" ou "image") que
diz para que serve.

Acrescentar um provedor do mesmo tipo é só config (pela UI). Uma família nova
é um módulo com `gerar`/`chat` registado aqui — o resto da app não muda.
"""

from __future__ import annotations

from typing import Callable

from . import openrouter
from . import multi
from . import media_tasks
from .base import ProviderError

__all__ = [
    "ProviderError",
    "get_adapter",
    "get_image_adapter",
    "get_chat_adapter",
    "available_kinds",
    "family_caps",
    "CAP_FUNCS",
]

# capacidade -> nome da função no módulo da família
CAP_FUNCS = {
    "image": "image",
    "chat": "chat",
    "video": "video",
    "audio": "audio",
}

# família -> capacidades
_FAMILIES: dict[str, dict] = {
    "openrouter": {
        "label": "OpenRouter",
        "image": openrouter.gerar,
        "chat": openrouter.chat,
        "video": openrouter.gerar_video,
        "audio": openrouter.gerar_audio,
    },
    'openai':{'label':'OpenAI','chat':multi.openai},
    'anthropic':{'label':'Anthropic','chat':multi.anthropic},
    'google':{'label':'Google Gemini','chat':multi.google},
    'ollama':{'label':'Ollama','chat':multi.compatible},
    'lmstudio':{'label':'LM Studio','chat':multi.compatible},
    'together':{'label':'Together AI','chat':multi.compatible},
    'fireworks':{'label':'Fireworks AI','chat':multi.compatible},
    'deepinfra':{'label':'DeepInfra','chat':multi.compatible},
    'cometapi':{'label':'CometAPI','chat':multi.compatible},
    'apimart':{'label':'APIMart','chat':multi.compatible},
    'openai-compatible':{'label':'OpenAI compatível','chat':multi.compatible},
    # imagem e vídeo por tarefa (sem conversa)
    **media_tasks.FAMILIES,
}

# kinds antigos/alternativos -> família
_ALIASES: dict[str, str] = {
    "openrouter-image": "openrouter",
    "openrouter-chat": "openrouter",
}


def _family(kind: str) -> dict:
    key = _ALIASES.get(kind, kind)
    fam = _FAMILIES.get(key)
    if fam is None:
        disponiveis = ", ".join(sorted(_FAMILIES)) or "(nenhum)"
        raise ProviderError(
            f"Tipo de provedor desconhecido: '{kind}'. "
            f"Disponíveis: {disponiveis}."
        )
    return fam


_CAP_LABEL = {
    "image": "gera imagens",
    "chat": "suporta chat de texto",
    "video": "gera vídeo",
    "audio": "gera áudio",
}


def get_adapter(kind: str, capability: str) -> Callable:
    """Devolve a função de uma capacidade ('image'|'chat'|'video'|'audio')."""
    fn = _family(kind).get(capability)
    if fn is None:
        raise ProviderError(f"O provedor '{kind}' não {_CAP_LABEL.get(capability, capability)}.")
    return fn


def get_image_adapter(kind: str) -> Callable:
    return get_adapter(kind, "image")


def get_chat_adapter(kind: str) -> Callable:
    adapter=get_adapter(kind, "chat")
    def safe(provider,*args,**kwargs):
        try:return adapter(provider,*args,**kwargs)
        except Exception as exc:
            secret=provider.get('api_key','');message=str(exc)
            if secret:message=message.replace(secret,'[credencial oculta]')
            raise ProviderError(message) from None
    return safe


def available_kinds() -> list[str]:
    return sorted(_FAMILIES)


def family_caps(kind: str) -> dict:
    """Diz que capacidades a família suporta (chat/image/video/audio)."""
    fam = _family(kind)
    return {cap: cap in fam for cap in CAP_FUNCS}

def provider_presets():return {**multi.PRESETS,**media_tasks.PRESETS}

def list_models(provider):return media_tasks.models(provider) if provider.get('kind') in media_tasks.KINDS else multi.models(provider)

def interruption(result):
    """Known terminal conditions must not become successful task completions."""
    reason=str(result.get('finish_reason') or '').lower()
    if reason in ('length','max_tokens','max_output_tokens','incomplete','pause_turn'):
        return dict(state='limited',reason=reason,message='O provedor interrompeu a resposta ('+reason+'). O trabalho ficou guardado e pode ser retomado.')
    if reason in ('content_filter','safety','recitation','blocklist','prohibited_content','refusal','error','malformed_function_call','unexpected_tool_call'):
        return dict(state='error',reason=reason,message='O provedor terminou a resposta ('+reason+'). O trabalho não foi marcado como concluído.')
    return None
