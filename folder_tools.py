"""Ferramentas MCP descobertas em Ferramentas/<nome>/ferramenta.json."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import threading
import zipfile
from pathlib import Path

import requests
import config
from mcp_bridge import MCPManager, validate_server, public_server, redact

REA_VERSION = "6.8.0"
REA_INTEGRITY = "sha512-9QDeRnGqEDzABZyr04eLnBXBv/c6I9/TWu/6M0MD4pEfkySI/BIgwTODIbAReX3C1x6hjw9+Jlx4A2yUSPZ9ww=="
NODE_VERSION = "24.22.1"
NODE_ZIP = "node-v24.22.1-win-x64.zip"
NODE_SHA256 = "d2046d28c2c3dcd211ac5145c0bf30e2047ef9dfb306693c8c6e2eccd8b95fa5"
MANIFEST = "ferramenta.json"
MAX_MANIFEST = 65536


def root():
    return config.application_root() / "Ferramentas"


def roots(cfg):
    result = [root()]
    project = config.active_project(cfg)
    if project and project.get("path"):
        path = Path(project["path"]) / "Ferramentas"
        if path.resolve() != root().resolve():
            result.append(path)
    return result


def ensure_layout():
    folder = root()
    folder.mkdir(parents=True, exist_ok=True)
    readme = folder / "LEIA-ME.md"
    if not readme.exists():
        readme.write_text('''# Ferramentas da app

Cada subpasta pode conter um servidor MCP e um `ferramenta.json` (versão 1).
Copiar apenas um repositório não define como o iniciar: inclui o manifesto.
A app deteta os manifestos nas configurações e antes de usar ferramentas.
Não executa instalações nem scripts de setup de ferramentas desconhecidas.
Com `enabled: true`, o servidor pode arrancar quando o modelo o pesquisar/utilizar.

Exemplo (guarda como `MinhaFerramenta/ferramenta.json` e ajusta os caminhos):
```json
{
  "version": 1,
  "name": "Minha ferramenta",
  "description": "Explica ao modelo para que serve.",
  "enabled": true,
  "approval": "each",
  "server": {
    "transport": "stdio",
    "command": "node",
    "args": ["${tool_dir}/servidor.js"],
    "cwd": "${workspace}",
    "env": {}
  }
}
```
Variáveis de caminhos: `${tool_dir}`, `${app_dir}`, `${workspace}`.
`approval` aceita `each` ou `auto`; as opções da interface têm precedência.
Usa caminhos absolutos para executáveis quando não estiverem no PATH.
Servidores HTTP também são aceites com `transport: http` e `url`.
Não coloques segredos nos argumentos ou na descrição. Campos env/headers de
manifestos são ficheiros locais em texto; a interface oculta os seus valores.
Para scripts CLI sem MCP é necessário um adaptador que exponha as operações.
Skills/instruções por si só não são servidores executáveis.

Também podes usar `Ferramentas` dentro de um projeto: só aparece quando esse
projeto estiver ativo. Esta pasta junto à app disponibiliza ferramentas globais.
Desativar na interface impede novas chamadas; não apaga a pasta.
''', encoding="utf-8")
    return folder


def node_runtime(tools_root):
    """Node das ferramentas: o do núcleo (``_Runtime/node``) ou, em instalações antigas, o que vem dentro do REA."""
    tools_root = Path(tools_root)
    for base in (tools_root / "_Runtime" / "node", tools_root / "REA" / "runtime"):
        found = sorted(base.glob("*/node.exe")) if base.is_dir() else []
        if found:
            return found[0]
    return tools_root / "_Runtime" / "node" / "node.exe"  # ainda por instalar


def _expand(value, variables):
    if isinstance(value, str):
        for key, path in variables.items():
            value = value.replace("${" + key + "}", str(path))
        return value
    if isinstance(value, list):
        return [_expand(v, variables) for v in value]
    if isinstance(value, dict):
        return {k: _expand(v, variables) for k, v in value.items()}
    return value


def scan(cfg):
    """Só lê ficheiros; não inicia processos nem instala dependências."""
    rows = []
    seen = set()
    _meta, workspace = config.resolve_context(cfg)
    overrides = cfg.get("folder_tools") or {}
    for directory in roots(cfg):
        if not directory.is_dir():
            continue
        for child in sorted(directory.iterdir(), key=lambda p: p.name.lower()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            manifest = child / MANIFEST
            if not manifest.is_file():
                continue
            path = str(manifest.resolve())
            if path in seen:
                continue
            seen.add(path)
            sid = "folder_" + hashlib.sha256(os.path.normcase(path).encode()).hexdigest()[:20]
            row = {"id": sid, "name": child.name, "path": str(child.resolve()), "manifest": path, "scope": "global" if directory.resolve() == root().resolve() else "project", "error": "", "enabled": False}
            try:
                if manifest.stat().st_size > MAX_MANIFEST:
                    raise ValueError("O manifesto excede 64 KB.")
                data = json.loads(manifest.read_text(encoding="utf-8-sig"))
                if not isinstance(data, dict) or data.get("version") != 1:
                    raise ValueError("O manifesto deve ter version: 1.")
                raw = data.get("server")
                if not isinstance(raw, dict):
                    raise ValueError("Falta a configuração server MCP.")
                if raw.get("adapter"):
                    adapter=raw["adapter"]
                    if adapter not in ("classrevive","android-skill","bench"):
                        raise ValueError("Adaptador incluído desconhecido.")
                    args=["--reverse-tools-server",adapter,str(child.resolve())] if getattr(sys,"frozen",False) else ["-u",str(Path(__file__).resolve().parent/"reverse_tools_server.py"),adapter,str(child.resolve())]
                    if adapter == "bench":
                        from bench_catalog import runtime
                        raw={**raw,"transport":"stdio","command":str(runtime(directory)),"args":["-u",str(Path(__file__).resolve().parent/"bench_server.py"),str(child.resolve())]}
                    else:
                        raw={**raw,"transport":"stdio","command":sys.executable,"args":args}
                override = overrides.get(sid, {})
                if not isinstance(override, dict):
                    override = {}
                from bench_catalog import runtime as python_runtime
                expanded = _expand(raw, {"tool_dir": child.resolve(), "app_dir": config.application_root(), "workspace": workspace.resolve(),
                                         "node": node_runtime(root()), "python": python_runtime(root()), "path": os.environ.get("PATH", "")})
                if expanded.get("transport", "stdio") == "stdio":
                    cwd = expanded.get("cwd")
                    if isinstance(cwd,str) and cwd and not Path(cwd).is_absolute():
                        expanded["cwd"] = str((child / cwd).resolve())
                    if not cwd:
                        expanded["cwd"] = str(workspace.resolve())
                server = validate_server({**expanded,
                                          "id": sid, "name": data.get("name", child.name),
                                          "enabled": override.get("enabled", data.get("enabled", True)),
                                          "approval": override.get("approval", data.get("approval", "each"))})
                # Paths relativos do executável/cwd são relativos à pasta da ferramenta.
                command = server.get("command", "")
                if command and not Path(command).is_absolute() and ("/" in command or "\\" in command):
                    server["command"] = str((child / command).resolve())
                row.update(name=server["name"], description=str(data.get("description", ""))[:2000],
                           source=str(data.get("source", ""))[:1000], package_version=str(data.get("package_version", ""))[:100],
                           enabled=server["enabled"], approval=server["approval"], server=server)
            except Exception as exc:
                # Não repetir JSON/segredos da configuração em mensagens de erro.
                row["error"] = str(exc) if type(exc) is ValueError else "Não foi possível ler o manifesto."
            rows.append(row)
            if len(rows) >= 100:
                return rows
    return rows


def public_row(row):
    result = {k: v for k, v in row.items() if k != "server"}
    if row.get("server"):
        result["server"] = public_server(row["server"])
    return result


def tool_definitions(rows):
    names = ", ".join(r["name"] for r in rows if r.get("enabled") and not r.get("error"))
    if not names:
        return []
    def tool(name, description, properties=None, required=None):
        return {"type": "function", "function": {"name": name, "description": description,
                "parameters": {"type": "object", "properties": properties or {}, "required": required or []}}}
    text = {"type": "string"}
    return [tool("ferramentas_listar", "Lista as ferramentas locais instaladas e os seus IDs. Disponíveis: " + names[:1500]),
            tool("ferramentas_pesquisar", "Descobre operações de uma ferramenta MCP local e devolve os schemas. Pesquisa antes de executar; usa termos em inglês se necessário. Uma pesquisa vazia lista nomes para descobrir capacidades.", {"id": text, "pesquisa": text}, ["id"]),
            tool("ferramentas_executar", "Executa uma operação local usando o nome e argumentos descobertos por ferramentas_pesquisar. Respeita as aprovações da ferramenta.", {"id": text, "operacao": text, "argumentos": {"type": "object", "additionalProperties": True}}, ["id", "operacao", "argumentos"])]


class FolderTools:
    def __init__(self):
        self.manager = MCPManager()
        self.installer = REAInstaller()

    def close(self):
        self.manager.close()
        self.installer.close()

    def status(self, cfg):
        rows = scan(cfg)
        valid = [row["server"] for row in rows if row.get("server")]
        # Fecha ferramentas desativadas/removidas, sem arrancar nenhuma.
        _meta, workspace = config.resolve_context(cfg)
        self.manager.tools(valid, str(workspace.resolve()), connect=False)
        states = {s["id"]: s for s in self.manager.status(valid)}
        return [{**public_row(row), "state": states.get(row["id"], {})} for row in rows]

    def _connect(self, cfg, sid, test=False):
        rows = scan(cfg)
        row = next((r for r in rows if r["id"] == sid), None)
        if not row or not row.get("server") or row.get("error"):
            raise ValueError("Ferramenta local não encontrada ou manifesto inválido.")
        if not row.get("enabled"):
            raise ValueError("A ferramenta está desativada.")
        _meta, workspace = config.resolve_context(cfg)
        self.manager.tools([row["server"]], str(workspace.resolve()), prune=False, timeout=30 if test else 8, total_timeout=35 if test else 10)
        with self.manager.lock:
            entry = self.manager.entries.get(sid, {})
            if entry.get("error") or not entry.get("client"):
                raise ValueError(entry.get("error") or "Não foi possível ligar a ferramenta.")
            return row, entry["client"], list(entry.get("tools", []))

    def search(self, cfg, sid, query=""):
        row, _client, definitions = self._connect(cfg, sid)
        query = str(query).lower().strip()
        if not query:
            return redact({"id": sid, "total": len(definitions), "operations": [{"name": t["name"], "description": t.get("description", "")[:80]} for t in definitions], "next": "Pesquisa pelo nome/termos para receber os schemas completos."},row["server"])
        terms = query.split()
        scored = []
        for tool in definitions:
            haystack = (tool["name"] + " " + tool.get("description", "")).lower()
            score = sum(term in haystack for term in terms) + (20 if tool["name"].lower() == query else 0)
            if score:
                scored.append((score, tool))
        scored.sort(key=lambda pair: (-pair[0], pair[1]["name"]))
        selected = []
        size = 0
        for _, tool in scored[:8]:
            clean = {k: tool[k] for k in ("name", "description", "inputSchema", "annotations") if k in tool}
            encoded = json.dumps(clean, ensure_ascii=False)
            if size + len(encoded) > 100000:
                break
            size += len(encoded)
            selected.append(clean)
        return redact({"id": sid, "matches": len(scored), "tools": selected, "truncated": len(selected) < len(scored)}, row["server"])

    def execute(self, cfg, sid, name, arguments, approve):
        if not isinstance(arguments, dict):
            raise ValueError("Os argumentos devem ser um objeto JSON.")
        row, client, definitions = self._connect(cfg, sid)
        if name not in {t["name"] for t in definitions}:
            raise ValueError("Operação desconhecida; pesquisa primeiro as ferramentas.")
        server = row["server"]
        if server.get("approval", "each") != "auto" and not approve(server, name, arguments):
            raise PermissionError("Chamada recusada pelo utilizador.")
        # Volta a verificar mudanças de configuração durante a aprovação.
        current = next((r for r in scan(config.load_config()) if r["id"] == sid), None)
        if not current or current.get("server") != server:
            raise ValueError("A ferramenta foi alterada/desativada; volta a pesquisar.")
        with self.manager.lock:
            if self.manager.entries.get(sid, {}).get("client") is not client:
                raise ValueError("A ligação foi alterada; volta a pesquisar.")
        try:
            return client.call(name, arguments)
        except Exception as exc:
            raise RuntimeError(redact(str(exc), server)) from None


class REAInstaller:
    """Instalação confinada à pasta REA, sem registos nos outros agentes."""
    def __init__(self):
        self.lock = threading.RLock()
        self.job = {"state": "idle", "message": ""}
        self.stop = threading.Event()
        self.process = None

    def close(self):
        self.stop.set()
        with self.lock:
            process = self.process
        if process and process.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0), timeout=10)
            else:
                process.terminate()

    def status(self):
        with self.lock:
            return dict(self.job)

    def start(self):
        with self.lock:
            if self.job["state"] == "running":
                return self.status()
            self.stop.clear()
            self.job = {"state": "running", "message": "A preparar REA e Node portátil…"}
            threading.Thread(target=self._run, daemon=True).start()
            return self.status()

    def _message(self, message, state="running"):
        with self.lock:
            self.job.update(state=state, message=message)

    def _run(self):
        try:
            if os.name != "nt" or platform.machine().lower() not in ("amd64", "x86_64"):
                raise ValueError("O instalador portátil REA incluído suporta Windows x64. Noutros sistemas, instala REA e cria o manifesto manualmente.")
            folder = ensure_layout() / "REA"
            folder.mkdir(exist_ok=True)
            manifest = folder / MANIFEST
            # Não substituir instalações/configurações trazidas pelo utilizador.
            if manifest.exists():
                existing = json.loads(manifest.read_text(encoding="utf-8"))
                if existing.get("managed_by") != "studio-rea-installer":
                    raise ValueError("A pasta REA já contém uma ferramenta própria; preservada. Renomeia-a para usar o instalador.")
            runtime = folder / "runtime" / ("node-v" + NODE_VERSION + "-win-x64")
            node = runtime / "node.exe"
            if not node.is_file():
                self._message("A descarregar Node portátil com verificação SHA-256…")
                runtime.parent.mkdir(exist_ok=True)
                archive = runtime.parent / NODE_ZIP
                digest = hashlib.sha256()
                with requests.get("https://nodejs.org/dist/v" + NODE_VERSION + "/" + NODE_ZIP, timeout=(15, 30), stream=True) as response:
                    response.raise_for_status()
                    total = 0
                    with archive.open("wb") as handle:
                        for chunk in response.iter_content(65536):
                            if self.stop.is_set():
                                raise ValueError("Instalação interrompida ao fechar a app.")
                            total += len(chunk)
                            if total > 100 * 1024 * 1024:
                                raise ValueError("O download Node excedeu o limite esperado.")
                            digest.update(chunk)
                            handle.write(chunk)
                if digest.hexdigest() != NODE_SHA256:
                    raise ValueError("A integridade do Node não corresponde à versão fixada.")
                with zipfile.ZipFile(archive) as zipped:
                    for member in zipped.infolist():
                        target = (runtime.parent / member.filename).resolve()
                        if not target.is_relative_to(runtime.parent.resolve()):
                            raise ValueError("Caminho inválido no arquivo Node.")
                    zipped.extractall(runtime.parent)
                archive.unlink()
            self._message("A instalar rea-agents " + REA_VERSION + " e dependências…")
            package = folder / "package"
            package.mkdir(exist_ok=True)
            npm_cli = runtime / "node_modules/npm/bin/npm-cli.js"
            environment = {**os.environ, "PATH": str(runtime) + os.pathsep + os.environ.get("PATH", "")}
            if self.stop.is_set():
                raise ValueError("Instalação interrompida ao fechar a app.")
            process = subprocess.Popen([str(node), str(npm_cli), "install", "--prefix", str(package), "--ignore-scripts", "--omit=optional", "--no-audit", "--no-fund", "rea-agents@" + REA_VERSION],
                                    cwd=str(folder), env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            with self.lock:
                self.process = process
            try:
                process.communicate(timeout=300)
            except subprocess.TimeoutExpired:
                self.close()
                raise ValueError("A instalação npm excedeu cinco minutos.") from None
            finally:
                with self.lock:
                    self.process = None
            if process.returncode:
                raise ValueError("A instalação npm falhou. Confirma a ligação à internet e volta a tentar.")
            lock = json.loads((package / "package-lock.json").read_text(encoding="utf-8"))
            record = lock.get("packages", {}).get("node_modules/rea-agents", {})
            if record.get("version") != REA_VERSION or record.get("integrity") != REA_INTEGRITY:
                raise ValueError("O pacote REA não corresponde à versão/integridade fixada.")
            entry = package / "node_modules/rea-agents/scripts/rea.mjs"
            if not entry.is_file():
                raise ValueError("A instalação não contém o servidor REA.")
            data = {"version": 1, "managed_by": "studio-rea-installer", "name": "REA", "package_version": REA_VERSION,
                    "description": "Reverse Engineer Anything: analisar aplicações, JavaScript/Electron, .NET, capturas HAR e binários. Pesquisa as operações para descobrir capacidades e pré-requisitos. Análise nativa profunda exige um motor externo compatível.",
                    "source": "https://github.com/morluto/rea", "enabled": True, "approval": "each",
                    "server": {"transport": "stdio", "command": "${tool_dir}/runtime/" + runtime.name + "/node.exe",
                               "args": ["${tool_dir}/package/node_modules/rea-agents/scripts/rea.mjs", "mcp"], "cwd": "${workspace}",
                               "env": {"REA_MCP_INPUT_SCHEMA_PROFILE": "compact", "REA_MCP_OUTPUT_SCHEMA_PROFILE": "off"}}}
            # Preservar escolhas locais, incluindo providers configurados em env.
            if manifest.exists():
                old = json.loads(manifest.read_text(encoding="utf-8"))
                for key in ("enabled", "approval"):
                    if key in old:
                        data[key] = old[key]
                data["server"]["env"].update(old.get("server", {}).get("env", {}))
            temporary = manifest.with_suffix(".tmp")
            temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(manifest)
            (folder / "provenance.json").write_text(json.dumps({"source": data["source"], "package": "rea-agents", "version": REA_VERSION, "integrity": REA_INTEGRITY, "node": NODE_VERSION, "node_url": "https://nodejs.org/dist/v" + NODE_VERSION + "/" + NODE_ZIP, "node_sha256": NODE_SHA256, "optional_dependencies": False, "install_scripts": False}, indent=2), encoding="utf-8")
            (folder / "LEIA-ME.md").write_text("# REA na app\n\nInstalação local MIT de https://github.com/morluto/rea.\n\nA licença e os avisos de terceiros estão em package/node_modules/rea-agents/.\nO Node inclui as suas licenças na pasta runtime.\n\nAnálise estática JavaScript/.NET e outras operações incluídas não exigem Ghidra.\nAnálise nativa profunda exige motor compatível (por exemplo Ghidra/JDK existentes);\nconfigura os caminhos em server.env do ferramenta.json, conforme a documentação REA.\nNão foram instalados Ghidra, IDA, Hopper, Frida nem alterados outros agentes.\n\nUsa Configurações → Ferramentas em pastas para testar, ativar/desativar e escolher\naprovações. As operações são descobertas por pesquisa para poupar contexto.\n", encoding="utf-8")
            self._message("REA instalado. Usa Testar para verificar o servidor MCP.", "ready")
        except Exception as exc:
            self._message(str(exc) if type(exc) is ValueError else "Não foi possível instalar REA. Confirma rede e permissões na pasta Ferramentas.", "error")
