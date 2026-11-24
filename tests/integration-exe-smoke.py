"""Verifica o exe com HTTP e handshakes SQL locais, sem contas ou bases reais."""
import socket
import struct
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integration_services import SettingsStore
from mcp_bridge import MCPClient, validate_server
from PyInstaller.archive.readers import CArchiveReader


class Page(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"<h1>Packaged Fetch OK</h1>")

    def log_message(self, *args):
        pass


def sql_fixture(kind, seen):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(20)
    port = listener.getsockname()[1]

    def serve():
        try:
            with listener.accept()[0] as client:
                client.settimeout(10)
                if kind == "mysql":
                    capabilities = 0x00000200 | 0x00008000 | 0x00080000 | 0x00000008
                    payload = (b"\x0a8.0.36\0" + struct.pack("<I", 1) + b"12345678\0" +
                               struct.pack("<H", capabilities & 65535) + b"\x2d" + struct.pack("<H", 2) +
                               struct.pack("<H", capabilities >> 16) + b"\x15" + b"\0" * 10 +
                               b"abcdefghijkl\0mysql_native_password\0")
                    client.sendall(len(payload).to_bytes(3, "little") + b"\0" + payload)
                # Receber o arranque/autenticação prova que o driver foi importado e executado.
                seen.append(bool(client.recv(8192)))
                # Sem base real: fechar antes de executar qualquer SQL.
        finally:
            listener.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return port, thread


exe = Path("dist/Studio de Media.exe").resolve()
archive = CArchiveReader(str(exe))
pyz = archive.open_embedded_archive(next(name for name, item in archive.toc.items() if item[-1] == "z"))
for module in ("integration_server", "integration_services", "pg8000.core", "pymysql", "scramp"):
    assert module in pyz.toc, module
for name in ("pg8000", "scramp", "pymysql"):
    assert any(name in path.lower() and path.lower().endswith("dist-info/metadata") for path in (p.replace("\\", "/") for p in archive.toc)), name

with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temporary:
    root = Path(temporary).resolve()
    http = ThreadingHTTPServer(("127.0.0.1", 0), Page)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    try:
        for kind in ("fetch", "brave", "postgres", "mysql", "discord"):
            seen = []
            sql_thread = None
            if kind in ("postgres", "mysql"):
                port, sql_thread = sql_fixture(kind, seen)
                SettingsStore(kind, root).write({"host": "127.0.0.1", "port": str(port), "database": "probe", "user": "probe", "password": "probe", "tls": "false", "readonly": "true"})
            server = validate_server({"id": "exe-" + kind, "name": kind, "command": str(exe), "args": ["--integration-server", kind, str(root)], "transport": "stdio"})
            client = MCPClient(server, str(root))
            try:
                definitions = client.connect()
                assert any(t["name"] == "connection_test" for t in definitions), kind
                if kind == "fetch":
                    result = client.call("fetch_url", {"url": "http://127.0.0.1:" + str(http.server_port)})
                    assert not result["isError"] and "Packaged Fetch OK" in result["content"][0]["text"], result
                elif sql_thread:
                    result = client.call("connection_test", {})
                    assert result["isError"], "O fixture não é uma base real."
                    sql_thread.join(5)
                    assert seen == [True], (kind, seen, result)
            finally:
                client.close()
        print("PASS: exe contém drivers/metadados; cinco conectores MCP; Fetch HTTP real; drivers PostgreSQL/MySQL executam handshakes locais.")
    finally:
        http.shutdown()
        http.server_close()
        thread.join(2)
