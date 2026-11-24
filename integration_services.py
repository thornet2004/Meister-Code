"""Conectores incluídos na app; configuração privada, HTTP e SQL parametrizado."""
from __future__ import annotations

import json
import os
import re
import ssl
import threading
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit, urljoin

import requests
import config
from mcp_oauth import _protect

KINDS = ("fetch", "brave", "postgres", "mysql", "discord")
_LOCK = threading.RLock()


class SettingsStore:
    def __init__(self, kind, root=None):
        if kind not in KINDS:
            raise ValueError("Conector desconhecido.")
        self.kind = kind
        self.path = Path(root or config.config_dir()) / "integration-secrets" / (kind + ".dat")
        self.entropy = ("studio-services:" + kind).encode()

    def read(self):
        with _LOCK:
            return json.loads(_protect(self.path.read_bytes(), self.entropy, True)) if self.path.exists() else {}

    def write(self, values):
        with _LOCK:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_bytes(_protect(json.dumps(values).encode(), self.entropy))
            if os.name != "nt":
                temporary.chmod(0o600)
            temporary.replace(self.path)


def validate_settings(kind, values):
    values = dict(values)
    if kind in ("postgres", "mysql"):
        for key in ("host", "database", "user"):
            if not values.get(key, "").strip():
                raise ValueError("Falta o campo: " + key)
        try:
            port = int(values.get("port") or (5432 if kind == "postgres" else 3306))
        except (TypeError, ValueError):
            raise ValueError("Porta inválida.") from None
        if not 1 <= port <= 65535:
            raise ValueError("Porta inválida.")
        values["port"] = str(port)
        if values.get("tls", "true") not in ("true", "false"):
            raise ValueError("Opção TLS inválida.")
        values.setdefault("tls", "true")
    if kind in ("discord", "postgres", "mysql"):
        if values.get("readonly", "true") not in ("true", "false"):
            raise ValueError("Opção de escrita inválida.")
        values.setdefault("readonly", "true")
    if kind in ("brave", "discord"):
        key = "api_key" if kind == "brave" else "token"
        if not values.get(key, "").strip():
            raise ValueError("Falta a chave de API." if kind == "brave" else "Falta o token do bot Discord.")
        if any(ord(c) < 32 for c in values[key]):
            raise ValueError("Credencial inválida.")
    return values


def definition(name, description, properties=None, required=None, write=False):
    return {"name": name, "description": description,
            "inputSchema": {"type": "object", "properties": properties or {}, "required": required or [], "additionalProperties": False},
            "annotations": {"readOnlyHint": not write, "destructiveHint": write}}


def tools(kind, settings):
    test = definition("connection_test", "Testa a ligação ao serviço, sem escrever dados.")
    text = {"type": "string"}
    limit = {"type": "integer", "minimum": 1, "maximum": 200}
    if kind == "fetch":
        return [definition("fetch_url", "Lê uma página HTTP/HTTPS e extrai texto e links. Não executa JavaScript.", {"url": text, "max_chars": {"type": "integer", "minimum": 100, "maximum": 50000}}, ["url"]), test]
    if kind == "brave":
        return [definition("web_search", "Pesquisa atualizada na web através do Brave Search.", {"query": text, "count": {"type": "integer", "minimum": 1, "maximum": 20}}, ["query"]), test]
    if kind in ("postgres", "mysql"):
        result = [test, definition("database_schema", "Lista tabelas e colunas da base de dados configurada."),
                  definition("query", "Consulta SQL numa transação só de leitura. Parâmetros usam %s; máximo 200 linhas.", {"sql": text, "params": {"type": "array", "items": {}}, "limit": limit}, ["sql"])]
        if settings.get("readonly", "true") == "false":
            result.append(definition("execute", "Executa uma instrução SQL de escrita e confirma a transação. Parâmetros usam %s.", {"sql": text, "params": {"type": "array", "items": {}}}, ["sql"], write=True))
        return result
    result = [test, definition("list_servers", "Lista servidores aos quais o bot Discord tem acesso."),
              definition("list_channels", "Lista canais de um servidor Discord.", {"server_id": text}, ["server_id"]),
              definition("read_messages", "Lê mensagens de um canal Discord. Depende das permissões e do Message Content Intent do bot.", {"channel_id": text, "limit": {"type": "integer", "minimum": 1, "maximum": 100}}, ["channel_id"])]
    if settings.get("readonly", "true") == "false":
        result.append(definition("send_message", "Envia uma mensagem num canal Discord, sem notificações de menções.", {"channel_id": text, "text": text}, ["channel_id", "text"], write=True))
    return result


class PageText(HTMLParser):
    def __init__(self, base):
        super().__init__(convert_charrefs=True)
        self.base = base
        self.parts = []
        self.links = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "template"):
            self.hidden += 1
        if not self.hidden:
            if tag in ("p", "div", "br", "h1", "h2", "li", "tr"):
                self.parts.append("\n")
            href = dict(attrs).get("href")
            if tag == "a" and href and len(self.links) < 100:
                url = urljoin(self.base, href)
                if urlsplit(url).scheme in ("http", "https"):
                    self.links.append(url)

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "template"):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def fetch_url(url, max_chars=20000):
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Usa um URL HTTP/HTTPS sem credenciais.")
    maximum = max(100, min(int(max_chars), 50000))
    started = time.monotonic()
    # Sem credenciais, sem .netrc e sem esquemas locais nos redirecionamentos.
    with requests.Session() as session:
        session.trust_env = False
        with session.get(url, timeout=(10, 15), stream=True, headers={"User-Agent": "StudioMedia-Fetch/1.0"}) as response:
            response.raise_for_status()
            data = bytearray()
            for chunk in response.iter_content(8192):
                if len(data) + len(chunk) > 2 * 1024 * 1024 or time.monotonic() - started > 25:
                    raise ValueError("A página excedeu o limite de 2 MB ou de tempo.")
                data.extend(chunk)
            content_type = response.headers.get("Content-Type", "").lower()
            if not any(t in content_type for t in ("text/", "json", "xml", "javascript")):
                raise ValueError("O Fetch lê páginas e documentos de texto; usa o browser para outros formatos.")
            encoding = response.encoding or "utf-8"
            text = data.decode(encoding, errors="replace")
            links = []
            if "html" in content_type:
                parser = PageText(response.url)
                parser.feed(text)
                text = re.sub(r"[ \t]+", " ", "".join(parser.parts))
                text = re.sub(r"\n\s*\n", "\n", text).strip()
                links = list(dict.fromkeys(parser.links))
            return {"url": response.url, "text": text[:maximum], "truncated": len(text) > maximum, "links": links}


def bounded_int(value, default, maximum):
    return max(1, min(int(value if value is not None else default), maximum))


def http_json(method, url, **kwargs):
    with requests.Session() as session:
        session.trust_env = False
        with session.request(method, url, timeout=(10, 20), allow_redirects=False, **kwargs) as response:
            if response.status_code == 429:
                raise ValueError("Limite de pedidos atingido; aguarda antes de repetir.")
            if not 200 <= response.status_code < 300:
                raise ValueError("O serviço recusou o pedido (HTTP " + str(response.status_code) + "). Verifica credenciais e permissões.")
            return response.json()


def discord(operation, args, settings):
    headers = {"Authorization": "Bot " + settings["token"], "User-Agent": "StudioMedia/1.0"}
    base = "https://discord.com/api/v10"
    def snowflake(key):
        value = str(args.get(key, ""))
        if not re.fullmatch(r"[0-9]{1,22}", value):
            raise ValueError("ID Discord inválido: " + key)
        return value
    if operation == "connection_test":
        user = http_json("GET", base + "/users/@me", headers=headers)
        if not user.get("bot"):
            raise ValueError("Usa um token de bot Discord.")
        return {"connected": True, "bot": user.get("username"), "id": user.get("id")}
    if operation == "list_servers":
        data = http_json("GET", base + "/users/@me/guilds", headers=headers, params={"limit": 100})
        return [{"id": row["id"], "name": row.get("name")} for row in data]
    if operation == "list_channels":
        data = http_json("GET", base + "/guilds/" + snowflake("server_id") + "/channels", headers=headers)
        return [{"id": row["id"], "name": row.get("name"), "type": row.get("type")} for row in data][:200]
    channel = snowflake("channel_id")
    url = base + "/channels/" + channel + "/messages"
    if operation == "read_messages":
        data = http_json("GET", url, headers=headers, params={"limit": bounded_int(args.get("limit"), 30, 100)})
        return [{"id": row["id"], "author": row.get("author", {}).get("username"), "content": row.get("content", ""), "timestamp": row.get("timestamp"), "attachments": [{"filename": a.get("filename"), "url": a.get("url")} for a in row.get("attachments", [])]} for row in data]
    message = args.get("text", "")
    if not isinstance(message, str) or not 1 <= len(message) <= 2000:
        raise ValueError("A mensagem deve ter entre 1 e 2000 caracteres.")
    data = http_json("POST", url, headers=headers, json={"content": message, "allowed_mentions": {"parse": []}})
    return {"id": data["id"], "channel_id": channel, "sent": True}


def database(kind, operation, args, settings):
    context = ssl.create_default_context() if settings.get("tls", "true") == "true" else False
    kwargs = {"host": settings["host"], "port": int(settings["port"]), "database": settings["database"], "user": settings["user"], "password": settings.get("password", "")}
    if kind == "postgres":
        import pg8000.dbapi
        connection = pg8000.dbapi.connect(**kwargs, timeout=15, ssl_context=context)
    else:
        import pymysql
        connection = pymysql.connect(**kwargs, connect_timeout=10, read_timeout=15, write_timeout=15, ssl=context or None, ssl_disabled=not bool(context), local_infile=False, charset="utf8mb4", autocommit=False)
        if context and not connection._secure:
            connection.close()
            raise ValueError("O servidor MySQL não negociou TLS; verifica a configuração.")
    try:
        cursor = connection.cursor()
        write = operation == "execute"
        if not write:
            cursor.execute("SET TRANSACTION READ ONLY" if kind == "postgres" else "START TRANSACTION READ ONLY")
        if kind == "postgres":
            cursor.execute("SET LOCAL statement_timeout = 15000")
        if operation == "connection_test":
            sql, params = "SELECT 1", []
        elif operation == "database_schema":
            sql = "SELECT table_schema, table_name, column_name, data_type FROM information_schema.columns WHERE "
            sql += "table_schema NOT IN ('pg_catalog', 'information_schema')" if kind == "postgres" else "table_schema = DATABASE()"
            sql += " ORDER BY table_schema, table_name, ordinal_position LIMIT 200"
            params = []
        else:
            sql = str(args.get("sql", "")).strip().rstrip(";").strip()
            params = args.get("params", [])
            if not sql or len(sql) > 50000 or not isinstance(params, list):
                raise ValueError("Indica SQL e parâmetros válidos.")
            if ";" in sql or "--" in sql or "/*" in sql:
                raise ValueError("Envia uma instrução de cada vez, sem comentários SQL.")
            if not write and not re.match(r"^(SELECT|WITH|SHOW)\b", sql, re.I):
                raise ValueError("Usa query para SELECT/WITH/SHOW; execute para escrita.")
            if write and not re.match(r"^(INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|TRUNCATE|REPLACE)\b", sql, re.I):
                raise ValueError("Tipo de instrução de escrita não suportado.")
        cursor.execute(sql, params)
        result = {"affected_rows": cursor.rowcount}
        if cursor.description:
            maximum = bounded_int(args.get("limit"), 100, 200)
            rows = cursor.fetchmany(maximum + 1)
            result.update(columns=[str(c[0]) for c in cursor.description], rows=[list(row) for row in rows[:maximum]], truncated=len(rows) > maximum)
        if write:
            connection.commit()
        else:
            connection.rollback()
        return {"connected": True} if operation == "connection_test" else result
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def execute(kind, operation, args, settings):
    allowed = {t["name"] for t in tools(kind, settings)}
    if operation not in allowed:
        raise ValueError("Ferramenta indisponível. Ativa a escrita na configuração se necessário.")
    if kind == "fetch":
        return {"ready": True, "network_tested": False} if operation == "connection_test" else fetch_url(args["url"], args.get("max_chars", 20000))
    settings = validate_settings(kind, settings)
    if kind == "brave":
        query = "Brave Search" if operation == "connection_test" else args.get("query", "")
        if not isinstance(query, str) or not 1 <= len(query) <= 600 or len(query.split()) > 75:
            raise ValueError("A pesquisa deve ter até 600 caracteres e 75 palavras.")
        result = http_json("GET", "https://api.search.brave.com/res/v1/web/search", headers={"X-Subscription-Token": settings["api_key"], "Accept": "application/json"}, params={"q": query, "count": bounded_int(args.get("count"), 8, 20)})
        return {"connected": True} if operation == "connection_test" else {"results": [{"title": r.get("title"), "url": r.get("url"), "description": r.get("description")} for r in result.get("web", {}).get("results", [])]}
    if kind == "discord":
        return discord(operation, args, settings)
    return database(kind, operation, args, settings)


def safe_execute(kind, operation, args, settings):
    try:
        result = execute(kind, operation, args, settings)
        # Tipos SQL como Decimal/datetime são representados de forma legível.
        text = json.dumps(result, ensure_ascii=False, default=str)
        for key in ("password", "token", "api_key"):
            secret = settings.get(key)
            if secret:
                text = text.replace(json.dumps(secret, ensure_ascii=False)[1:-1], "[credencial oculta]")
        if len(text) > 150000:
            return {"isError": True, "content": [{"type": "text", "text": "Resultado demasiado grande. Reduz os dados ou o limite da consulta."}]}
        return {"isError": False, "content": [{"type": "text", "text": text}]}
    except Exception as exc:
        # Drivers e servidores podem repetir passwords/SQL nos erros.
        message = str(exc) if type(exc) is ValueError else "Falha na ligação ou operação. Verifica endereço, credenciais, permissões e SQL."
        for key in ("password", "token", "api_key"):
            secret = settings.get(key)
            if secret:
                message = message.replace(secret, "[credencial oculta]")
        return {"isError": True, "content": [{"type": "text", "text": message}]}
