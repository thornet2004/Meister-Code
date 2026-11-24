"""Git de leitura, SQLite e grafo de memória por contexto."""
import json
import re
import shutil
import sqlite3
import subprocess
import time
from contextlib import closing
from pathlib import Path


def scoped_path(path, context):
    base = Path(context["base"]).resolve()
    target = Path(path or ".").expanduser()
    if not target.is_absolute():
        target = base / target
    target = target.resolve()
    if context.get("scope") != "computer" and target != base and base not in target.parents:
        raise ValueError("Caminho fora da pasta de trabalho autorizada.")
    return target


def git_query(args, context):
    executable = shutil.which("git")
    if not executable:
        raise RuntimeError("Git não está instalado ou disponível no PATH.")
    folder = scoped_path(args.get("pasta", "."), context)
    action = args.get("acao")
    revision = args.get("revisao") or "HEAD"
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_./~^:@-]{0,150}", revision):
        raise ValueError("Revisão Git inválida.")
    commands = {
        "estado":["status","--short","--branch"],
        "diff":["diff","--no-ext-diff","--no-textconv"] + (["--cached"] if args.get("staged") else []) + ["--"],
        "historico":["log","--oneline","--decorate","-n",str(max(1,min(50,int(args.get("limite",20))))),"--"],
        "branches":["branch","--list"],
        "commit":["show","--no-ext-diff","--no-textconv","--stat",revision,"--"],
    }
    if action not in commands:
        raise ValueError("Ação Git inválida.")
    repository = subprocess.run([executable,"-c","core.fsmonitor=false","rev-parse","--show-toplevel"],cwd=folder,
        capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=10,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    if repository.returncode == 0:
        scoped_path(repository.stdout.strip(),context)
    result = subprocess.run([executable,"--no-pager","-c","core.fsmonitor=false",*commands[action]],
        cwd=folder,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=20,
        creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    return {"ok":result.returncode==0,"code":result.returncode,"pasta":str(folder),"output":(result.stdout+result.stderr)[:24000]}


def sqlite_run(path, sql, parameters=None, write=False, limit=100, schema=False):
    path = Path(path)
    if write:
        path.parent.mkdir(parents=True,exist_ok=True)
    uri = path.as_uri() + ("?mode=rwc" if write else "?mode=ro")
    with closing(sqlite3.connect(uri,uri=True,timeout=5)) as connection, connection:
        connection.row_factory = sqlite3.Row
        if not write:
            connection.execute("PRAGMA query_only=ON")
        def authorize(action, first, second, database, trigger):
            if action in (sqlite3.SQLITE_ATTACH,sqlite3.SQLITE_DETACH):
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        connection.set_authorizer(authorize)
        deadline = time.monotonic()+10
        connection.set_progress_handler(lambda: int(time.monotonic()>deadline),1000)
        if schema:
            rows = connection.execute("SELECT name,type,sql FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%' ORDER BY name").fetchmany(200)
            data=[]
            for row in rows:
                item=dict(row)
                if item["type"]=="table":
                    quoted=item["name"].replace('"','""')
                    item["columns"]=[dict(c) for c in connection.execute('PRAGMA table_info("'+quoted+'")')]
                data.append(item)
            return {"schema":data}
        cursor=connection.execute(sql,parameters or [])
        cap=max(1,min(500,int(limit)))
        rows=cursor.fetchmany(cap+1) if cursor.description else []
        data=[{key:(value[:512].hex() if isinstance(value,bytes) else value[:4000] if isinstance(value,str) else value) for key,value in dict(row).items()} for row in rows[:cap]]
        return {"rows":data,"truncated":len(rows)>cap,"changes":connection.total_changes,"columns":[c[0] for c in cursor.description or []]}


class GraphMemory:
    def __init__(self, meta_dir):
        self.path=Path(meta_dir)/"memory.sqlite"

    def _connect(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        connection=sqlite3.connect(self.path,timeout=5)
        connection.row_factory=sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS entities(name TEXT PRIMARY KEY,kind TEXT NOT NULL,observations TEXT NOT NULL,updated_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS relations(source TEXT REFERENCES entities(name) ON DELETE CASCADE,target TEXT REFERENCES entities(name) ON DELETE CASCADE,label TEXT NOT NULL,PRIMARY KEY(source,target,label));
        """)
        return connection

    def save(self,name,kind,observations):
        name=(name or "").strip()[:200]
        if not name:raise ValueError("A entidade precisa de um nome.")
        if not isinstance(observations,list) or any(not isinstance(x,str) for x in observations):
            raise ValueError("As observações devem ser uma lista de textos.")
        with closing(self._connect()) as db, db:
            old=db.execute("SELECT observations FROM entities WHERE name=?",(name,)).fetchone()
            facts=list(dict.fromkeys((json.loads(old[0]) if old else [])+[x[:2000] for x in observations]))[-100:]
            db.execute("INSERT INTO entities VALUES(?,?,?,?) ON CONFLICT(name) DO UPDATE SET kind=excluded.kind,observations=excluded.observations,updated_at=excluded.updated_at",(name,(kind or "facto")[:100],json.dumps(facts,ensure_ascii=False),time.time()))
        return {"saved":name,"observations":facts}

    def relate(self,source,target,label):
        if not all(isinstance(x,str) and x.strip() for x in (source,target,label)):
            raise ValueError("Origem, destino e relação são obrigatórios.")
        with closing(self._connect()) as db, db:
            db.execute("INSERT OR IGNORE INTO relations VALUES(?,?,?)",(source,target,label[:200]))
        return {"related":True}

    def search(self,query=""):
        if not self.path.exists():return {"entities":[],"relations":[]}
        with closing(self._connect()) as db, db:
            value="%"+query[:500]+"%"
            rows=db.execute("SELECT * FROM entities WHERE name LIKE ? OR kind LIKE ? OR observations LIKE ? ORDER BY updated_at DESC LIMIT 40",(value,value,value)).fetchall()
            entities=[{"name":r["name"],"type":r["kind"],"observations":json.loads(r["observations"])} for r in rows]
            names={r["name"] for r in rows}
            relations=[dict(r) for r in db.execute("SELECT * FROM relations ORDER BY source,target LIMIT 500") if r["source"] in names or r["target"] in names][:100]
            return {"entities":entities,"relations":relations}

    def forget(self,name):
        with closing(self._connect()) as db, db:
            deleted=db.execute("DELETE FROM entities WHERE name=?",(name,)).rowcount
        return {"forgotten":deleted>0}
