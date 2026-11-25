"""Ponte ``Api``: base de conhecimento por projeto (painel «Conhecimento»).

Classe-base de ``api.Api``. As mesmas notas que o agente grava e consulta pelas ferramentas ``conhecimento_*``
ficam aqui disponíveis à interface: listar/pesquisar (por palavras), ler, guardar/editar e apagar. Vivem em
``<projeto>/.studio/knowledge.sqlite`` (``KnowledgeStore``). Editar uma nota aqui limpa o vetor de significado (ficaria
desatualizado); a pesquisa por palavras continua a funcionar e o agente volta a calcular o vetor quando lhe tocar.
"""
from __future__ import annotations

import config
from api_helpers import _err, _ok
from knowledge_store import KnowledgeStore


class KnowledgeApi:
    def _knowledge_store(self):
        meta, _root = config.resolve_context(config.load_config())
        return KnowledgeStore(meta)

    def get_notes(self, query: str = "", limit: int = 50) -> dict:
        try:
            return _ok(**self._knowledge_store().search(str(query or ""), limit))
        except Exception as exc:  # noqa: BLE001
            return _err(str(exc))

    def read_note(self, note_id) -> dict:
        try:
            return _ok(**self._knowledge_store().read(note_id))
        except Exception as exc:  # noqa: BLE001
            return _err(str(exc))

    def save_note(self, titulo: str, texto: str = "", etiquetas: str = "", tipo: str = "", ref: str = "", note_id=None) -> dict:
        try:
            return _ok(**self._knowledge_store().save(titulo, texto, etiquetas, tipo, ref, note_id))
        except Exception as exc:  # noqa: BLE001
            return _err(str(exc))

    def forget_note(self, note_id) -> dict:
        try:
            return _ok(**self._knowledge_store().forget(note_id))
        except Exception as exc:  # noqa: BLE001
            return _err(str(exc))
