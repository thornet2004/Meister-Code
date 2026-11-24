"""Presets MCP: serviços incluídos, remotos por OAuth e componentes Node locais.

Os serviços incluídos são implementados em ``integration_services.py``. Cada
preset produz uma configuração compatível com ``mcp_bridge.py``. Fetch é
ativado uma vez; os restantes exigem configuração. Os componentes Node são instalados
com npm em ``.integrations/node`` quando a pasta da aplicação é gravável; caso
contrário, ficam na pasta de configuração do utilizador.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import config

PROFILES = {
    "all": "Todas as áreas",
    "coding": "Programação",
    "research": "Pesquisa",
    "work": "Trabalho e comunicação",
}

CATALOG = {
    "github": dict(
        name="GitHub",
        mode="remote",
        url="https://api.githubcopilot.com/mcp/",
        profiles=["coding", "work"],
        description="Repositórios, issues e pull requests.",
        source="https://github.com/github/github-mcp-server",
        help="O OAuth remoto pode exigir um Client ID próprio. Também podes usar um PAT no modo manual.",
    ),
    "linear": dict(
        name="Linear",
        mode="remote",
        url="https://mcp.linear.app/mcp",
        profiles=["coding", "work"],
        description="Issues, projetos e tarefas no Linear.",
        source="https://linear.app/docs/mcp",
    ),
    "linear_read": dict(
        name="Linear (só leitura)",
        mode="remote",
        url="https://mcp.linear.app/mcp/readonly",
        profiles=["coding", "work"],
        description="Consulta issues e projetos do Linear, sem ferramentas de escrita.",
        source="https://linear.app/docs/mcp",
    ),
    "jira": dict(
        name="Jira / Confluence",
        mode="remote",
        url="https://mcp.atlassian.com/v2/mcp",
        profiles=["coding", "work"],
        description="Tarefas e documentação da Atlassian.",
        source="https://support.atlassian.com/atlassian-ai-gateway/docs/get-started-with-the-atlassian-remote-mcp-server",
        help="Usa OAuth ou, no modo manual, um cabeçalho Authorization: Basic com email:API token.",
    ),
    "slack": dict(
        name="Slack",
        mode="remote",
        url="https://mcp.slack.com/mcp",
        profiles=["work"],
        description="Pesquisa, canais, conversas e ações autorizadas no Slack.",
        source="https://docs.slack.dev/ai/slack-mcp-server/",
        help="O Slack exige uma app registada, Client ID/secret e aprovação do workspace; não permite registo dinâmico.",
    ),
    "notion": dict(
        name="Notion",
        mode="remote",
        url="https://mcp.notion.com/mcp",
        profiles=["research", "work"],
        description="Pesquisar e trabalhar com páginas e bases do Notion.",
        source="https://developers.notion.com/guides/mcp",
    ),
    "playwright": dict(
        name="Playwright",
        mode="node",
        package="@playwright/mcp",
        version="0.0.84",
        entry="cli.js",
        args=["--headless", "--browser", "msedge", "--isolated"],
        profiles=["coding", "research"],
        description="Navegador de testes próprio, snapshots e automação.",
        source="https://github.com/microsoft/playwright-mcp",
        license="Apache-2.0",
        integrity="sha512-weqLrA7/D8MJzNV9/t3Hnjp100tS2sxFXKeb2gH6Nhktqmdfvx5qRA9AZ5Mhjnre1jY0wltsrRK5VZS5NBgcvw==",
    ),
    "google_drive": dict(
        name="Google Drive / Docs / Sheets",
        mode="node",
        package="@piotr-agier/google-drive-mcp",
        version="2.13.0",
        entry="dist/index.js",
        profiles=["research", "work"],
        description="Servidor comunitário para documentos e ficheiros Google.",
        source="https://github.com/piotr-agier/google-drive-mcp",
        license="MIT",
        integrity="sha512-qEarVL28NbFhrMt0XDfPM1Q2B2gGQuA9FGUTQjOTBF5ZzTtfbJJUoK6dpIyR/ewG+D4e8b/3U80tgTB38JnOIw==",
        help="Cria um cliente OAuth Desktop no Google Cloud e indica o respetivo JSON. Depois autoriza a conta pelo botão próprio.",
        fields=[
            dict(
                key="credentials_path",
                label="Ficheiro JSON OAuth Desktop do Google",
                required=True,
                secret=False,
            )
        ],
    ),
}

# Implementações próprias empacotadas: não dependem de npm nem de servidores terceiros.
def _field(key, label, default="", secret=False, required=False, options=None):
    return dict(key=key, label=label, default=default, secret=secret, required=required, options=options)


for _kind, _name, _description, _profiles, _fields, _help in [
    ("fetch", "Fetch", "Ler páginas e documentos de texto HTTP/HTTPS.", ["research", "coding"], [], "Incluído na app e disponível automaticamente. Não executa JavaScript; para isso usa o browser integrado."),
    ("brave", "Brave Search", "Pesquisa atualizada na web.", ["research"], [_field("api_key", "Chave de API Brave Search", secret=True, required=True)], "Indica a chave do Brave Search uma vez. O botão Testar faz uma pesquisa e pode consumir a quota da conta."),
    ("postgres", "PostgreSQL", "Consultar schemas, executar queries e escritas opcionais.", ["coding", "work"], [], "Indica a base de dados existente. A app não instala um servidor PostgreSQL. As consultas usam parâmetros %s."),
    ("mysql", "MySQL", "Consultar schemas, executar queries e escritas opcionais.", ["coding", "work"], [], "Indica a base de dados existente. A app não instala um servidor MySQL. As consultas usam parâmetros %s."),
    ("discord", "Discord", "Listar servidores e canais, ler mensagens e enviar opcionalmente.", ["work"], [_field("token", "Token do bot Discord", secret=True, required=True), _field("readonly", "Permissões", "true", options=[["true", "Só leitura"], ["false", "Permitir envio de mensagens"]])], "Cria um bot no Discord Developer Portal e adiciona-o ao teu servidor. Para ler conteúdo poderá ser necessário ativar Message Content Intent. Não uses um token pessoal."),
]:
    if _kind in ("postgres", "mysql"):
        _fields = [_field("host", "Servidor", "localhost", required=True),
                   _field("port", "Porta", "5432" if _kind == "postgres" else "3306"),
                   _field("database", "Base de dados", required=True), _field("user", "Utilizador", required=True),
                   _field("password", "Palavra-passe (vazio mantém a atual)", secret=True),
                   _field("tls", "Ligação TLS", "true", options=[["true", "TLS com certificado verificado"], ["false", "Sem TLS (servidor local)"]]),
                   _field("readonly", "Permissões", "true", options=[["true", "Só leitura"], ["false", "Permitir escrita SQL"]])]
    CATALOG[_kind] = dict(name=_name, mode="bundled", description=_description, profiles=_profiles, fields=_fields, help=_help)


def bundled_command(kind):
    args = ["--integration-server", kind] if getattr(sys, "frozen", False) else ["-u", str(Path(__file__).resolve().parent / "integration_server.py"), kind]
    return sys.executable, [*args, str(config.config_dir().resolve())]


def ensure_fetch():
    """Uma única ativação no arranque; respeita remoções/desativações posteriores."""
    cfg = config.load_config()
    if cfg.get("bundled_fetch_initialized"):
        return
    if not find_server(cfg, "fetch"):
        from mcp_bridge import validate_server
        server = validate_server({**server_for("fetch"), "id": "studio-fetch", "approval": "auto"})
        cfg.setdefault("mcp_servers", []).append(server)
    cfg["bundled_fetch_initialized"] = True
    config.save_config(cfg)


def _node_flags():
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def node_executable():
    return shutil.which("node")


def node_version(node):
    try:
        result = subprocess.run(
            [node, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            creationflags=_node_flags(),
        )
        return int((result.stdout or "").strip().lstrip("v").split(".")[0])
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("Não foi possível confirmar a versão do Node.js.") from exc


def _roots():
    """Raízes possíveis dos componentes: junto à app e na config do utilizador."""
    return [
        config.application_root() / ".integrations" / "node",
        config.config_dir() / "integrations" / "node",
    ]


def _writable(root):
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".write-test"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def runtime_root():
    """Pasta onde instalar: junto à app se der, senão na config do utilizador."""
    for root in _roots():
        if (root / "node_modules").is_dir() or _writable(root):
            return root
    return _roots()[-1]


def package_dir(kind, root=None):
    return (root or runtime_root()) / "node_modules" / CATALOG[kind]["package"]


def _integrity_matches(kind, root):
    expected = CATALOG[kind].get("integrity")
    if not expected:
        return True
    try:
        lock = json.loads((root / "package-lock.json").read_text(encoding="utf-8"))
        packages = lock.get("packages") or {}
        actual = (packages.get("node_modules/" + CATALOG[kind]["package"]) or {}).get("integrity", "")
        return actual == expected
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def _installed_in(kind, root):
    item = CATALOG[kind]
    folder = package_dir(kind, root)
    try:
        package = json.loads((folder / "package.json").read_text(encoding="utf-8"))
        return (
            (folder / item["entry"]).is_file()
            and str(package.get("version", "")) == item["version"]
            and _integrity_matches(kind, root)
        )
    except (OSError, ValueError, TypeError):
        return False


def installed(kind):
    item = CATALOG.get(kind)
    if item is None or item["mode"] != "node":
        return True
    return any(_installed_in(kind, root) for root in _roots())


def entry_path(kind):
    item = CATALOG[kind]
    for root in _roots():
        if _installed_in(kind, root):
            return package_dir(kind, root) / item["entry"]
    return package_dir(kind, runtime_root()) / item["entry"]


def google_environment(settings):
    path = Path((settings or {}).get("credentials_path", "")).expanduser()
    if not path.is_file():
        raise ValueError("Indica o ficheiro JSON OAuth Desktop do Google.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("O ficheiro de credenciais do Google não é JSON válido.") from exc
    if not isinstance(data, dict) or "installed" not in data:
        raise ValueError("O ficheiro deve ser um cliente OAuth Desktop (chave 'installed').")
    directory = config.config_dir() / "google-drive-mcp"
    directory.mkdir(parents=True, exist_ok=True)
    return {
        "GOOGLE_DRIVE_OAUTH_CREDENTIALS": str(path.resolve()),
        "XDG_CONFIG_HOME": str(directory),
    }


def server_for(kind, settings=None):
    """Configuração de servidor MCP para o preset, pronta para ``save_mcp_server``."""
    item = CATALOG.get(kind)
    if item is None:
        raise ValueError("Integração MCP desconhecida.")
    base = {
        "name": item["name"],
        "enabled": True,
        "approval": "each",
        "preset": kind,
    }
    if item["mode"] == "remote":
        return {
            **base,
            "transport": "http",
            "url": item["url"],
            "auth_mode": "oauth",
            "headers": {},
        }
    if item["mode"] == "bundled":
        command, args = bundled_command(kind)
        return {**base, "transport": "stdio", "command": command, "args": args, "env": {}}
    node = node_executable()
    if not node:
        raise RuntimeError("Instala Node.js 20 ou superior para este componente local.")
    if not installed(kind):
        raise RuntimeError("Instala o componente local antes de o configurar.")
    env = google_environment(settings or {}) if kind == "google_drive" else {}
    return {
        **base,
        "transport": "stdio",
        "command": node,
        "args": [str(entry_path(kind)), *item.get("args", [])],
        "env": env,
    }


def find_server(cfg, kind):
    """Servidor já criado para o preset, incluindo os criados manualmente."""
    item = CATALOG.get(kind)
    if item is None:
        return None
    servers = [s for s in cfg.get("mcp_servers", []) if isinstance(s, dict)]
    for server in servers:
        if server.get("preset") == kind:
            return server
    for server in servers:
        if item["mode"] == "remote":
            url = str(server.get("url", "")).rstrip("/")
            if url and url == item["url"].rstrip("/"):
                return server
        elif item["mode"] == "node" and server.get("transport") == "stdio":
            entry = item["entry"].replace("\\", "/")
            for argument in server.get("args", []):
                if str(argument).replace("\\", "/").endswith("/" + entry):
                    return server
    return None


class ComponentJobs:
    """Instalação/autorização de componentes Node em segundo plano."""

    def __init__(self, on_success=None):
        self.on_success = on_success
        self.jobs = {}
        self.lock = threading.RLock()
        self.install_lock = threading.Lock()

    def start(self, kind, authorize=False, settings=None):
        item = CATALOG.get(kind)
        if item is None or item["mode"] != "node":
            raise ValueError("Esta integração não precisa de instalação externa.")
        with self.lock:
            old = self.jobs.get(kind)
            if old and old["state"] == "running":
                return self.status(kind)
            job = {
                "state": "running",
                "message": "A autorizar no browser…" if authorize else "A instalar o componente local…",
            }
            self.jobs[kind] = job

            def run():
                try:
                    node = node_executable()
                    if not node:
                        raise RuntimeError("Instala Node.js 20 ou superior para estes componentes locais.")
                    if node_version(node) < 20:
                        raise RuntimeError("O Node.js instalado é antigo; atualiza para a versão 20 ou superior.")
                    if authorize:
                        if kind != "google_drive":
                            raise ValueError("Este componente não tem autorização própria.")
                        if not installed(kind):
                            raise RuntimeError("Instala o componente antes de autorizar.")
                        env = google_environment(settings or {})
                        command = [node, str(entry_path(kind)), "auth"]
                        result = subprocess.run(
                            command,
                            env={**os.environ, **env},
                            capture_output=True,
                            text=True,
                            encoding="utf-8",
                            errors="replace",
                            timeout=240,
                            creationflags=_node_flags(),
                        )
                    else:
                        with self.install_lock:
                            npm = shutil.which("npm.cmd") or shutil.which("npm")
                            if not npm:
                                raise RuntimeError("npm não está disponível. Instala Node.js com npm.")
                            npm_cli = Path(npm).parent / "node_modules" / "npm" / "bin" / "npm-cli.js"
                            command = [node, str(npm_cli)] if npm_cli.is_file() else [npm]
                            runtime_root().mkdir(parents=True, exist_ok=True)
                            command += [
                                "install",
                                "--prefix",
                                str(runtime_root()),
                                "--ignore-scripts",
                                "--no-audit",
                                "--no-fund",
                                item["package"] + "@" + item["version"],
                            ]
                            result = subprocess.run(
                                command,
                                capture_output=True,
                                text=True,
                                encoding="utf-8",
                                errors="replace",
                                timeout=240,
                                creationflags=_node_flags(),
                            )
                    if result.returncode:
                        details = (result.stderr or result.stdout or "").strip().splitlines()
                        suffix = (" " + details[-1][:300]) if details else ""
                        raise RuntimeError("O componente não concluiu a operação." + suffix)
                    if not authorize and not installed(kind):
                        raise RuntimeError("O ficheiro principal do componente não foi instalado.")
                    with self.lock:
                        job.update(
                            state="ready",
                            message="Autorização concluída." if authorize else "Componente instalado.",
                        )
                    if self.on_success:
                        self.on_success(kind)
                except Exception as exc:  # noqa: BLE001
                    with self.lock:
                        job.update(state="error", message=str(exc)[:500])

            thread = threading.Thread(target=run, daemon=True)
            thread.start()
            return self.status(kind)

    def status(self, kind):
        with self.lock:
            return dict(self.jobs.get(kind, {"state": "idle", "message": ""}))


class PresetCatalog:
    def __init__(self, on_success=None):
        self.components = ComponentJobs(on_success)

    def status(self, cfg):
        settings = cfg.get("mcp_preset_settings") or {}
        output = []
        for kind, item in CATALOG.items():
            server = find_server(cfg, kind)
            node = node_executable() if item["mode"] == "node" else (sys.executable if item["mode"] == "bundled" else None)
            output.append(
                {
                    "kind": kind,
                    "name": item["name"],
                    "mode": item["mode"],
                    "transport": "http" if item["mode"] == "remote" else "stdio",
                    "url": item.get("url", ""),
                    "command": node or "",
                    "args": (
                        [str(entry_path(kind)), *item.get("args", [])]
                        if item["mode"] == "node"
                        else (bundled_command(kind)[1] if item["mode"] == "bundled" else [])
                    ),
                    "description": item["description"],
                    "source": item.get("source", ""),
                    "help": item.get("help", ""),
                    "profiles": item.get("profiles", []),
                    "license": item.get("license", ""),
                    "version": item.get("version", ""),
                    "installed": installed(kind),
                    "node": True if item["mode"] == "remote" else bool(node),
                    "server_id": server.get("id", "") if server else "",
                    "enabled": bool(server.get("enabled", True)) if server else False,
                    "approval": server.get("approval", "each") if server else "each",
                    "settings": {f["key"]: settings.get(kind, {}).get(f["key"], f.get("default", "")) for f in item.get("fields", []) if not f.get("secret")},
                    "fields": item.get("fields", []),
                    "job": self.components.status(kind),
                }
            )
        return output
