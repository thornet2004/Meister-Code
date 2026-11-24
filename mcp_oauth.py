"""OAuth MCP com SDK oficial, PKCE, callback local e DPAPI no Windows."""
import asyncio
import ctypes
import hashlib
import json
import logging
import os
import queue
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import config

logging.getLogger("mcp.client.auth").setLevel(logging.CRITICAL)
_locks = {}
_guard = threading.Lock()


class OAuthRequired(PermissionError):
    pass


def _protect(data, entropy, decrypt=False):
    if os.name != "nt":
        # Fora do Windows não há DPAPI: o ficheiro fica com permissões 0600.
        return data
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]
    def blob(value):
        buffer = ctypes.create_string_buffer(value)
        return Blob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer
    source, source_buffer = blob(data)
    salt, salt_buffer = blob(entropy)
    output = Blob()
    function = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(source), None, ctypes.byref(salt), None, None, 1, ctypes.byref(output)):
        raise RuntimeError("Não foi possível proteger ou abrir as credenciais OAuth deste utilizador.")
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        free = ctypes.windll.kernel32.LocalFree
        free.argtypes = [ctypes.c_void_p]; free.restype = ctypes.c_void_p
        free(output.data)


class OAuthStore:
    def __init__(self, server):
        self.server = server
        self.binding = hashlib.sha256((server["id"] + "|" + server["url"]).encode()).digest()
        self.path = config.config_dir() / "oauth" / (self.binding.hex() + ".dat")
        with _guard:
            self.lock = _locks.setdefault(str(self.path), threading.RLock())

    def read(self):
        with self.lock:
            if not self.path.exists(): return {}
            return json.loads(_protect(self.path.read_bytes(), self.binding, True))

    def update(self, **values):
        with self.lock:
            data = self.read(); data.update(values)
            self._write(data)

    def replace(self, data):
        with self.lock:
            if data:
                self._write(dict(data))
            else:
                self.path.unlink(missing_ok=True)

    def _write(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_bytes(_protect(json.dumps(data, ensure_ascii=True).encode(), self.binding))
        if os.name != "nt":
            os.chmod(temporary, 0o600)
        temporary.replace(self.path)
        if os.name != "nt":
            os.chmod(self.path, 0o600)

    def clear(self):
        with self.lock:
            self.path.unlink(missing_ok=True)

    async def get_tokens(self):
        from mcp.shared.auth import OAuthToken
        value = self.read().get("tokens")
        return OAuthToken.model_validate(value) if value else None

    async def set_tokens(self, tokens):
        old = self.read().get("tokens") or {}
        data = tokens.model_dump(mode="json")
        if not data.get("refresh_token") and old.get("refresh_token"):
            data["refresh_token"] = old["refresh_token"]
        expiry = time.time() + tokens.expires_in if tokens.expires_in is not None else None
        self.update(tokens=data, expires_at=expiry)

    async def get_client_info(self):
        from mcp.shared.auth import OAuthClientInformationFull
        value = self.read().get("client")
        return OAuthClientInformationFull.model_validate(value) if value else None

    async def set_client_info(self, info):
        self.update(client=info.model_dump(mode="json"))


def token_status(server):
    if server.get("auth_mode") != "oauth": return {"linked": False}
    try:
        data = OAuthStore(server).read()
        return {"linked": bool(data.get("tokens", {}).get("access_token")), "expires_at": data.get("expires_at")}
    except Exception:
        return {"linked": False}


def secret_values(server):
    if server.get("auth_mode") != "oauth": return []
    try:
        data = OAuthStore(server).read()
        values = [v for key in ("tokens", "client") for name, v in (data.get(key) or {}).items()
                  if name in ("access_token", "refresh_token", "client_secret") and isinstance(v, str)]
        if data.get("manual_client_secret"): values.append(data["manual_client_secret"])
        return values
    except Exception:
        return []


class Callback:
    def __init__(self, store):
        self.result = queue.Queue(maxsize=1); self.expected_state = None; self.expected_issuer = None
        old = store.read().get("redirect_uri", "")
        port = store.server.get("oauth_callback_port") or (urlsplit(old).port if old else 0)
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                parsed = urlsplit(self.path); query = parse_qs(parsed.query)
                state = query.get("state", [""])[0]
                if parsed.path != "/oauth/callback":
                    self.send_error(404); return
                if not owner.expected_state or not secrets.compare_digest(state, owner.expected_state):
                    self.send_error(400, "Invalid state"); return
                issuer = query.get("iss", [None])[0]
                if issuer and owner.expected_issuer and issuer.rstrip("/") != owner.expected_issuer.rstrip("/"):
                    self.send_error(400, "Invalid issuer"); return
                if self.headers.get("Host") != f"127.0.0.1:{owner.http.server_port}":
                    self.send_error(400, "Invalid host"); return
                try:
                    owner.result.put_nowait({"code": query.get("code", [""])[0], "state": state, "error": query.get("error", [None])[0]})
                except queue.Full:
                    self.send_error(409); return
                body = "<!doctype html><meta charset='utf-8'><title>Studio de Média</title><h2>Autorização recebida</h2><p>Podes voltar à aplicação.</p>".encode()
                self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body))); self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Security-Policy", "default-src 'none'"); self.send_header("Referrer-Policy", "no-referrer")
                self.end_headers(); self.wfile.write(body)
        try:
            self.http = ThreadingHTTPServer(("127.0.0.1", port or 0), Handler)
        except OSError:
            # O registo dinâmico terá de ser renovado se a porta anterior estiver ocupada.
            self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            if not store.server.get("oauth_client_id"): store.update(client=None)
            else:
                self.http.server_close()
                raise RuntimeError("A porta de retorno OAuth registada está ocupada.")
        self.uri = f"http://127.0.0.1:{self.http.server_port}/oauth/callback"
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True); self.thread.start()

    async def wait(self, cancel):
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            if cancel and cancel.is_set(): raise OAuthRequired("Autorização cancelada.")
            try:
                result = self.result.get_nowait()
                if result["error"]: raise OAuthRequired("Autorização recusada pelo utilizador.")
                return result["code"], result["state"]
            except queue.Empty:
                await asyncio.sleep(0.1)
        raise OAuthRequired("A autorização expirou após três minutos.")

    def close(self):
        self.http.shutdown(); self.http.server_close(); self.thread.join(timeout=1)


async def _request(server, interactive=False, opener=None, cancel=None, stage=None, force_refresh=False):
    import httpx
    from mcp.client.auth import OAuthClientProvider
    from mcp.shared.auth import OAuthClientMetadata, OAuthClientInformationFull, OAuthMetadata, ProtectedResourceMetadata
    store = OAuthStore(server)
    callback = Callback(store) if interactive else None
    existing = store.read()
    uri = callback.uri if callback else existing.get("redirect_uri", "http://127.0.0.1/oauth/callback")
    store.update(redirect_uri=uri)
    metadata = OAuthClientMetadata(redirect_uris=[uri], client_name="Studio de Média", token_endpoint_auth_method="none",
                                   grant_types=["authorization_code", "refresh_token"], response_types=["code"], scope=server.get("oauth_scope") or None)
    if server.get("oauth_client_id") and not existing.get("client"):
        info = OAuthClientInformationFull(**metadata.model_dump(), client_id=server["oauth_client_id"],
                                          client_secret=existing.get("manual_client_secret"))
        if info.client_secret: info.token_endpoint_auth_method = "client_secret_post"
        await store.set_client_info(info)

    async def redirect(url):
        if not interactive: raise OAuthRequired("É necessário ligar a conta nas Configurações.")
        callback.expected_state = parse_qs(urlsplit(url).query).get("state", [None])[0]
        callback.expected_issuer = str(provider.context.oauth_metadata.issuer) if provider.context.oauth_metadata else provider.context.auth_server_url
        if stage: stage("waiting", "Conclui o início de sessão e a autorização no browser.")
        if not (opener or webbrowser.open)(url):
            raise OAuthRequired("Não foi possível abrir o browser do sistema.")

    async def returned():
        if not callback: raise OAuthRequired("É necessário ligar a conta nas Configurações.")
        return await callback.wait(cancel)

    provider = OAuthClientProvider(server_url=server["url"], client_metadata=metadata, storage=store,
                                   redirect_handler=redirect, callback_handler=returned, timeout=180)
    # O SDK aceita o armazenamento de tokens; estes dados mantêm a expiração e o emissor entre arranques.
    expiry = existing.get("expires_at")
    provider.context.token_expiry_time = (time.time() - 1) if force_refresh else (expiry - 10 if expiry else None)
    if existing.get("oauth_metadata"): provider.context.oauth_metadata = OAuthMetadata.model_validate(existing["oauth_metadata"])
    if existing.get("resource_metadata"): provider.context.protected_resource_metadata = ProtectedResourceMetadata.model_validate(existing["resource_metadata"])
    provider.context.auth_server_url = existing.get("auth_server_url")
    try:
        async with httpx.AsyncClient(auth=provider, timeout=20, follow_redirects=False) as client:
            response = await client.post(server["url"], json={"jsonrpc":"2.0","id":"oauth-probe","method":"server/discover","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientInfo":{"name":"studio-media","version":"2.0"},"io.modelcontextprotocol/clientCapabilities":{}}}},
                                         headers={"Accept":"application/json, text/event-stream","MCP-Protocol-Version":"2026-07-28","Mcp-Method":"server/discover"})
        data = store.read()
        if response.status_code in (401, 403) or not (data.get("tokens") or {}).get("access_token"):
            raise OAuthRequired("Não foi possível autorizar a conta neste servidor.")
        store.update(redirect_uri=uri, oauth_metadata=provider.context.oauth_metadata.model_dump(mode="json") if provider.context.oauth_metadata else None,
                     resource_metadata=provider.context.protected_resource_metadata.model_dump(mode="json") if provider.context.protected_resource_metadata else None,
                     auth_server_url=provider.context.auth_server_url)
        return data["tokens"]["access_token"]
    finally:
        if callback: callback.close()


def access_token(server, force_refresh=False):
    store = OAuthStore(server); data = store.read(); tokens = data.get("tokens") or {}
    if not tokens.get("access_token"): raise OAuthRequired("Clica em Ligar conta nas Configurações do servidor MCP.")
    expired = bool(data.get("expires_at")) and data["expires_at"] <= time.time() + 10
    if force_refresh or expired:
        if not tokens.get("refresh_token"): raise OAuthRequired("A autorização expirou. Volta a ligar a conta.")
        try:
            return asyncio.run(_request(server,force_refresh=True))
        except Exception:
            raise OAuthRequired("Não foi possível renovar a autorização. Volta a ligar a conta nas Configurações.") from None
    return tokens["access_token"]


class OAuthJobs:
    def __init__(self, on_success=None, opener=None):
        self.jobs = {}; self.lock = threading.RLock(); self.on_success = on_success; self.opener = opener

    def start(self, server):
        sid = server["id"]
        with self.lock:
            old = self.jobs.get(sid)
            if old and old["state"] in ("starting", "waiting"): return self.status(sid)
            store = OAuthStore(server)
            backup = store.read()
            store.update(tokens=None, expires_at=None)
            job = {"state":"starting", "message":"A preparar a ligação segura…", "cancel":threading.Event()}; self.jobs[sid] = job
            def stage(state, message):
                with self.lock: job.update(state=state, message=message)
            def restore():
                if job.get("discard"):
                    try: store.clear()
                    except Exception: pass
                    return
                try: store.replace(backup)
                except Exception: pass
            def run():
                try:
                    asyncio.run(_request(server, True, self.opener, job["cancel"], stage))
                    if job["cancel"].is_set():
                        restore(); stage("cancelled", "Ligação cancelada."); return
                    try:
                        if self.on_success: self.on_success(sid)
                    except Exception:
                        pass
                    stage("connected", "Conta autorizada. As ferramentas já podem ser descobertas.")
                except Exception as exc:
                    text = str(exc).lower()
                    restore()
                    if job["cancel"].is_set(): stage("cancelled", "Ligação cancelada.")
                    elif "registration" in text or "register" in text: stage("error", "O serviço pode exigir um Client ID próprio. Verifica as opções avançadas de OAuth.")
                    elif isinstance(exc, OAuthRequired): stage("error", str(exc))
                    else: stage("error", "Não foi possível concluir OAuth (" + type(exc).__name__ + "). Verifica o endpoint e o suporte OAuth do serviço.")
            job["thread"] = threading.Thread(target=run, daemon=True); job["thread"].start()
            return self.status(sid)

    def status(self, sid):
        with self.lock:
            job = self.jobs.get(sid)
            return {"state":job["state"], "message":job["message"]} if job else {"state":"idle", "message":""}

    def cancel(self, sid, discard=False):
        with self.lock:
            job = self.jobs.get(sid)
            if job:
                job["cancel"].set()
                job["discard"] = bool(discard)

    def wait(self, sid, timeout=5):
        with self.lock:
            job = self.jobs.get(sid)
            thread = job.get("thread") if job else None
        if thread:
            thread.join(timeout)

    def close(self):
        for sid in list(self.jobs): self.cancel(sid)


def diagnostics():
    """Verificação de distribuição: sem rede, ficheiros ou credenciais de contas."""
    from importlib.metadata import version
    from mcp.client.auth import OAuthClientProvider
    from mcp.shared.auth import OAuthClientMetadata
    from mcp_demo import ensure_stdio
    ensure_stdio()
    data = secrets.token_bytes(32); salt = secrets.token_bytes(32)
    assert _protect(_protect(data, salt), salt, True) == data
    OAuthClientMetadata(redirect_uris=["http://127.0.0.1/oauth/callback"], token_endpoint_auth_method="none")
    print(json.dumps({"oauth_sdk":version("mcp"), "dpapi":os.name=="nt", "vault":"dpapi" if os.name=="nt" else "file-0600", "provider":OAuthClientProvider.__name__}), flush=True)
    return 0
