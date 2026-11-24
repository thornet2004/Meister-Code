"""Tipos partilhados pelos adaptadores de provedores."""

from __future__ import annotations


class ProviderError(Exception):
    """Erro legível para mostrar na UI (código HTTP + corpo, etc.)."""
