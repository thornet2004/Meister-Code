"""Vetores de texto (embeddings) pela API compatível com OpenAI: ``POST {base}/embeddings``.

Usado pela pesquisa de código por significado. Suporta os provedores cuja API
segue esse formato; Anthropic e Google não entram aqui.
"""
from __future__ import annotations

from . import multi
from .base import ProviderError

SUPPORTED_KINDS = ('openrouter', 'openai', 'ollama', 'lmstudio', 'openai-compatible')
MAX_BATCH = 64


def supported(kind: str) -> bool:
    return kind in SUPPORTED_KINDS


def embed(provider: dict, model_id: str, texts: list[str]) -> list[list[float]]:
    """Devolve um vetor por texto, pela mesma ordem."""
    kind = provider.get('kind', '')
    if not supported(kind):
        raise ProviderError("O provedor '" + str(kind) + "' não tem embeddings neste formato. Usa OpenRouter, OpenAI, Ollama, LM Studio ou uma API compatível.")
    model_id = (model_id or '').strip()
    if not model_id:
        raise ProviderError('Indica o modelo de embeddings.')
    if not texts:
        return []
    if len(texts) > MAX_BATCH:
        raise ProviderError('Demasiados textos num só pedido de embeddings.')
    with multi.request(provider, 'POST', '/embeddings', {'model': model_id, 'input': list(texts)}) as response:
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderError('O provedor devolveu uma resposta de embeddings que não é JSON.') from exc
    rows = payload.get('data') if isinstance(payload, dict) else None
    if not isinstance(rows, list) or len(rows) != len(texts):
        raise ProviderError('O provedor não devolveu um vetor por texto (modelo sem embeddings?).')
    rows = sorted(rows, key=lambda row: row.get('index', 0) if isinstance(row, dict) else 0)
    vectors = []
    for row in rows:
        vector = row.get('embedding') if isinstance(row, dict) else None
        if not isinstance(vector, list) or not vector or not all(isinstance(value, (int, float)) for value in vector):
            raise ProviderError('O provedor devolveu um vetor de embeddings inválido.')
        vectors.append([float(value) for value in vector])
    if len({len(vector) for vector in vectors}) != 1:
        raise ProviderError('O provedor devolveu vetores com tamanhos diferentes.')
    return vectors
