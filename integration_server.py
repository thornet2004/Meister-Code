"""Servidor MCP stdio incluído no executável, sem processos Node adicionais."""
import json
import sys

from integration_services import SettingsStore, KINDS, tools, safe_execute
from mcp_demo import ensure_stdio


def main(kind, root):
    if kind not in KINDS:
        return 2
    ensure_stdio()
    for line in sys.stdin:
        try:
            message = json.loads(line)
            if "id" not in message:
                continue
            method = message.get("method")
            settings = SettingsStore(kind, root).read()
            if method == "server/discover":
                result = {"resultType": "complete", "supportedVersions": ["2026-07-28"], "capabilities": {"tools": {}}, "_meta": {"io.modelcontextprotocol/serverInfo": {"name": "studio-" + kind, "version": "1.0"}}}
            elif method == "initialize":
                result = {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}}, "serverInfo": {"name": "studio-" + kind, "version": "1.0"}}
            elif method == "tools/list":
                result = {"tools": tools(kind, settings)}
            elif method == "tools/call":
                params = message.get("params", {})
                result = safe_execute(kind, params.get("name"), params.get("arguments") or {}, settings)
            else:
                print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32601, "message": "Method not found"}}), flush=True)
                continue
            print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}), flush=True)
        except Exception:
            # Nunca imprimir credenciais ou exceções no stdout do protocolo.
            if "message" in locals() and isinstance(message, dict) and "id" in message:
                print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32602, "message": "Configuração ou pedido inválido."}}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
