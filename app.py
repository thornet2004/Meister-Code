"""Arranque da app: cria a janela pywebview e liga a classe Api (js_api).

Correr com:  python app.py

Usa o WebView2 já incluído no Windows (ou o motor nativo do SO em Linux/Mac).
Não há servidor HTTP: o frontend fala com o Python pelo bridge do pywebview.
"""

from __future__ import annotations

import sys
from pathlib import Path

import webview
from app_version import APP_NAME

from api import Api


def _base_dir() -> Path:
    """Pasta base dos recursos (web/), compatível com o PyInstaller.

    - Normal: a pasta deste ficheiro.
    - Empacotado (.exe): a pasta de extração do PyInstaller (``sys._MEIPASS``).
    """
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent


def _local_temp(clean: bool = False) -> None:
    """Na versão que vive na sua pasta (marcador ``meistercode-portable.json``), os temporários ficam em ``<app>/Temp``.

    Sem isto, o WebView2, o ditado e os programas lançados pela app escreviam no ``%TEMP%`` do Windows.
    A correr do código ou sem o marcador, nada muda. ``clean`` apaga o que tenha mais de um dia (só a janela principal o pede).
    """
    if not getattr(sys, "frozen", False):
        return
    import os
    import shutil
    import tempfile
    import time

    import config
    root = config.portable_root()
    if root is None:
        return
    folder = root / "Temp"
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    os.environ["TEMP"] = os.environ["TMP"] = str(folder)
    tempfile.tempdir = str(folder)
    if clean:
        limit = time.time() - 86400
        for item in folder.iterdir():
            try:
                if item.stat().st_mtime < limit:
                    shutil.rmtree(item, ignore_errors=True) if item.is_dir() else item.unlink()
            except OSError:
                pass


WEB_DIR = _base_dir() / "web"
INDEX = WEB_DIR / "index.html"


def main() -> int:
    _local_temp(clean=not any(arg.startswith('--') for arg in sys.argv[1:]))
    if '--build-info' in sys.argv:
        import json
        from app_version import VERSION
        from coding_tools import atomic
        index=sys.argv.index('--build-info');atomic(Path(sys.argv[index+1]),json.dumps(dict(version=VERSION,name=APP_NAME)).encode());return 0
    if '--system-diagnostics' in sys.argv:
        import json
        from system_diagnostics import report
        from coding_tools import atomic
        index=sys.argv.index('--system-diagnostics');atomic(Path(sys.argv[index+1]),json.dumps(report(),ensure_ascii=False,indent=2).encode());return 0
    if "--reverse-tools-helper" in sys.argv:
        from reverse_tools_server import helper
        return helper(sys.argv[sys.argv.index("--reverse-tools-helper")+1])
    if "--reverse-tools-server" in sys.argv:
        from reverse_tools_server import main as reverse_main
        index=sys.argv.index("--reverse-tools-server")
        return reverse_main(sys.argv[index+1],sys.argv[index+2])
    if "--integration-server" in sys.argv:
        from integration_server import main as integration_main
        index = sys.argv.index("--integration-server")
        return integration_main(sys.argv[index + 1], sys.argv[index + 2])
    if "--mcp-demo-server" in sys.argv:
        from mcp_demo import main as demo_main
        return demo_main()
    if "--oauth-diagnostics" in sys.argv:
        from mcp_oauth import diagnostics
        return diagnostics()
    if not INDEX.exists():
        print(f"ERRO: não encontrei {INDEX}", file=sys.stderr)
        return 1

    from integration_catalog import ensure_fetch
    ensure_fetch()
    from folder_tools import ensure_layout
    ensure_layout()
    api = Api()
    # Installer refuses to replace files while any desktop instance is open.
    mutex=None
    if sys.platform=='win32':
        import ctypes
        from app_version import APP_MUTEX
        ctypes.windll.kernel32.CreateMutexW.restype=ctypes.c_void_p
        mutex=ctypes.windll.kernel32.CreateMutexW(None,False,APP_MUTEX)
    window = webview.create_window(
        APP_NAME,
        url=str(INDEX),
        js_api=api,
        width=1200,
        height=820,
        min_size=(900, 640),
        text_select=True,
    )
    # Dá à Api acesso à janela (diálogos nativos de pasta).
    api._window = window
    window.events.closed += api.cancel_chat
    window.events.closed += api._tasks.close
    window.events.closed += api._validations.close
    window.events.closed += api._commands.close
    window.events.closed += api._terminal.close
    window.events.closed += api._mcp.close
    window.events.closed += api._folder_tools.close
    window.events.closed += api._lsp.close
    window.events.closed += api._oauth.close
    window.events.closed += api._provider_tests.close
    # o instalador das ferramentas só existe depois de o painel ser aberto; fechar a janela pára-o e mata o npm/pip em curso
    window.events.closed += lambda: getattr(api, '_tool_installer', None) and api._tool_installer.close()
    window.events.closed += lambda: getattr(api, '_remote_control', None) and api._remote_control.close()

    # debug=True abre as devtools do WebView; útil enquanto se desenvolve.
    webview.start(debug=False,icon=str(WEB_DIR/'assets/meistercode.ico'))
    if mutex:ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(mutex))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
