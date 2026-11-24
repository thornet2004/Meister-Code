"""Servidor MCP mínimo usando o SDK oficial instalado no ambiente."""
from mcp.server.fastmcp import FastMCP

server = FastMCP("Official SDK smoke")


@server.tool()
def sdk_echo(texto: str) -> str:
    return "SDK: " + texto


if __name__ == "__main__":
    server.run(transport="stdio")
