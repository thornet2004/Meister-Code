"""Base de conhecimento por projeto: notas que o agente grava e consulta.

Agnóstica à ferramenta: guarda texto + metadados (título, etiquetas, tipo, ref), venha de onde vier — análise do
próprio agente, ficheiros, ou a saída de uma ferramenta externa (disassembler, etc.). Fica em <meta_dir>/knowledge.sqlite,
na pasta .studio/ do projeto ativo (como a memória em grafo). Serve para trabalhar projetos grandes sem encher o
contexto: o agente pergunta só o que precisa em vez de carregar tudo.

Pesquisa: por palavras (FTS5) sempre; por significado (embeddings) quando a pesquisa semântica está ligada e
configurada — nesse caso cada nota guarda também o seu vetor, e a procura junta os dois (significado primeiro). Sem
semântica, cai só no FTS. O cálculo dos vetores (chamada ao provedor) é feito por quem chama (o despacho), que passa
o vetor da nota ao gravar e o vetor da consulta ao procurar; reutiliza-se o motor de embeddings do índice de código."""
import math
import re
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from code_semantic import _pack, _unpack


class KnowledgeStore:
    def __init__(self, meta_dir):
        self.path = Path(meta_dir) / "knowledge.sqlite"

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS notes(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                titulo TEXT NOT NULL,
                texto TEXT NOT NULL DEFAULT '',
                etiquetas TEXT NOT NULL DEFAULT '',
                tipo TEXT NOT NULL DEFAULT '',
                ref TEXT NOT NULL DEFAULT '',
                vector BLOB,
                assinatura TEXT NOT NULL DEFAULT '',
                criado REAL NOT NULL,
                atualizado REAL NOT NULL);
            CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(titulo,texto,etiquetas,ref,content='notes',content_rowid='id');
            CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN
                INSERT INTO notes_fts(rowid,titulo,texto,etiquetas,ref) VALUES(new.id,new.titulo,new.texto,new.etiquetas,new.ref);
            END;
            CREATE TRIGGER IF NOT EXISTS notes_ad AFTER DELETE ON notes BEGIN
                INSERT INTO notes_fts(notes_fts,rowid,titulo,texto,etiquetas,ref) VALUES('delete',old.id,old.titulo,old.texto,old.etiquetas,old.ref);
            END;
            CREATE TRIGGER IF NOT EXISTS notes_au AFTER UPDATE ON notes BEGIN
                INSERT INTO notes_fts(notes_fts,rowid,titulo,texto,etiquetas,ref) VALUES('delete',old.id,old.titulo,old.texto,old.etiquetas,old.ref);
                INSERT INTO notes_fts(rowid,titulo,texto,etiquetas,ref) VALUES(new.id,new.titulo,new.texto,new.etiquetas,new.ref);
            END;
        """)
        cols = {row[1] for row in connection.execute("PRAGMA table_info(notes)")}  # migra bases feitas antes dos vetores
        if "vector" not in cols:
            connection.execute("ALTER TABLE notes ADD COLUMN vector BLOB")
        if "assinatura" not in cols:
            connection.execute("ALTER TABLE notes ADD COLUMN assinatura TEXT NOT NULL DEFAULT ''")
        return connection

    @staticmethod
    def _fts_query(text):
        # cada palavra citada (AND implícito), para o texto do utilizador nunca ser lido como sintaxe do FTS5
        tokens = re.findall(r"\w+", text or "", re.UNICODE)[:20]
        return " ".join('"' + t + '"' for t in tokens)

    def save(self, titulo, texto="", etiquetas="", tipo="", ref="", note_id=None, vector=None, signature=""):
        titulo = (titulo or "").strip()[:200]
        if not titulo:
            raise ValueError("A nota precisa de um título.")
        texto = (texto or "")[:20000]
        etiquetas = (etiquetas or "").strip()[:500]
        tipo = (tipo or "").strip()[:100]
        ref = (ref or "").strip()[:300]
        blob = None
        if vector is not None:
            try:
                blob = _pack(vector)
            except (ValueError, TypeError):
                blob = None
        signature = (signature or "")[:200] if blob is not None else ""
        now = time.time()
        with closing(self._connect()) as db, db:
            if note_id is not None:
                if not db.execute("SELECT 1 FROM notes WHERE id=?", (int(note_id),)).fetchone():
                    raise ValueError("Não existe nota com esse id.")
                target = int(note_id)
            else:  # idempotente pelo título: regravar o mesmo título atualiza a nota em vez de duplicar
                row = db.execute("SELECT id FROM notes WHERE titulo=? ORDER BY atualizado DESC LIMIT 1", (titulo,)).fetchone()
                target = row["id"] if row else None
            if target is not None:
                db.execute("UPDATE notes SET titulo=?,texto=?,etiquetas=?,tipo=?,ref=?,vector=?,assinatura=?,atualizado=? WHERE id=?",
                           (titulo, texto, etiquetas, tipo, ref, blob, signature, now, target))
                return {"id": target, "titulo": titulo, "atualizada": True}
            cursor = db.execute("INSERT INTO notes(titulo,texto,etiquetas,tipo,ref,vector,assinatura,criado,atualizado) VALUES(?,?,?,?,?,?,?,?,?)",
                                (titulo, texto, etiquetas, tipo, ref, blob, signature, now, now))
            return {"id": cursor.lastrowid, "titulo": titulo, "atualizada": False}

    def search(self, query="", limit=20, query_vector=None, signature=""):
        if not self.path.exists():
            return {"notas": []}
        limit = max(1, min(40, int(limit or 20)))
        with closing(self._connect()) as db, db:
            order, scores = [], {}
            if query_vector is not None and signature:  # por significado (quando configurado)
                try:
                    wanted = _unpack(_pack(query_vector))
                except (ValueError, TypeError):
                    wanted = None
                if wanted is not None:
                    scored = []
                    for row in db.execute("SELECT id,vector FROM notes WHERE assinatura=? AND vector IS NOT NULL", (signature,)):
                        vec = _unpack(row["vector"])
                        if len(vec) == len(wanted):
                            scored.append((math.sumprod(wanted, vec), row["id"]))
                    scored.sort(reverse=True)
                    for score, nid in scored[:limit]:
                        scores[nid] = round(float(score), 4)
                        order.append(nid)
            match = self._fts_query(query)  # por palavras (completa a semântica, ou é o único critério)
            if match:
                for row in db.execute("SELECT n.id FROM notes_fts JOIN notes n ON n.id=notes_fts.rowid WHERE notes_fts MATCH ? ORDER BY bm25(notes_fts) LIMIT ?", (match, limit)):
                    if row["id"] not in scores:
                        order.append(row["id"])
            elif not order:  # sem pesquisa e sem semântica: as mais recentes
                for row in db.execute("SELECT id FROM notes ORDER BY atualizado DESC LIMIT ?", (limit,)):
                    order.append(row["id"])
            order = order[:limit]
            if not order:
                return {"notas": []}
            rows = {r["id"]: r for r in db.execute(
                "SELECT id,titulo,tipo,ref,etiquetas,substr(texto,1,300) AS trecho FROM notes WHERE id IN (%s)" % ",".join("?" * len(order)), order)}
            notas = []
            for nid in order:
                r = rows.get(nid)
                if not r:
                    continue
                item = {"id": r["id"], "titulo": r["titulo"], "tipo": r["tipo"], "ref": r["ref"], "etiquetas": r["etiquetas"], "trecho": r["trecho"]}
                if nid in scores:
                    item["semelhanca"] = scores[nid]
                notas.append(item)
            return {"notas": notas}

    def read(self, note_id):
        try:
            note_id = int(note_id)
        except (TypeError, ValueError):
            raise ValueError("id inválido.")
        if not self.path.exists():
            return {"encontrada": False}
        with closing(self._connect()) as db, db:
            row = db.execute("SELECT id,titulo,texto,etiquetas,tipo,ref,criado,atualizado FROM notes WHERE id=?", (note_id,)).fetchone()
        return {"encontrada": True, "nota": dict(row)} if row else {"encontrada": False}

    def forget(self, note_id):
        try:
            note_id = int(note_id)
        except (TypeError, ValueError):
            raise ValueError("id inválido.")
        if not self.path.exists():
            return {"apagada": False}
        with closing(self._connect()) as db, db:
            removed = db.execute("DELETE FROM notes WHERE id=?", (note_id,)).rowcount
        return {"apagada": removed > 0}
