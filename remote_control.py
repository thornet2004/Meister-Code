"""Acesso remoto pelo telemóvel: um pequeno servidor HTTP dentro da app, ligado a pedido (``/remote-control``).

Serve uma página web (``web/remote/index.html``) que mostra a conversa ativa, deixa enviar mensagens,
acompanhar a resposta, responder aos cartões de aprovação e mudar de conversa ou de projeto.

Segurança (o agente corre comandos neste PC, por isso quem entrar aqui manda nele):
- o servidor fica desligado por omissão e só existe enquanto o utilizador o ligar; a porta fecha
  quando ele desliga ou a app fecha;
- emparelhamento por código de uso único mostrado na janela da app; cinco códigos errados trocam o
  código e bloqueiam novas tentativas durante um minuto;
- a sessão é um cookie aleatório (HttpOnly, SameSite=Strict), guardado no telemóvel por um ano; os
  dispositivos emparelhados ficam LEMBRADOS neste PC (só a impressão digital do token, em
  ``remote_devices.json``) para não pedirem o código de cada vez — sobrevivem a desligar/ligar e a
  fechar a app, até o utilizador carregar em «Esquecer dispositivos»;
- os pedidos que alteram exigem um
  cabeçalho próprio e a mesma origem, para uma página de terceiros não os conseguir fazer;
- só os endereços listados em ``_GET`` e ``_POST`` existem: não é a ponte inteira da app;
- é HTTP simples, pensado para a rede de casa ou para uma VPN (WireGuard), que é quem cifra o tráfego.
  Não é para expor à internet.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

DEFAULT_PORT = 8765
CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'  # sem 0/O nem 1/I
MAX_BODY = 256 * 1024
MAX_TEXT = 20000
MAX_SESSIONS = 5
MAX_FAILURES = 5
LOCK_SECONDS = 60
TOKEN_TTL = 365 * 24 * 3600  # validade do cookie no telemóvel: um ano
EVENT_LIMIT = 400
POLL_SECONDS = 25
HEADER = 'X-MeisterCode'
COOKIE = 'meistercode_remote'


class Hub:
    """Fila de eventos numerados (texto a chegar, aprovações, mudanças) que os telemóveis leem por espera longa."""

    def __init__(self):
        self.condition = threading.Condition()
        self.events = []
        self.sequence = 0

    def publish(self, kind: str, data=None) -> None:
        with self.condition:
            self.sequence += 1
            self.events.append(dict(seq=self.sequence, kind=kind, data=data))
            del self.events[:-EVENT_LIMIT]
            self.condition.notify_all()

    def wait(self, after: int, timeout: float) -> dict:
        deadline = time.monotonic() + timeout
        with self.condition:
            while self.sequence <= after:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self.condition.wait(remaining)
            rows = [event for event in self.events if event['seq'] > after]
            # o telemóvel ficou tão para trás que há eventos perdidos: tem de recarregar tudo
            lost = bool(self.events) and after < self.events[0]['seq'] - 1 and after != 0
            return dict(events=rows, last=self.sequence, reload=lost)


def addresses(port: int) -> list:
    """Endereços por onde o telemóvel pode chegar a este PC (rede local e VPN), sem contactar ninguém."""
    found = []
    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.append(item[4][0])
    except OSError:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(('10.255.255.255', 1))  # UDP: não envia nada, só escolhe a interface de saída
            found.insert(0, probe.getsockname()[0])
    except OSError:
        pass
    unique = [ip for ip in dict.fromkeys(found) if not ip.startswith(('127.', '169.254.'))]
    return ['http://%s:%d/' % (ip, port) for ip in unique]


def _slim_message(message: dict) -> dict:
    """O que o telemóvel precisa de uma mensagem: texto e um resumo dos passos; nunca ficheiros nem dados binários."""
    steps = []
    for step in (message.get('steps') or [])[-40:]:
        if isinstance(step, dict):
            steps.append(dict(title=str(step.get('title') or step.get('kind') or 'ação')[:200], ok=bool(step.get('ok', True))))
    media = [str(item.get('type') or 'ficheiro') for item in (message.get('media') or []) if isinstance(item, dict)]
    return dict(role=message.get('role', ''), text=str(message.get('text') or '')[:60000], steps=steps, media=media,
                files=[str(item.get('name') or '') for item in (message.get('files') or []) if isinstance(item, dict)][:20],
                error=bool(message.get('error')), created_at=message.get('created_at', ''))


class RemoteControl:
    """Liga e desliga o servidor e faz de ponte, limitada, entre o telemóvel e a ``Api``."""

    def __init__(self, api, page_dir, store_path=None):
        self.api = api
        self.page_dir = Path(page_dir)
        if store_path is None:
            import config
            store_path = config.config_dir() / 'remote_devices.json'
        self.store_path = Path(store_path)
        self.hub = Hub()
        self.lock = threading.RLock()
        self.server = None
        self.thread = None
        self.port = 0
        self.code = ''
        self.sessions = self._load_devices()  # impressão digital do token -> dict(since, address)
        self.failures = 0
        self.locked_until = 0.0
        self.busy = False       # resposta pedida pelo telemóvel
        self.external = False   # resposta pedida na janela da app
        self.stream = ''        # texto da resposta em curso, para quem se liga a meio
        self.approval = None    # cartão de aprovação pendente

    # ------------------------------------------------------------------ ligar / desligar
    def running(self) -> bool:
        return self.server is not None

    def status(self) -> dict:
        with self.lock:
            return dict(running=self.running(), port=self.port, urls=addresses(self.port) if self.running() else [], code=self.code if self.running() else '',
                        devices=[dict(address=item['address'], since=item['since']) for item in self.sessions.values()], max_devices=MAX_SESSIONS,
                        locked=max(0, int(self.locked_until - time.time())))

    def start(self, port: int = DEFAULT_PORT, host: str = '0.0.0.0') -> dict:
        with self.lock:
            if self.running():
                return self.status()
            handler = _handler(self)
            server = None
            for candidate in (port, 0):  # a porta habitual; se estiver ocupada, uma livre
                try:
                    server = ThreadingHTTPServer((host, candidate), handler)
                    break
                except OSError:
                    continue
            if server is None:
                raise OSError('Não foi possível abrir uma porta para o acesso remoto.')
            server.daemon_threads = True
            self.server, self.port = server, server.server_address[1]
            self._new_code()  # código fresco para dispositivos NOVOS; os já lembrados entram pelo cookie
            self.failures, self.locked_until = 0, 0.0
            self.thread = threading.Thread(target=server.serve_forever, kwargs=dict(poll_interval=0.2), daemon=True)
            self.thread.start()
            return self.status()

    def stop(self) -> dict:
        with self.lock:
            server, self.server = self.server, None
            self.code = ''  # os dispositivos lembrados ficam; só a porta fecha
        if server is not None:
            server.shutdown()
            server.server_close()
        self.hub.publish('stopped')
        return self.status()

    close = stop

    def forget_devices(self) -> dict:
        """Esquece todos os dispositivos lembrados: cada um terá de voltar a emparelhar com o código."""
        with self.lock:
            self.sessions.clear()
            if self.running():
                self._new_code()
        self._save_devices()
        self._tell_desktop()
        return self.status()

    def _new_code(self):
        raw = ''.join(secrets.choice(CODE_ALPHABET) for _ in range(8))
        self.code = raw[:4] + '-' + raw[4:]

    # ------------------------------------------------------------------ dispositivos lembrados (disco)
    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256((token or '').encode('utf-8')).hexdigest()

    def _load_devices(self) -> dict:
        try:
            data = json.loads(self.store_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        out = {}
        for key, record in data.items():
            if isinstance(key, str) and isinstance(record, dict):
                out[key] = dict(address=str(record.get('address', '')), since=str(record.get('since', '')))
        return out

    def _save_devices(self):
        try:
            self.store_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.store_path.with_suffix('.tmp')
            temporary.write_text(json.dumps(self.sessions, ensure_ascii=False), encoding='utf-8')
            os.replace(temporary, self.store_path)
        except OSError:
            pass  # não poder gravar não deve derrubar o acesso remoto

    # ------------------------------------------------------------------ emparelhamento e sessões
    def pair(self, code, address: str):
        """Troca o código mostrado na app por uma sessão. Devolve ``(token, erro)``."""
        with self.lock:
            now = time.time()
            if now < self.locked_until:
                return None, 'Demasiadas tentativas. Espera %d segundos e usa o código novo que a app mostra.' % int(self.locked_until - now + 1)
            given = ''.join(ch for ch in str(code or '').upper() if ch.isalnum())
            if not self.code or not hmac.compare_digest(given.encode(), self.code.replace('-', '').encode()):
                self.failures += 1
                if self.failures >= MAX_FAILURES:
                    self.failures, self.locked_until = 0, now + LOCK_SECONDS
                    self._new_code()
                return None, 'Código errado.'
            if len(self.sessions) >= MAX_SESSIONS:
                return None, 'Já há %d dispositivos ligados. Desliga e volta a ligar o acesso remoto na app.' % MAX_SESSIONS
            token = secrets.token_urlsafe(32)
            self.sessions[self._hash(token)] = dict(address=address, since=time.strftime('%H:%M'))
            self.failures = 0
            self._new_code()  # uso único: outro dispositivo precisa do código seguinte
            self._save_devices()  # fica lembrado para não voltar a pedir o código
        self._tell_desktop()
        return token, ''

    def authorised(self, token) -> bool:
        if not token:
            return False
        target = self._hash(token)
        with self.lock:
            return any(hmac.compare_digest(target, known) for known in self.sessions)

    def _tell_desktop(self):
        self.api._stream_js('window.remoteControlChanged && window.remoteControlChanged()')

    # ------------------------------------------------------------------ o que a Api avisa (ver api_chat e api)
    def turn_started(self):
        if not self.busy:  # mensagem escrita na janela da app
            self.external = True
            self.hub.publish('busy', True)

    def turn_finished(self):
        if self.external:
            self.external = False
            self.stream = ''
            self.hub.publish('done', '')

    def stream_start(self):
        self.stream = ''
        self.hub.publish('stream_start')

    def stream_text(self, text: str):
        self.stream += text
        self.hub.publish('stream', text)

    def stream_end(self):
        self.stream = ''
        self.hub.publish('stream_end')

    def approval_asked(self, request: dict):
        self.approval = request
        self.hub.publish('approval', request)

    def approval_done(self, request_id: str):
        if self.approval and self.approval.get('id') == request_id:
            self.approval = None
        self.hub.publish('approval_done', request_id)

    # ------------------------------------------------------------------ pedidos do telemóvel
    def state(self) -> dict:
        full = self.api.get_state()
        if not full.get('ok'):
            return full
        return dict(ok=True, app_version=full.get('app_version', ''), busy=self.busy or self.external, stream=self.stream, approval=self.approval, last=self.hub.sequence,
                    active_project_id=full.get('active_project_id', ''), active_conversation_id=full.get('active_conversation_id', ''),
                    projects=[dict(id=item.get('id', ''), name=item.get('name', '')) for item in full.get('projects', [])],
                    conversations=[dict(id=item.get('id', ''), title=item.get('title') or item.get('name') or 'Conversa') for item in full.get('conversations', [])][:200])

    def conversation(self) -> dict:
        result = self.api.get_conversation()
        if not result.get('ok'):
            return result
        return dict(ok=True, messages=[_slim_message(item) for item in (result.get('messages') or [])[-200:] if isinstance(item, dict)])

    def select(self, body: dict) -> dict:
        if self.busy or self.external:
            return dict(ok=False, error='Espera que a resposta em curso acabe antes de mudar de conversa.')
        kind, ident = body.get('kind'), body.get('id')
        if kind not in ('conversation', 'project') or not isinstance(ident, str) or not ident or len(ident) > 200:
            return dict(ok=False, error='Pedido inválido.')
        result = self.api.set_active_conversation(ident) if kind == 'conversation' else self.api.set_active_project(ident)
        return self._changed(result)

    def new(self, _body: dict) -> dict:
        if self.busy or self.external:
            return dict(ok=False, error='Espera que a resposta em curso acabe.')
        return self._changed(self.api.create_conversation(''))

    def _changed(self, result: dict) -> dict:
        if not result.get('ok'):
            return dict(ok=False, error=result.get('error', 'Falhou.'))
        self.hub.publish('changed')
        self.api._stream_js('window.remoteConversationChanged && window.remoteConversationChanged(true)')
        return dict(ok=True)

    def chat(self, body: dict) -> dict:
        text = body.get('text')
        if not isinstance(text, str) or not text.strip():
            return dict(ok=False, error='Escreve uma mensagem.')
        if len(text) > MAX_TEXT:
            return dict(ok=False, error='Mensagem demasiado longa.')
        with self.lock:
            if self.busy or self.external:
                return dict(ok=False, error='Já há uma resposta em curso.')
            self.busy = True
        threading.Thread(target=self._run_chat, args=(text.strip(),), daemon=True).start()
        return dict(ok=True)

    def _run_chat(self, text: str):
        error = ''
        self.hub.publish('busy', True)
        self.api._stream_js('window.remoteConversationChanged && window.remoteConversationChanged(false, %s)' % json.dumps(text))
        try:
            result = self.api.chat(text, [])
            if not result.get('ok'):
                error = str(result.get('error') or 'Falhou.')
        except Exception as exc:  # noqa: BLE001  (a thread não pode morrer sem avisar o telemóvel)
            error = '%s: %s' % (type(exc).__name__, exc)
        finally:
            self.busy = False
            self.stream = ''
            self.hub.publish('done', error)
            self.api._stream_js('window.remoteConversationChanged && window.remoteConversationChanged(true)')

    def stop_chat(self, _body: dict) -> dict:
        self.api.cancel_chat()
        return dict(ok=True)

    def answer(self, body: dict) -> dict:
        ident, decision = body.get('id'), body.get('decision')
        if not isinstance(ident, str) or decision not in ('allow', 'deny'):
            return dict(ok=False, error='Pedido inválido.')
        if not self.approval or self.approval.get('id') != ident:
            return dict(ok=False, error='Esse pedido de autorização já não está pendente.')
        self.api.respond_approval(ident, decision)
        return dict(ok=True)


def _handler(remote: RemoteControl):
    get = {'/api/state': lambda _q: remote.state(), '/api/conversation': lambda _q: remote.conversation()}
    post = {'/api/select': remote.select, '/api/new': remote.new, '/api/chat': remote.chat, '/api/stop': remote.stop_chat, '/api/approval': remote.answer}

    class Handler(BaseHTTPRequestHandler):
        server_version = 'MeisterCode'
        sys_version = ''
        protocol_version = 'HTTP/1.1'

        def log_message(self, *_args):  # sem registos: os endereços e os pedidos não vão para a consola
            pass

        # ---------------------------------------------------------------- respostas
        def _send(self, status, body: bytes, kind='application/json; charset=utf-8', extra=()):
            self.send_response(status)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            for name, value in extra:
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data, status=200, extra=()):
            self._send(status, json.dumps(data, ensure_ascii=False).encode('utf-8'), extra=extra)

        def _token(self):
            for part in (self.headers.get('Cookie') or '').split(';'):
                name, _, value = part.strip().partition('=')
                if name == COOKIE:
                    return value
            return ''

        def _same_origin(self) -> bool:
            """Pedidos que alteram: têm de vir da nossa página (cabeçalho próprio) e, havendo ``Origin``, da mesma origem."""
            if self.headers.get(HEADER) != '1':
                return False
            origin = self.headers.get('Origin')
            return not origin or urlsplit(origin).netloc == (self.headers.get('Host') or '')

        # ---------------------------------------------------------------- GET
        def do_GET(self):
            if not remote.running():
                return self._json(dict(ok=False, error='O acesso remoto foi desligado.'), 503)
            path = urlsplit(self.path).path
            if path in ('/', '/index.html', '/app.js'):
                name = 'app.js' if path == '/app.js' else 'index.html'
                try:
                    body = (remote.page_dir / name).read_bytes()
                except OSError:
                    return self._json(dict(ok=False, error='Falta a página do acesso remoto.'), 500)
                return self._send(200, body, 'text/javascript; charset=utf-8' if name == 'app.js' else 'text/html; charset=utf-8')
            if not remote.authorised(self._token()):
                return self._json(dict(ok=False, error='Emparelha primeiro este dispositivo.', pair=True), 401)
            if path == '/api/events':
                try:
                    after = int(parse_qs(urlsplit(self.path).query).get('after', ['0'])[0])
                except ValueError:
                    after = 0
                return self._json(dict(ok=True, **remote.hub.wait(max(0, after), POLL_SECONDS)))
            if path in get:
                return self._json(get[path](None))
            self._json(dict(ok=False, error='Não existe.'), 404)

        # ---------------------------------------------------------------- POST
        def do_POST(self):
            # o corpo é sempre lido primeiro: numa ligação reaproveitada, o que ficasse por ler seria tomado pelo pedido seguinte
            try:
                length = int(self.headers.get('Content-Length') or '0')
            except ValueError:
                length = -1
            if length < 0 or length > MAX_BODY:
                self.close_connection = True
                return self._json(dict(ok=False, error='Pedido demasiado grande.'), 413)
            raw = self.rfile.read(length)
            if not remote.running():
                return self._json(dict(ok=False, error='O acesso remoto foi desligado.'), 503)
            path = urlsplit(self.path).path
            if path not in post and path != '/api/pair':
                return self._json(dict(ok=False, error='Não existe.'), 404)
            if not self._same_origin() or (self.headers.get('Content-Type') or '').split(';')[0].strip() != 'application/json':
                return self._json(dict(ok=False, error='Pedido recusado.'), 403)
            try:
                body = json.loads(raw.decode('utf-8') or '{}')
            except (ValueError, UnicodeDecodeError):
                return self._json(dict(ok=False, error='Pedido inválido.'), 400)
            if not isinstance(body, dict):
                return self._json(dict(ok=False, error='Pedido inválido.'), 400)
            if path == '/api/pair':
                token, error = remote.pair(body.get('code'), self.client_address[0])
                if not token:
                    return self._json(dict(ok=False, error=error), 403)
                return self._json(dict(ok=True), extra=[('Set-Cookie', '%s=%s; Path=/; Max-Age=%d; HttpOnly; SameSite=Strict' % (COOKIE, token, TOKEN_TTL))])
            if not remote.authorised(self._token()):
                return self._json(dict(ok=False, error='Emparelha primeiro este dispositivo.', pair=True), 401)
            self._json(post[path](body))

    return Handler
