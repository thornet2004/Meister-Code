"""Ensaio real da ponte pywebview, sem mostrar janela e sem tocar na configuração.

Abre uma janela escondida com a classe ``Api`` verdadeira, e o JavaScript chama
``window.pywebview.api.<método>`` para alguns métodos (incluindo os que vêm de
classes-base). Usa pastas temporárias para a configuração e para os dados.

Não faz parte da suite (precisa do WebView2 e demora alguns segundos):
    python tests/bridge_live_smoke.py
"""
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

os.environ['APPDATA'] = tempfile.mkdtemp(prefix='meister-bridge-')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import webview  # noqa: E402

import config  # noqa: E402

# A correr do código-fonte, a raiz dos dados é a pasta do projeto: isolar também
# essa raiz, senão cada ensaio deixa uma pasta de conversa em Conversas/.
_DATA_ROOT = Path(tempfile.mkdtemp(prefix='meister-bridge-dados-'))
config.application_root = lambda: _DATA_ROOT

import api  # noqa: E402

# (método, argumentos) — leituras, e escritas inofensivas na configuração temporária.
CALLS = [
    ('ping', []),
    ('get_mcp_servers', []),
    ('get_mcp_presets', []),
    ('get_folder_tools', []),
    ('mcp_oauth_status', ['inexistente']),
    ('get_state', []),
    ('get_system_diagnostics', []),
    ('get_provider_diagnostics', []),
    ('browser_state', []),
    ('get_tools_inventory', []),
    ('get_conversation', []),
    ('set_model', ['chat', '', '']),  # escreve só na configuração temporária
    ('get_execution_limits', []),
    ('get_command_jobs', []),
    ('get_project_hooks', []),
    ('get_project_validation', []),
    ('get_git_workspace', []),
    ('get_context_usage', []),
    ('search_messages', ['x']),
    ('get_history', []),
    ('get_project_context', []),
    ('get_agent_workspace', []),
    ('get_code_changes', []),
    ('get_chat_recovery', []),
    ('get_semantic_search', []),
    ('get_tool_updates', []),
    ('terminal_read', [0]),
]
# Respostas de erro que são o comportamento certo neste ensaio (dados numa pasta temporária).
EXPECTED_ERRORS = {'get_git_workspace': 'not a git repository'}
result = {'done': False, 'rows': None, 'error': ''}


def drive(window):
    try:
        deadline = time.time() + 40
        script = (
            'window.__bridge = null;'
            '(async () => { const out = [];'
            'for (const [name, args] of ' + json.dumps(CALLS) + ') {'
            ' try { const fn = window.pywebview.api[name];'
            '  if (typeof fn !== "function") { out.push([name, "em falta"]); continue; }'
            '  const r = await fn(...args); out.push([name, r && r.ok === true ? "ok" : "erro: " + JSON.stringify(r).slice(0, 160)]); }'
            ' catch (e) { out.push([name, "excepção: " + e]); } }'
            'window.__bridge = JSON.stringify(out); })();'
        )
        while time.time() < deadline:
            if window.evaluate_js('!!(window.pywebview && window.pywebview.api && window.pywebview.api.ping)'):
                break
            time.sleep(0.3)
        else:
            result['error'] = 'a ponte não ficou disponível'
            return
        window.evaluate_js(script)
        while time.time() < deadline:
            raw = window.evaluate_js('window.__bridge')
            if raw:
                result['rows'] = json.loads(raw)
                return
            time.sleep(0.3)
        result['error'] = 'tempo esgotado à espera das respostas'
    except Exception as exc:  # noqa: BLE001
        result['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        result['done'] = True
        window.destroy()


def main() -> int:
    bridge = api.Api()
    window = webview.create_window('ensaio da ponte', html='<html><body>ensaio</body></html>', js_api=bridge, hidden=True)
    bridge._window = window
    watchdog = threading.Timer(60, lambda: os._exit(3))
    watchdog.daemon = True
    watchdog.start()
    webview.start(drive, window)
    watchdog.cancel()
    if result['error'] or not result['rows']:
        print('FALHOU:', result['error'] or 'sem respostas')
        return 1
    rows = []
    for name, state in result['rows']:
        expected = EXPECTED_ERRORS.get(name)
        if expected and state.startswith('erro:') and expected in state:
            state = 'ok (erro esperado: ' + expected + ')'
        rows.append((name, state))
        print(f'{name}: {state}')
    bad = [row for row in rows if not row[1].startswith('ok')]
    return 1 if bad else 0


if __name__ == '__main__':
    code = main()
    sys.stdout.flush()
    os._exit(code)
