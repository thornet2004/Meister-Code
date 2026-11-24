"""Teste nativo sem usar configuração pessoal nem serviços externos."""
import sys
import tempfile
import threading
import time
import json
from urllib.parse import parse_qs, urlsplit
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import webview
import api
import config


class Page(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        value=parse_qs(urlsplit(self.path).query).get('nome',[''])[0]
        html='''<!doctype html><title>Browser test</title><h1>Browser local</h1>
        <form><label>Nome<input name="nome" /></label><button type="button" onclick="document.getElementById('result').textContent='Clicado: '+document.querySelector('input').value">Mostrar</button><button>Enviar</button></form>
        <p id="result"></p><p>Recebido: '''+escape(value)+'''</p>'''
        self.wfile.write(html.encode('utf-8'))

    def log_message(self, *args):
        pass


with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as data_dir:
    config.config_dir = lambda: Path(data_dir)
    config.application_root = lambda: Path(data_dir) / "app"
    server = ThreadingHTTPServer(("127.0.0.1", 0), Page)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    backend = api.Api()
    window = webview.create_window("Teste Studio", str(Path("web/index.html").resolve()), js_api=backend, hidden=True)
    backend._window = window
    failures = []

    def smoke():
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if window.evaluate_js("Boolean(window.pywebview && window.pywebview.api && document.querySelector('#btn-terminal'))"):
                    break
                time.sleep(0.1)
            window.evaluate_js("window.pywebview.api.terminal_execute('Write-Output 42').then(r => {window.smokeTerminal = r;})")
            while time.monotonic() < deadline:
                result = window.evaluate_js("window.smokeTerminal || null")
                if result:
                    assert result["ok"] and "42" in result["output"], result
                    break
                time.sleep(0.1)
            else:
                raise AssertionError("Bridge terminal timeout")
            result = backend.open_browser()
            assert result["ok"], result
            window.evaluate_js("openBrowser(); true")
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if backend._browser and backend._browser.control:
                    break
                time.sleep(0.1)
            url = f"http://127.0.0.1:{server.server_port}"
            result = backend.open_browser(url)
            assert result["ok"], result
            window.evaluate_js(f"document.querySelector('#browser-url').value = '{url}'; navigateBrowser()")
            state = {}
            while time.monotonic() < deadline:
                state = backend.browser_state()
                if state.get("title") == "Browser test" and window.evaluate_js("browserNavigated"):
                    break
                time.sleep(0.1)
            else:
                raise AssertionError(f"Browser embedded timeout: {state}")
            assert len(webview.windows) == 1, "Must not create another window"
            window.evaluate_js("syncBrowserBounds(); true")
            time.sleep(0.5)
            def verify_native():
                control = backend._browser.control
                assert control.Parent == window.native
                assert control.Visible == window.native.Visible
                assert control.Bounds.Width > 100, str(control.Bounds)
                assert control.Bounds.X > 300
            backend._browser._ui(verify_native)
            task = backend._browser._ui(lambda: backend._browser.control.CoreWebView2.ExecuteScriptAsync("Boolean(window.pywebview)"))
            assert task.Result == "false", "Remote page must not receive a Python bridge"
            assert backend.open_browser(url + "/next")["ok"]
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                state = backend.browser_state()
                if state.get("url", "").endswith("/next") and state.get("back"):
                    break
                time.sleep(0.1)
            else:
                raise AssertionError("Navigation history unavailable")
            assert backend.browser_action("back")["ok"]
            while time.monotonic() < deadline:
                if backend.browser_state().get("url") == url + "/":
                    break
                time.sleep(0.1)
            else:
                raise AssertionError("Back navigation did not return to first page")
            steps=[]
            backend._ask_approval=lambda *args: (_ for _ in ()).throw(AssertionError('Browser must not ask for approval'))
            def tool(name, **args):
                result=json.loads(backend._dispatch_browser_tool(name,args,steps))
                assert 'error' not in result,result
                return result
            page=tool('browser_ler')
            field=next(e['ref'] for e in page['elements'] if e['tag']=='input')
            page=tool('browser_escrever',ref=field,texto='Olá browser')
            button=next(e['ref'] for e in page['elements'] if e['label']=='Mostrar')
            page=tool('browser_clicar',ref=button)
            if 'Clicado: Olá browser' not in page['text']:
                button=next(e['ref'] for e in page['elements'] if e['label']=='Mostrar')
                page=tool('browser_clicar',ref=button)
            assert 'Clicado: Olá browser' in page['text'],page
            field=next(e['ref'] for e in page['elements'] if e['tag']=='input')
            page=tool('browser_tecla',ref=field,tecla='Enter')
            assert 'Recebido: Olá browser' in page['text'],page
            assert len(steps)==4 and all(step['ok'] for step in steps)
            assert backend.add_mcp_demo()["ok"]
            catalogue=backend.get_tool_catalog()
            alias=next(t["name"] for t in catalogue["tools"] if t["name"].endswith("_demo_echo"))
            cfg=config.load_config();meta,output=config.resolve_context(cfg)
            result=json.loads(backend._handle_tool(cfg,{"name":alias,"arguments":{"texto":"MCP nativo"}},[],steps,backend._agent_context(cfg),meta,output))
            assert result["structuredContent"]["texto"]=="MCP nativo",result
            window.evaluate_js("refreshToolCatalog(); true")
            time.sleep(0.3)
            assert "Demonstração local" in window.evaluate_js("document.querySelector('#mcp-servers').textContent")
            window.evaluate_js("closeBrowser()")
            time.sleep(0.2)
            assert not backend._browser._ui(lambda: backend._browser.control.Visible)
            print("PASS: native browser read/fill/trusted click/Enter submission without approvals; one window, no remote bridge, real PowerShell, real MCP through native catalogue", flush=True)
        except Exception:
            import traceback
            failures.append(traceback.format_exc())
        finally:
            backend._terminal.close()
            backend._mcp.close()
            window.destroy()

    webview.start(smoke, gui="edgechromium")
    server.shutdown()
    if failures:
        raise AssertionError(failures)
