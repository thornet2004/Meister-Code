"""Ensaio real da interface: carrega ``web/index.html`` numa janela pywebview escondida.

Usa a classe ``Api`` verdadeira e o WebView2 verdadeiro, com pastas temporárias
para a configuração e para os dados (não toca nos do utilizador). Confirma que:
  - a página arranca (``init`` corre até ao fim, sem caixa de erro);
  - todas as funções globais do contrato ``tests/js-globals-contract.json``
    existem depois de carregar todos os scripts;
  - o estado e a lista de conversas chegam da ponte;
  - o cartão de aprovação distingue um comando perigoso (sem «permitir nesta sessão»);
  - uma conversa completa: a mensagem aparece logo, a resposta chega por streaming de um
    modelo de ensaio local, e os tokens e o custo ficam na resposta e no total da conversa;
  - a lista de tarefas: a ponte grava, o painel mostra, um clique conclui e o Python atualiza-a em direto;
  - o terminal interativo corre um comando e entrega uma linha a um programa que a pede;
  - a pesquisa por significado indexa e encontra código, com o pedido HTTP verdadeiro a um
    servidor de embeddings local de ensaio (não gasta créditos nem usa a rede externa).

Não faz parte da suite (precisa do WebView2 e demora alguns segundos):
    python tests/ui_live_smoke.py
"""
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ['APPDATA'] = tempfile.mkdtemp(prefix='meister-ui-')
sys.path.insert(0, str(ROOT))

import webview  # noqa: E402

import config  # noqa: E402

_DATA_ROOT = Path(tempfile.mkdtemp(prefix='meister-ui-dados-'))
config.application_root = lambda: _DATA_ROOT

import api  # noqa: E402
from test_code_semantic import fake_vector  # noqa: E402  (vetores de teste, sem modelo verdadeiro)


def start_embeddings_server():
    """Servidor local no formato OpenAI: embeddings com vetores de teste e chat por SSE."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        requests = []
        chats = []

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or b'{}')
            if self.path.endswith('/chat/completions'):
                Handler.chats.append((body.get('model'), bool(body.get('stream')), len(body.get('messages', []))))
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.end_headers()
                for piece in ('Olá! ', 'Resposta do ', 'modelo de ensaio.'):
                    self.wfile.write(('data: ' + json.dumps({'choices': [{'delta': {'content': piece}}]}) + '\n\n').encode())
                    self.wfile.flush()
                done = {'choices': [{'delta': {}, 'finish_reason': 'stop'}], 'usage': {'prompt_tokens': 1000, 'completion_tokens': 500, 'total_tokens': 1500}}
                self.wfile.write(('data: ' + json.dumps(done) + '\n\ndata: [DONE]\n\n').encode())
                return
            Handler.requests.append((self.path, body.get('model'), len(body.get('input', []))))
            payload = json.dumps({'data': [{'index': i, 'embedding': fake_vector(text)} for i, text in enumerate(body.get('input', []))]}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, Handler

CONTRACT = json.loads((ROOT / 'tests' / 'js-globals-contract.json').read_text(encoding='utf-8'))
FUNCTIONS = sorted(name for name, kind in CONTRACT.items() if kind == 'function')
result = {'report': None, 'error': ''}

PROBE = '''
(() => {
  const names = %s;
  const missing = names.filter(name => { try { return typeof eval(name) !== 'function'; } catch (e) { return true; } });
  const box = document.querySelector('#error-box');
  // cartão de aprovação: comando perigoso vs. comando normal
  const card = category => { window.showApproval({id: 'x', category, summary: 's', detail: 'd'});
    const seen = {badge: document.querySelector('#approval-cat').textContent,
                  session: !document.querySelector('#approval-session').classList.contains('hidden'),
                  open: !document.querySelector('#approval-modal').classList.contains('hidden')};
    window.hideApproval(); return seen; };
  const dangerousCard = card('dangerous'), commandCard = card('command'), installCard = card('instalar');
  return JSON.stringify({
    missing,
    dangerousCard,
    commandCard,
    installCard,
    voice: {button: !!document.querySelector('#btn-voice'), title: (document.querySelector('#btn-voice') || {}).title || '',
            microphoneApi: !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia), audioContext: typeof (window.AudioContext || window.webkitAudioContext) === 'function'},
    dangerousOption: document.querySelector('#ag-dangerous') ? document.querySelector('#ag-dangerous').checked : null,
    inited: typeof inited !== 'undefined' && inited === true,
    errorVisible: !!box && !box.classList.contains('hidden'),
    errorText: box ? box.textContent.slice(0, 300) : '',
    providersIsArray: Array.isArray(state.providers),
    conversations: state.conversations.length,
    conversationCards: document.querySelectorAll('#conversations-list [data-act], #conversations-list .conv-card').length,
    version: state.appVersion || '',
    scripts: [...document.scripts].map(s => (s.getAttribute('src') || '').split('/').pop()).filter(Boolean),
  });
})()
''' % json.dumps(FUNCTIONS)


TERMINAL_STATE = "JSON.stringify({text: document.querySelector('#terminal-output').textContent.slice(-400), busy: terminalBusy, cwd: document.querySelector('#terminal-cwd').textContent})"


def terminal_submit(window, text):
    window.evaluate_js('(() => { const i = document.querySelector("#terminal-input"); i.value = %s; '
                       'document.querySelector("#terminal-form").dispatchEvent(new Event("submit", {cancelable: true})); })()' % json.dumps(text))


def terminal_wait(window, condition, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        seen = json.loads(window.evaluate_js(TERMINAL_STATE))
        if condition(seen):
            return seen
        time.sleep(0.2)
    return None


def terminal_round_trip(window):
    """Interface verdadeira -> ponte -> PowerShell verdadeiro: comando, e programa que pede uma linha."""
    if sys.platform != 'win32':
        return {'skipped': True}
    window.evaluate_js('toggleTerminal(true)')
    terminal_submit(window, 'Write-Output (6*7)')
    first = terminal_wait(window, lambda seen: '42' in seen['text'] and not seen['busy'])
    terminal_submit(window, "$n = Read-Host 'nome'; 'ola ' + $n")
    asked = terminal_wait(window, lambda seen: seen['busy'] and 'nome' in seen['text'].split('PS >')[-1])
    terminal_submit(window, 'Rui')
    answered = terminal_wait(window, lambda seen: 'ola Rui' in seen['text'] and not seen['busy'])
    return {'command': bool(first), 'asked': bool(asked), 'answered': bool(answered), 'cwd': (answered or first or {}).get('cwd', '')}


def js(window, script):
    return window.evaluate_js(script)


def tasks_round_trip(window):
    """Lista de tarefas: ponte verdadeira grava, o painel mostra, e um clique na interface conclui a tarefa."""
    def wait(condition, timeout=15):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if js(window, condition):
                return True
            time.sleep(0.2)
        return False

    js(window, "(() => { pywebview.api.update_context_record('task', 'Tarefa de ensaio').then(() => refreshContextUsage()); })()")
    shown = wait("!document.querySelector('#task-plan').classList.contains('hidden') && document.querySelectorAll('#task-plan-list li.open').length === 1")
    summary = js(window, "document.querySelector('#task-plan-summary').textContent")
    js(window, "document.querySelector('#task-plan-list li').click()")
    done = wait("document.querySelectorAll('#task-plan-list li.done').length === 1")
    js(window, "window.showAgentTasks([{id:'x', text:'Empurrada pelo Python', state:'doing'}])")
    pushed = js(window, "document.querySelector('#task-plan-summary').textContent")
    js(window, "refreshContextUsage()")
    restored = wait("document.querySelector('#task-plan-summary').textContent.includes('1/1')")
    return {'shown': shown, 'summary': summary, 'done_by_click': done, 'pushed': pushed, 'restored_from_disk': restored}


def tool_updates_round_trip(window):
    """Painel «Atualizar ferramentas» com a ponte verdadeira: só lista (não instala nada)."""
    js(window, "document.querySelector('#btn-tools').click(); document.querySelector('#tools-update').click();")
    deadline = time.time() + 20
    while time.time() < deadline and not js(window, "document.querySelectorAll('#tool-updates-list .tool-update').length"):
        time.sleep(0.2)
    report = {'rows': js(window, "document.querySelectorAll('#tool-updates-list .tool-update').length"),
              'described': js(window, "document.querySelectorAll('#tool-updates-list .tool-update-description').length"),
              'selectable': js(window, "document.querySelectorAll('#tool-updates-list input:not([disabled])').length"),
              'summary': js(window, "document.querySelector('#tool-updates-summary').textContent"),
              'start_disabled': js(window, "document.querySelector('#tool-updates-start').disabled")}
    js(window, "document.querySelector('#tool-updates-close').click(); document.querySelector('#tools-close').click();")
    return report


def chat_round_trip(window):
    """Conversa real: interface -> ponte -> pedido HTTP com streaming -> mensagem com tokens e custo."""
    def wait(condition, timeout=40):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if js(window, condition):
                return True
            time.sleep(0.2)
        return False

    js(window, "(() => { document.querySelector('#composer').value = 'Olá, isto é um ensaio.'; send(); })()")
    optimistic = wait("[...document.querySelectorAll('.msg.user')].some(n => n.textContent.includes('isto é um ensaio'))", timeout=5)
    answered = wait("[...document.querySelectorAll('.msg.assistant')].some(n => n.textContent.includes('Resposta do modelo de ensaio.')) && !!document.querySelector('.msg-usage')")
    wait("!document.querySelector('#conversation-cost').classList.contains('hidden')", timeout=15)
    return {'user_shown_at_once': optimistic, 'answered': answered,
            'usage': js(window, "(document.querySelector('.msg-usage') || {}).textContent || ''"),
            'conversation_cost': js(window, "document.querySelector('#conversation-cost').textContent"),
            'error': js(window, "document.querySelector('#error-box').classList.contains('hidden') ? '' : document.querySelector('#error-box').textContent.slice(0, 300)")}


def semantic_round_trip(window):
    """Interface verdadeira -> ponte -> pedido HTTP verdadeiro -> índice -> resultados."""
    def wait(condition, timeout=30):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if js(window, condition):
                return True
            time.sleep(0.2)
        return False

    js(window, "document.querySelector('#btn-project-context').click()")
    opened = wait("!document.querySelector('#project-context-modal').classList.contains('hidden') && !!document.querySelector('#semantic-search')")
    js(window, "document.querySelector('#semantic-search').open = true")
    off = wait("document.querySelector('#sem-status').textContent.includes('Ainda sem índice') && document.querySelector('#sem-query').disabled")
    js(window, "(() => { const c = document.querySelector('#sem-enabled'); c.checked = true; c.dispatchEvent(new Event('change')); })()")
    wait("!document.querySelector('#sem-provider').disabled && document.querySelector('#sem-provider').options.length > 1")
    js(window, "(() => { const p = document.querySelector('#sem-provider'); p.value = 'ensaio'; p.dispatchEvent(new Event('change')); })()")
    wait("document.querySelector('#sem-provider').value === 'ensaio'")
    js(window, "(() => { const m = document.querySelector('#sem-model'); m.value = 'modelo-de-ensaio'; m.dispatchEvent(new Event('change')); })()")
    time.sleep(0.5)
    js(window, "document.querySelector('#sem-index').click()")
    indexed = wait("/\\d+ excertos de 2 ficheiros/.test(document.querySelector('#sem-status').textContent)", timeout=40)
    js(window, "(() => { document.querySelector('#sem-query').value = 'onde é feito o login'; document.querySelector('#sem-search').click(); })()")
    found = wait("document.querySelectorAll('#sem-results article').length > 0", timeout=20)
    first = js(window, "(document.querySelector('#sem-results article strong') || {}).textContent || ''")
    status = js(window, "document.querySelector('#sem-status').textContent")
    js(window, "document.querySelector('#project-context-modal').classList.add('hidden')")
    return {'opened': opened, 'off_by_default': off, 'indexed': indexed, 'found': found, 'first': first, 'status': status}


def remote_round_trip(window):
    """Acesso remoto com a Api e a janela verdadeiras: um «telemóvel» (pedidos HTTP) emparelha, envia e recebe a resposta.

    O servidor é aberto só em 127.0.0.1, para o ensaio não fazer o Windows perguntar pela firewall.
    """
    import requests

    def wait(condition, timeout=20):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if js(window, condition):
                return True
            time.sleep(0.2)
        return False

    info = BRIDGE._remote_server().start(0, '127.0.0.1')
    base = 'http://127.0.0.1:%d' % info['port']
    headers = {'X-MeisterCode': '1', 'Content-Type': 'application/json'}
    js(window, "window.openRemoteControl()")
    shown = wait("document.querySelector('#remote-code').textContent === %s && !document.querySelector('#remote-details').classList.contains('hidden')" % json.dumps(info['code']))
    phone = requests.Session()
    refused = phone.get(base + '/api/state', timeout=10).status_code
    paired = phone.post(base + '/api/pair', data=json.dumps({'code': info['code']}), headers=headers, timeout=10).json().get('ok')
    device_listed = wait("document.querySelector('#remote-devices').textContent.includes('127.0.0.1')", timeout=10)
    state = phone.get(base + '/api/state', timeout=10).json()
    before = len(phone.get(base + '/api/conversation', timeout=10).json()['messages'])
    sent = phone.post(base + '/api/chat', data=json.dumps({'text': 'Mensagem do telemóvel.'}), headers=headers, timeout=10).json()
    kinds, streamed, after, deadline = [], '', state.get('last', 0), time.time() + 60
    while time.time() < deadline and 'done' not in kinds:
        data = phone.get(base + '/api/events?after=%d' % after, timeout=40).json()
        after = data['last']
        for event in data['events']:
            kinds.append(event['kind'])
            if event['kind'] == 'stream':
                streamed += event['data']
    messages = phone.get(base + '/api/conversation', timeout=10).json()['messages']
    desktop = wait("[...document.querySelectorAll('.msg.user')].some(n => n.textContent.includes('Mensagem do telemóvel.')) && !document.querySelector('.streaming-msg')")
    js(window, "document.querySelector('#remote-stop').click()")
    stopped = wait("document.querySelector('#remote-status').textContent === 'Desligado.'", timeout=10)
    try:
        after_stop = requests.get(base + '/api/state', timeout=3).status_code
    except requests.RequestException:
        after_stop = 'sem ligação'
    js(window, "document.querySelector('#remote-close').click()")
    return {'code_shown': shown, 'refused_before_pairing': refused, 'paired': paired, 'device_listed': device_listed, 'conversations': len(state.get('conversations', [])),
            'sent': sent.get('ok'), 'events': sorted(set(kinds)), 'streamed': streamed, 'new_messages': len(messages) - before, 'answer': messages[-1]['text'] if messages else '',
            'desktop_updated': desktop, 'stopped': stopped, 'after_stop': after_stop}


def voice_bridge(window):
    """Pergunta à ponte verdadeira se o ditado está pronto. Não liga o microfone."""
    js(window, "window.__voz = ''; pywebview.api.get_voice_input().then(r => { window.__voz = JSON.stringify(r); });")
    deadline = time.time() + 10
    while time.time() < deadline and not js(window, 'window.__voz'):
        time.sleep(0.2)
    return json.loads(js(window, 'window.__voz') or '{}')


BRIDGE = None


def drive(window):
    try:
        deadline = time.time() + 45
        while time.time() < deadline:
            ready = window.evaluate_js("typeof inited !== 'undefined' && inited === true && Array.isArray(state.conversations) && state.conversations.length > 0")
            if ready:
                break
            time.sleep(0.4)
        time.sleep(1.0)  # deixar acabar os pedidos de arranque
        result['report'] = json.loads(window.evaluate_js(PROBE))
        result['report']['chat'] = chat_round_trip(window)
        result['report']['tasks'] = tasks_round_trip(window)
        result['report']['tool_updates'] = tool_updates_round_trip(window)
        result['report']['terminal'] = terminal_round_trip(window)
        result['report']['semantic'] = semantic_round_trip(window)
        result['report']['voice_bridge'] = voice_bridge(window)
        result['report']['remote'] = remote_round_trip(window)
    except Exception as exc:  # noqa: BLE001
        result['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        window.destroy()


def main() -> int:
    server, handler = start_embeddings_server()
    global BRIDGE
    bridge = api.Api()
    BRIDGE = bridge
    bridge.get_state()  # cria a conversa ativa nas pastas temporárias
    cfg = config.load_config()
    cfg['providers'] = [{'id': 'ensaio', 'name': 'Servidor de ensaio', 'kind': 'openai-compatible',
                         'base_url': 'http://127.0.0.1:' + str(server.server_address[1]) + '/v1', 'api_key': '',
                         'models': [{'id': 'chat-de-ensaio', 'name': 'Chat de ensaio', 'type': 'chat'}],
                         'catalog': [{'id': 'chat-de-ensaio', 'categories': ['chat'], 'pricing': {'prompt': '0.000001', 'completion': '0.000002'}}]}]
    cfg['chat'] = {'provider_id': 'ensaio', 'model_id': 'chat-de-ensaio'}
    config.save_config(cfg)
    _meta, workspace = config.resolve_context(config.load_config())
    (workspace / 'auth.py').write_text('def verificar_senha(utilizador, senha):\n    """Autenticar o utilizador com a password guardada."""\n    return comparar(utilizador, senha)\n', encoding='utf-8')
    (workspace / 'billing.py').write_text('def emitir(cliente, total):\n    """Cria a fatura e regista o pagamento do cliente."""\n    return gravar(cliente, total)\n', encoding='utf-8')
    window = webview.create_window('ensaio da interface', url=str(ROOT / 'web' / 'index.html'), js_api=bridge, hidden=True, width=1200, height=820)
    bridge._window = window
    watchdog = threading.Timer(240, lambda: os._exit(3))
    watchdog.daemon = True
    watchdog.start()
    webview.start(drive, window)
    watchdog.cancel()
    report = result['report']
    if result['error'] or not report:
        print('FALHOU:', result['error'] or 'sem relatório')
        return 1
    print('scripts carregados:', len(report['scripts']))
    print('funções globais verificadas:', len(FUNCTIONS), '| em falta:', report['missing'])
    print('init concluído:', report['inited'], '| caixa de erro visível:', report['errorVisible'], report['errorText'])
    print('estado da ponte: provedores é lista:', report['providersIsArray'], '| conversas:', report['conversations'])
    print('cartão de comando perigoso:', report['dangerousCard'], '| cartão de comando normal:', report['commandCard'], '| opção ligada:', report['dangerousOption'])
    cards = (report['dangerousCard'] == {'badge': 'perigoso', 'session': False, 'open': True}
             and report['commandCard'] == {'badge': 'comando', 'session': True, 'open': True}
             and report['installCard'] == {'badge': 'instalar ferramenta', 'session': False, 'open': True}
             and report['dangerousOption'] is True)
    terminal = report.get('terminal') or {}
    print('terminal interativo (PowerShell verdadeiro):', terminal)
    terminal_ok = terminal.get('skipped') or (terminal.get('command') and terminal.get('asked') and terminal.get('answered'))
    chat = report.get('chat') or {}
    print('conversa real (modelo de ensaio local, com streaming):', chat, '| pedidos de chat:', handler.chats)
    chat_ok = (chat.get('user_shown_at_once') and chat.get('answered') and not chat.get('error')
               and chat.get('usage') == '≈1,5k tokens · ≈US$ 0,0020' and chat.get('conversation_cost') == '≈US$ 0,0020'
               and handler.chats and handler.chats[0][0] == 'chat-de-ensaio' and handler.chats[0][1] is True)
    tasks = report.get('tasks') or {}
    print('lista de tarefas (ponte verdadeira):', tasks)
    tasks_ok = (tasks.get('shown') and tasks.get('summary') == '📋 Tarefas 0/1' and tasks.get('done_by_click')
                and tasks.get('pushed') == '📋 Tarefas 0/1 · em curso: Empurrada pelo Python' and tasks.get('restored_from_disk'))
    updates = report.get('tool_updates') or {}
    print('painel Atualizar ferramentas (ponte verdadeira, só leitura):', updates)
    updates_ok = updates.get('rows') == 45 and updates.get('described') == 45 and updates.get('selectable', 0) >= 1 and updates.get('start_disabled') is True and 'por instalar' in (updates.get('summary') or '')
    semantic = report.get('semantic') or {}
    print('pesquisa por significado (HTTP verdadeiro, modelo de ensaio):', semantic, '| pedidos ao servidor:', handler.requests)
    semantic_ok = (semantic.get('off_by_default') and semantic.get('indexed') and semantic.get('found') and semantic.get('first', '').startswith('auth.py')
                   and all(path == '/v1/embeddings' and model == 'modelo-de-ensaio' for path, model, _count in handler.requests) and len(handler.requests) >= 2)
    voice = report.get('voice') or {}
    voice['bridge'] = report.get('voice_bridge') or {}
    print('ditado por voz (janela verdadeira, sem ligar o microfone):', voice)
    voice_ok = voice.get('button') and voice.get('microphoneApi') and voice.get('audioContext') and voice['bridge'].get('ok') and voice['bridge'].get('ready') is False
    remote = report.get('remote') or {}
    print('acesso remoto (Api e janela verdadeiras, telemóvel por HTTP):', remote)
    remote_ok = (remote.get('code_shown') and remote.get('refused_before_pairing') == 401 and remote.get('paired') and remote.get('device_listed') and remote.get('sent')
                 and {'busy', 'stream', 'done'} <= set(remote.get('events', [])) and remote.get('streamed', '').endswith('Resposta do modelo de ensaio.') and remote.get('streamed') == remote.get('answer') and remote.get('new_messages') == 2
                 and remote.get('desktop_updated') and remote.get('stopped') and remote.get('after_stop') in (503, 'sem ligação'))
    ok = remote_ok and voice_ok and chat_ok and tasks_ok and updates_ok and semantic_ok and terminal_ok and cards and report['inited'] and not report['missing'] and not report['errorVisible'] and report['providersIsArray'] and report['conversations'] >= 1
    print('RESULTADO:', 'ok' if ok else 'FALHOU')
    return 0 if ok else 1


if __name__ == '__main__':
    code = main()
    sys.stdout.flush()
    os._exit(code)
