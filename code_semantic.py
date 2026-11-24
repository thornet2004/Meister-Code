"""Pesquisa de código por significado: índice local de vetores (embeddings).

Complementa o índice lexical (``code_context.CodeIndex``), que só encontra
palavras iguais. Aqui cada ficheiro é partido em excertos, cada excerto é
convertido num vetor por um modelo de embeddings, e a pesquisa devolve os
excertos cujo vetor está mais próximo do da pergunta.

- A lista de ficheiros e o texto vêm do índice lexical, por isso valem as
  mesmas exclusões e limites (``.env``, credenciais, binários, 1 MiB/ficheiro).
- É incremental: só se recalculam os ficheiros cujo conteúdo mudou.
- Os vetores ficam em ``code-semantic.sqlite`` na pasta de metadados do
  contexto; mudar de modelo apaga-os (vetores de modelos diferentes não se
  comparam).
- Este módulo não fala com a rede: recebe uma função ``embed(textos) -> vetores``.
"""
from __future__ import annotations

import heapq
import json
import math
import sqlite3
import threading
import time
from array import array
from contextlib import closing
from pathlib import Path

from code_context import CodeIndex
from coding_tools import digest, read

_LOCK = threading.RLock()

CHUNK_LINES = 40          # linhas por excerto
CHUNK_OVERLAP = 8         # linhas repetidas entre excertos seguidos
CHUNK_MAX_CHARS = 1800    # texto enviado ao modelo por excerto
MAX_CHUNKS_PER_REFRESH = 1500
BATCH = 32


def chunks(text: str) -> list[tuple[int, int, str]]:
    """Parte um ficheiro em excertos ``(linha inicial, linha final, texto)``."""
    lines = text.splitlines()
    found = []
    start = 0
    while start < len(lines):
        end = min(len(lines), start + CHUNK_LINES)
        body = '\n'.join(lines[start:end]).strip('\n')
        if len(body.strip()) >= 20:
            found.append((start + 1, end, body[:CHUNK_MAX_CHARS]))
        if end >= len(lines):
            break
        start = end - CHUNK_OVERLAP
    return found


def _pack(vector) -> bytes:
    norm = math.sqrt(math.sumprod(vector, vector))
    if not norm:
        raise ValueError('vetor nulo')
    return array('f', [value / norm for value in vector]).tobytes()


def _unpack(blob: bytes) -> array:
    vector = array('f')
    vector.frombytes(blob)
    return vector


class SemanticIndex:
    def __init__(self, meta, root):
        self.meta = Path(meta)
        self.root = Path(root).resolve()
        self.path = self.meta / 'code-semantic.sqlite'

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('CREATE TABLE IF NOT EXISTS chunks(id INTEGER PRIMARY KEY,path TEXT,sha TEXT,start INTEGER,finish INTEGER,text TEXT,vector BLOB)')
        db.execute('CREATE INDEX IF NOT EXISTS chunks_path ON chunks(path)')
        db.execute('CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT)')
        return db

    @staticmethod
    def _meta(db, key, default=None):
        row = db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def status(self) -> dict:
        if not self.path.exists():
            return dict(state='not_indexed', chunks=0, files=0)
        with _LOCK, closing(self.connect()) as db:
            count, files = db.execute('SELECT count(*),count(DISTINCT path) FROM chunks').fetchone()
            report = self._meta(db, 'report', {})
            return dict(state='ready' if count else 'not_indexed', chunks=count, files=files,
                        signature=self._meta(db, 'signature', ''), **report)

    def clear(self) -> None:
        with _LOCK:
            if self.path.exists():
                with closing(self.connect()) as db:
                    db.execute('DELETE FROM chunks')
                    db.execute('DELETE FROM metadata')
                    db.commit()

    def refresh(self, embed, signature: str, progress=None, cancel=None) -> dict:
        """Atualiza os vetores. ``signature`` identifica o provedor/modelo dos vetores."""
        lexical = CodeIndex(self.meta, self.root)
        lexical.refresh()
        with closing(lexical.connect()) as source:
            documents = {row['path']: (row['sha'], row['content']) for row in source.execute('SELECT path,sha,content FROM docs')}
        with _LOCK, closing(self.connect()) as db:
            if self._meta(db, 'signature') != signature:
                db.execute('DELETE FROM chunks')
                db.execute("INSERT OR REPLACE INTO metadata VALUES('signature',?)", (json.dumps(signature),))
                db.commit()
            stored = {row['path']: row['sha'] for row in db.execute('SELECT path,sha FROM chunks GROUP BY path')}
            for path in stored:
                if path not in documents:
                    db.execute('DELETE FROM chunks WHERE path=?', (path,))
            pending = []
            for path in sorted(documents):
                sha, content = documents[path]
                if stored.get(path) == sha:
                    continue
                for start, finish, body in chunks(content):
                    pending.append((path, sha, start, finish, body))
            db.commit()
            total = len(pending)
            limited = pending[:MAX_CHUNKS_PER_REFRESH]
            # só se substituem os excertos de um ficheiro quando TODOS os seus vetores chegaram
            allowed = {path for path, *_ in limited}
            if total > len(limited):
                cut_path = limited[-1][0] if limited else None
                if cut_path and any(item[0] == cut_path for item in pending[MAX_CHUNKS_PER_REFRESH:]):
                    allowed.discard(cut_path)
            work = [item for item in limited if item[0] in allowed]
            done = 0
            cancelled = False
            ready = {}
            for offset in range(0, len(work), BATCH):
                if cancel is not None and cancel.is_set():
                    cancelled = True
                    break
                batch = work[offset:offset + BATCH]
                vectors = embed([path + '\n' + body for path, _sha, _start, _finish, body in batch])
                if len(vectors) != len(batch):
                    raise ValueError('O modelo de embeddings não devolveu um vetor por excerto.')
                for item, vector in zip(batch, vectors):
                    ready.setdefault(item[0], []).append((item, _pack(vector)))
                done += len(batch)
                if progress:
                    progress(done, len(work))
            complete = {}
            expected = {}
            for item in work:
                expected[item[0]] = expected.get(item[0], 0) + 1
            for path, rows in ready.items():
                if len(rows) == expected[path]:
                    complete[path] = rows
            for path, rows in complete.items():
                db.execute('DELETE FROM chunks WHERE path=?', (path,))
                db.executemany('INSERT INTO chunks(path,sha,start,finish,text,vector) VALUES(?,?,?,?,?,?)',
                               [(p, sha, start, finish, body, blob) for (p, sha, start, finish, body), blob in rows])
            embedded = sum(len(rows) for rows in complete.values())
            report = dict(updated_at=time.time(), embedded=embedded, pending=total - embedded,
                          cancelled=cancelled, truncated=total > len(work) or cancelled,
                          coverage='Excertos de ' + str(CHUNK_LINES) + ' linhas dos ficheiros do índice lexical; até '
                                   + str(MAX_CHUNKS_PER_REFRESH) + ' excertos novos por atualização.')
            db.execute("INSERT OR REPLACE INTO metadata VALUES('report',?)", (json.dumps(report),))
            db.commit()
        return self.status()

    def search(self, query_vector, limit: int = 8) -> list[dict]:
        """Excertos mais próximos de ``query_vector`` (semelhança de cosseno, 1 = igual)."""
        if not self.path.exists():
            return []
        try:
            wanted = _unpack(_pack(query_vector))
        except ValueError:
            return []
        limit = min(30, max(1, int(limit)))
        with _LOCK, closing(self.connect()) as db:
            scored = []
            for row in db.execute('SELECT id,vector FROM chunks'):
                vector = _unpack(row['vector'])
                if len(vector) == len(wanted):
                    scored.append((math.sumprod(wanted, vector), row['id']))
            best = heapq.nlargest(limit * 3, scored)
            results, seen = [], set()
            for score, key in best:
                row = db.execute('SELECT path,sha,start,finish,text FROM chunks WHERE id=?', (key,)).fetchone()
                # excertos sobrepostos do mesmo ficheiro: fica o melhor de cada zona
                zone = (row['path'], row['start'] // CHUNK_LINES)
                if zone in seen:
                    continue
                seen.add(zone)
                target = self.root / row['path']
                try:
                    stale = not target.resolve().is_relative_to(self.root) or digest(read(target)) != row['sha']
                except (OSError, ValueError, TypeError):
                    stale = True
                if stale:
                    # o ficheiro mudou desde a indexação: não mostrar texto antigo como se fosse atual
                    results.append(dict(path=row['path'], line=row['start'], end_line=row['finish'], score=round(float(score), 4),
                                        stale=True, message='O ficheiro mudou; atualiza o índice de significado.'))
                    if len(results) >= limit:
                        break
                    continue
                results.append(dict(path=row['path'], sha256=row['sha'], line=row['start'], end_line=row['finish'],
                                    score=round(float(score), 4), excerpt=row['text'], stale=False))
                if len(results) >= limit:
                    break
            return results
