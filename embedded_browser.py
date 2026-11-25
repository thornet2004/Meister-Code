"""Segundo WebView2, alojado no painel direito da janela principal."""
from urllib.parse import urlsplit
import json
import sys
import time
from pathlib import Path


class EmbeddedBrowser:
    def __init__(self, window):
        self.window = window
        self.control = None
        self.pending_url = "about:blank"
        self.loading = False
        self.error = ""

    def _ui(self, action):
        from System import Action
        result = []
        def run():
            result.append(action())
        self.window.native.Invoke(Action(run))
        return result[0]

    def open(self, url=""):
        def run():
            if self.control is None:
                from Microsoft.Web.WebView2.WinForms import WebView2
                from System.Drawing import Color
                from System.Windows.Forms import DockStyle
                self.control = WebView2()
                self.control.DefaultBackgroundColor = Color.FromArgb(24, 24, 24)
                self.control.Dock = getattr(DockStyle, "None")
                self.control.Visible = False
                self.window.native.Controls.Add(self.control)
                self.control.BringToFront()
                self.window.native.FormClosing += self._closing
                self.control.CoreWebView2InitializationCompleted += self._ready
                self.control.NavigationStarting += self._starting
                self.control.NavigationCompleted += self._completed
                environment = self.window.native.webview.CoreWebView2.Environment
                self.control.EnsureCoreWebView2Async(environment)
            if url:
                self.pending_url = url
                if self.control.CoreWebView2:
                    self.control.CoreWebView2.Navigate(url)
        self._ui(run)

    def _closing(self, sender, event):
        if self.control:
            self.control.Dispose()

    def _ready(self, sender, event):
        if not event.IsSuccess:
            self.error = str(event.InitializationException)
            return
        # Nenhum js_api ou host object é instalado neste WebView.
        self.control.CoreWebView2.NewWindowRequested += self._popup
        self.control.CoreWebView2.Navigate(self.pending_url)

    def _popup(self, sender, event):
        event.Handled = True
        if urlsplit(event.Uri).scheme in ("http", "https"):
            self.control.CoreWebView2.Navigate(event.Uri)

    def _starting(self, sender, event):
        if event.Uri != "about:blank" and urlsplit(event.Uri).scheme not in ("http", "https"):
            event.Cancel = True
            return
        self.loading = True
        self.error = ""

    def _completed(self, sender, event):
        self.loading = False
        self.error = "" if event.IsSuccess else str(event.WebErrorStatus)

    def layout(self, rect):
        def run():
            if self.control is None:
                return
            visible = bool(rect.get("visible"))
            self.control.Visible = visible
            if visible:
                from System.Drawing import Rectangle
                scale = self.window.native.ClientSize.Width / max(1, float(rect["viewport"]))
                values = [int(float(rect[key]) * scale) for key in ("x", "y", "width", "height")]
                self.control.Bounds = Rectangle(values[0], values[1], max(1, values[2]), max(1, values[3]))
                self.control.BringToFront()
        self._ui(run)

    def action(self, action):
        def run():
            core = self.control.CoreWebView2 if self.control else None
            if core is None:
                return
            if action == "back" and core.CanGoBack:
                core.GoBack()
            elif action == "forward" and core.CanGoForward:
                core.GoForward()
            elif action == "reload":
                core.Reload()
        self._ui(run)

    def state(self):
        def run():
            core = self.control.CoreWebView2 if self.control else None
            return {"url": str(core.Source) if core else "", "title": str(core.DocumentTitle) if core else "",
                    "back": bool(core and core.CanGoBack), "forward": bool(core and core.CanGoForward),
                    "loading": self.loading, "error": self.error}
        return self._ui(run)

    def run_after_load(self, script, timeout=20):
        """Espera a página acabar de carregar e corre um script nela (ex.: semear a chave de admin)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            ready = self._ui(lambda: self.control is not None and self.control.CoreWebView2 is not None)
            if ready and not self.loading:
                break
            if self.error:
                raise RuntimeError(self.error)
            time.sleep(0.1)
        else:
            raise TimeoutError("A página demorou demasiado a carregar.")
        return self._script(script)

    def _script(self, script):
        task = self._ui(lambda: self.control.CoreWebView2.ExecuteScriptAsync(script))
        if not task.Wait(10000):
            raise TimeoutError("O browser não respondeu ao comando em 10 segundos.")
        result = json.loads(task.Result)
        if isinstance(result, dict) and result.get("studio_error"):
            raise RuntimeError(result["studio_error"])
        return result

    def _protocol(self, method, arguments):
        task = self._ui(lambda: self.control.CoreWebView2.CallDevToolsProtocolMethodAsync(method, json.dumps(arguments)))
        if not task.Wait(10000):
            raise TimeoutError("A interação com o browser excedeu 10 segundos.")
        return task.Result

    def read(self):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            ready = self._ui(lambda: self.control is not None and self.control.CoreWebView2 is not None)
            if ready and not self.loading:
                break
            if self.error:
                raise RuntimeError(self.error)
            time.sleep(0.1)
        else:
            raise TimeoutError("A página ainda está a carregar. Tenta ler novamente.")
        root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
        self._script((root / "web" / "browser-agent.js").read_text(encoding="utf-8"))
        return self._script("window.__studioBrowserAgent.read()")

    def interact(self, action, ref="", text="", key="", amount=600):
        if action == "click":
            point = self._agent_script("locate", ref)
            self._protocol("Input.dispatchMouseEvent", {"type":"mouseMoved", **point})
            time.sleep(0.05)
            for event in ("mousePressed", "mouseReleased"):
                self._protocol("Input.dispatchMouseEvent", {"type":event, **point, "button":"left", "buttons":1 if event=="mousePressed" else 0, "clickCount":1})
        elif action == "fill":
            self._agent_script("fill", ref, text)
        elif action == "key":
            if ref:
                self._agent_script("focus", ref)
            keys = {"Enter":13,"Tab":9,"Escape":27,"Backspace":8,"Delete":46,"ArrowUp":38,"ArrowDown":40,"ArrowLeft":37,"ArrowRight":39,"Home":36,"End":35}
            if key not in keys:
                raise ValueError("Tecla não suportada: " + key)
            for event in ("keyDown", "keyUp"):
                self._protocol("Input.dispatchKeyEvent", {"type":event,"key":key,"windowsVirtualKeyCode":keys[key],"text":"\r" if key=="Enter" and event=="keyDown" else ""})
        elif action == "scroll":
            self._agent_script("scroll", max(-10000,min(10000,int(amount))))
        else:
            raise ValueError("Ação desconhecida: " + action)
        time.sleep(0.35)
        return self.read()

    def _agent_script(self, method, *args):
        values = ",".join(json.dumps(arg, ensure_ascii=True) for arg in args)
        return self._script("(() => {try {return window.__studioBrowserAgent." + method + "(" + values + ");} catch(e) {return {studio_error:String(e.message || e)};}})()")
