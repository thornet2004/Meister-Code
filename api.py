"""Classe `Api` exposta ao JavaScript via pywebview (`js_api`).

Chat multimodal com quatro capacidades por modelo + MODO AGENTE:
  - "chat"  : texto / multimodal (/chat/completions)   [programar entra aqui]
  - "image" : geração de imagem (/images)
  - "video" : geração de vídeo  (/videos, assíncrono)
  - "audio" : geração de fala    (/audio/speech)

Modo agente (opcional, ligado nas Configurações): o modelo de chat pode chamar
ferramentas para mexer em ficheiros e correr comandos, à semelhança do Claude
Code / Codex:
  - listar_pasta, ler_ficheiro, escrever_ficheiro, executar_comando

Segurança do modo agente:
  - Âmbito de ficheiros: "project" (projeto ativo) ou "computer" (todo o PC).
  - Aprovação: "each" (confirma cada ação), "writes" (confirma escrita/comandos
    uma vez por categoria) ou "auto" (sem confirmar). As confirmações aparecem
    como um cartão na app; sem janela/confirmação, a ação é RECUSADA.
  - Escritas diretas em âmbito "project" ficam na pasta; comandos podem usar todo o PC.

Regras mantidas:
  - A chave de API NUNCA é devolvida ao frontend (só `has_key`).
  - Erros são devolvidos como {"ok": False, "error": "..."} — nunca em silêncio.
  - Nada é apagado do disco sem pedido explícito.

Organização: este ficheiro tem só o núcleo (arranque, estado, preferências,
terminal e aprovações). Os restantes métodos da ponte vêm de classes-base,
uma por tema, de que `Api` herda:
  - `api_chat.ChatApi`             pedido, ciclo modelo/ferramentas, retoma
  - `api_agent.AgentApi`           agente, subagentes, propostas, skills
  - `api_code.CodeApi`             checkpoints, patches, ficheiros e comandos
  - `api_operations.OperationsApi` comandos em segundo plano, hooks, validação, Git
  - `api_context.ContextApi`       janela de contexto, compactação, pesquisa
  - `api_media.MediaApi`           geração direta, histórico, galeria
  - `api_workspaces.WorkspaceApi`  projetos e conversas
  - `api_providers.ProvidersApi`   provedores e modelos
  - `api_mcp.McpApi`               MCP, ferramentas numa pasta, presets
  - `api_system.SystemApi`         diagnóstico, atualizações, browser, bancada
  - `api_semantic.SemanticApi`     pesquisa de código por significado (embeddings)
  - `api_knowledge.KnowledgeApi`   base de conhecimento por projeto (notas do agente/utilizador)
Funções sem estado: `api_helpers.py` e `chat_messages.py`. Os métodos públicos
(sem `_`) são o contrato com a interface: ver `tests/test_bridge_contract.py`.
"""

from __future__ import annotations

import json
import shutil
import sys
import threading
import uuid

import command_safety
import config
import rig
import integration_catalog
import folder_tools
import providers
from terminal import PowerShellSession
from terminal_interactive import InteractiveShell
from mcp_bridge import MCPManager
from mcp_oauth import OAuthJobs
from tool_catalog import BROWSER_TOOLS, LOCAL_TOOLS, CODING_TOOLS, AGENT_TOOLS, _TOOLS, _AGENT_TOOLS
from agent_runtime import PROFILES,READ_TOOLS,AgentTasks
import project_validation
import system_diagnostics
from release_updates import Updates
from app_version import VERSION
from coding_lsp import LanguageServers
from command_jobs import CommandJobs
from api_operations import OperationsApi
from api_context import ContextApi
from api_media import MediaApi
from api_agent import AgentApi
from api_code import CodeApi
from api_chat import ChatApi
from api_mcp import McpApi
from api_knowledge import KnowledgeApi
from api_semantic import SemanticApi
from api_providers import ProvidersApi
from api_system import SystemApi
from api_workspaces import WorkspaceApi
from api_helpers import (
    APPROVAL_TIMEOUT,
    MODEL_SLOTS,
    _ok,
    _err,
    _sanitize_provider,
    _sanitize_project,
    _sanitize_conv,
    _resolve_model,
    _open_in_file_manager,
    _fmt_exc,
)

# Reexportados: os testes usam estes nomes como ``api.<nome>``.
import agent_isolation  # noqa: F401,E402
from api_helpers import _agent_cwd, _resolve_agent_model, _resolve_in_scope  # noqa: F401,E402
from chat_messages import _build_model_messages, _load_conversation, _save_attachments, _save_conversation  # noqa: F401,E402


class Api(SystemApi, McpApi, WorkspaceApi, ProvidersApi, OperationsApi, ContextApi, MediaApi, AgentApi, CodeApi, ChatApi, SemanticApi, KnowledgeApi):
    def __init__(self):
        self._terminal = PowerShellSession()
        self._shell = InteractiveShell()
        self._mcp = MCPManager()
        self._folder_tools = folder_tools.FolderTools()
        self._presets = integration_catalog.PresetCatalog(on_success=self._component_success)
        self._oauth = OAuthJobs(on_success=self._mcp.reset)
        self._browser = None
        self._window = None  # definido por app.py
        self._approvals = {}  # req_id -> {"event": Event, "decision": str|None}
        self._approved_categories = set()  # allowlist por sessão (modo "writes")
        self._cancel_chat = threading.Event()
        self._lsp=LanguageServers()
        self._code_reads={}
        self._code_lock=threading.RLock()
        self._code_turns=set()
        self._turn_lock=threading.RLock();self._active_contexts=set()
        self._tasks=AgentTasks(self._run_subagent)
        self._commands=CommandJobs()
        self._validations=project_validation.ValidationRuns(self._commands)
        self._updates=Updates();self._provider_tests=system_diagnostics.ProviderTests()

    # ------------------------------------------------------------------ #
    # Estado / config
    # ------------------------------------------------------------------ #
    def get_state(self) -> dict:
        try:
            cfg = config.load_config()
            if self._ensure_context(cfg):
                config.save_config(cfg)
            caps = {k: providers.family_caps(k) for k in providers.available_kinds()}
            _meta_dir, out_dir = config.resolve_context(cfg)
            convs = sorted(cfg.get("conversations", []), key=lambda c: c.get("updated_at", ""), reverse=True)
            convs = sorted(convs, key=lambda c: bool(c.get("pinned", False)), reverse=True)
            projects = sorted(cfg.get("projects", []), key=lambda p: (not bool(p.get("pinned", False)), (p.get("name", "") or "").lower()))
            return _ok(
                # a rig só entra na lista (e na barra de modelos) enquanto está ligada
                providers=[_sanitize_provider(p) for p in cfg.get("providers", []) if not p.get("rig") or p.get("enabled")],
                rig=rig.state(cfg),
                projects=[_sanitize_project(p) for p in projects],
                active_project_id=cfg.get("active_project_id", ""),
                conversations=[_sanitize_conv(c) for c in convs],
                active_conversation_id=cfg.get("active_conversation_id", ""),
                output_dir=str(out_dir),
                selections={t: cfg.get(t, {}) for t in MODEL_SLOTS},
                preferences=cfg.get("preferences", {}),
                kinds=providers.available_kinds(),
                kind_caps=caps,
                kind_details=providers.provider_presets(),
                config_path=str(config.config_path()),
                app_version=VERSION,
                conversations_root=str(config.conversations_root()),
                projects_root=str(config.projects_root()),
            )
        except Exception as exc:  # noqa: BLE001
            return _err(_fmt_exc(exc))

    def set_output_dir(self, path: str) -> dict:
        try:
            cfg = config.load_config()
            cfg["output_dir"] = (path or "").strip() or config.default_output_dir()
            config.save_config(cfg)
            return self.get_state()
        except Exception as exc:  # noqa: BLE001
            return _err(_fmt_exc(exc))

    def open_output_dir(self) -> dict:
        """Abre a pasta de saída do contexto ativo (projeto ou padrão)."""
        try:
            cfg = config.load_config()
            _meta_dir, out_dir = config.resolve_context(cfg)
            out_dir.mkdir(parents=True, exist_ok=True)
            _open_in_file_manager(out_dir)
            return _ok()
        except Exception as exc:  # noqa: BLE001
            return _err(_fmt_exc(exc))

    def _available_tools(self, cfg, agent_ctx, connect=True):
        if agent_ctx.get('readonly'):
            candidates=list(LOCAL_TOOLS.values())
            if agent_ctx.get('on'):candidates += [*_AGENT_TOOLS.values(),*CODING_TOOLS.values(),*AGENT_TOOLS.values()]
            return self._semantic_filter_tools(cfg, agent_ctx, [t for t in candidates if t['function']['name'] in READ_TOOLS])
        tools = [_TOOLS[cap] for cap in ("image", "video", "audio") if _resolve_model(cfg, cap)[0] is not None]
        if agent_ctx["on"]:
            tools += list(_AGENT_TOOLS.values())
        tools += [tool for name, tool in LOCAL_TOOLS.items() if name != "git_consultar" or shutil.which("git")]
        if self._window is not None and sys.platform == "win32":
            tools += list(BROWSER_TOOLS.values())
        if agent_ctx.get('on'):tools += list(CODING_TOOLS.values())
        if agent_ctx.get('on'):tools += list(AGENT_TOOLS.values())
        _meta, workspace = config.resolve_context(cfg)
        tools += self._mcp.tools(cfg.get("mcp_servers", []), str(workspace.resolve()), connect=connect)
        tools += folder_tools.tool_definitions(folder_tools.scan(cfg))
        return self._semantic_filter_tools(cfg, agent_ctx, tools)

    def _preset_status(self, cfg):
        presets = self._presets.status(cfg)
        server_list = [s for s in cfg.get("mcp_servers", []) if isinstance(s, dict) and s.get("id")]
        states = {s["id"]: s for s in self._mcp.status(server_list)}
        for preset in presets:
            server_id = preset.get("server_id")
            if server_id and server_id in states:
                preset["server"] = states[server_id]
        return presets

    def terminal_execute(self, command: str) -> dict:
        """Comandos introduzidos pelo utilizador na consola integrada."""
        try:
            if sys.platform != "win32":
                return _err("A consola integrada requer Windows e PowerShell.")
            command = (command or "").strip()
            if not command:
                return _err("Escreve um comando.")
            cfg = config.load_config()
            _meta, output_dir = config.resolve_context(cfg)
            return _ok(**self._terminal.execute(command, str(output_dir.resolve())))
        except Exception as exc:
            return _err(_fmt_exc(exc))

    def terminal_send(self, text: str) -> dict:
        """Terminal interativo: envia uma linha (comando, ou entrada do programa a correr)."""
        try:
            if sys.platform != "win32":
                return _err("A consola integrada requer Windows e PowerShell.")
            cfg = config.load_config()
            _meta, output_dir = config.resolve_context(cfg)
            return _ok(**self._shell.send(str(text or ""), str(output_dir.resolve())))
        except Exception as exc:
            return _err(str(exc))

    def terminal_read(self, cursor: int = 0) -> dict:
        """Terminal interativo: saída desde ``cursor`` e estado (ocupado, pasta, código de saída)."""
        try:
            return _ok(**self._shell.read(cursor))
        except Exception as exc:
            return _err(str(exc))

    def terminal_stop(self) -> dict:
        """Terminal interativo: interrompe o que está a correr."""
        try:
            return _ok(**self._shell.stop())
        except Exception as exc:
            return _err(str(exc))

    def set_preference(self, key: str, value) -> dict:
        try:
            if key=='agent_profile' and value not in PROFILES:return _err('Perfil de agente inválido.')
            if key=='voice_reply':  # só enquanto a conversa por voz está ligada; não se guarda em disco
                self._voice_reply=bool(value)
                import voice_output
                if value:threading.Thread(target=voice_output.warm,args=(folder_tools.root(),config.load_config().get('preferences',{}).get('voice_name','')),name='voz-aquecer',daemon=True).start()
                else:voice_output.close()  # a voz fica carregada só enquanto a conversa está ligada
                return _ok()
            if key=='voice_server':
                import voice_input
                try:value=voice_input.server_address(value)
                except voice_input.VoiceError as exc:return _err(str(exc))
            if key=='voice_name' and (not isinstance(value,str) or len(value)>120 or any(c in value for c in '/\\:*?"<>|')):return _err('Voz inválida.')
            if key=='agent_name':
                if not isinstance(value,str) or len(value)>40:return _err('Nome do agente inválido (até 40 caracteres).')
                value=value.strip()
            if key=='voice_listen_seconds':
                try:value=int(value)
                except (TypeError,ValueError):return _err('Tempo de escuta inválido (2 a 30 segundos).')
                if not 2<=value<=30:return _err('Tempo de escuta inválido (2 a 30 segundos).')
            if key=='personality' and value not in ('neutra','sociavel','sarcastico','bruto','profissional'):return _err('Personalidade inválida.')
            if key=='voice_tone' and value not in ('normal','grave','muito_grave','profunda'):return _err('Tom de voz inválido.')
            if key=='picker_type' and value not in ('chat','code','image','video','audio'):return _err('Tipo de modelo inválido.')
            if key == "mcp_profile" and value not in config.MCP_PROFILES:
                return _err("Perfil de integrações inválido.")
            if key == "theme" and value not in ("system", "dark", "light"):
                return _err("Tema inválido.")
            if key == "density" and value not in ("comfortable", "compact"):
                return _err("Densidade inválida.")
            cfg = config.load_config()
            cfg.setdefault("preferences", {})[key] = value
            config.save_config(cfg)
            return self.get_state()
        except Exception as exc:  # noqa: BLE001
            return _err(_fmt_exc(exc))

    def set_agent_settings(self, data: dict) -> dict:
        """Liga/desliga o agente e define âmbito e modo de aprovação."""
        try:
            cfg = config.load_config()
            prefs = cfg.setdefault("preferences", {})
            ag = config.normalize_agent(prefs)
            if "enabled" in data:
                ag["enabled"] = bool(data["enabled"])
            if data.get("scope") in config._AGENT_SCOPES:
                ag["scope"] = data["scope"]
            if data.get("approval") in config._AGENT_APPROVALS:
                ag["approval"] = data["approval"]
            if "confirm_dangerous" in data:
                ag["confirm_dangerous"] = bool(data["confirm_dangerous"])
            prefs["agent"] = ag
            config.save_config(cfg)
            # Mudar definições limpa a allowlist da sessão.
            self._approved_categories.clear()
            return self.get_state()
        except Exception as exc:  # noqa: BLE001
            return _err(_fmt_exc(exc))

    # ------------------------------------------------------------------ #
    # Aprovação (chamada pelo frontend)
    # ------------------------------------------------------------------ #
    def respond_approval(self, req_id: str, decision: str) -> dict:
        rec = self._approvals.get(req_id)
        if rec:
            rec["decision"] = decision
            rec["event"].set()
        return _ok()

    def cancel_chat(self) -> dict:
        self._cancel_chat.set()
        return _ok()

    # ------------------------------------------------------------------ #
    # Aprovação (bloqueante, à espera do frontend)
    # ------------------------------------------------------------------ #
    def _approve(self, category: str, summary: str, detail: str, agent_ctx: dict) -> bool:
        mode = agent_ctx.get("approval", "each")
        if category in self._approved_categories:
            return True
        if mode == "auto":
            return True
        decision = self._ask_approval(category, summary, detail)
        if decision in ("allow", "session"):
            if mode == "writes" or decision == "session":
                self._approved_categories.add(category)
            return True
        return False

    def _approve_command(self, command: str, summary: str, detail: str, agent_ctx: dict) -> bool:
        """Aprovação de um comando do agente.

        Um comando com padrões perigosos (``command_safety``) pede SEMPRE
        confirmação, com o motivo, mesmo em modo "auto" ou depois de "permitir
        nesta sessão"; essa autorização vale só para esse comando. Sem janela
        para confirmar, é recusado. Os restantes seguem ``_approve``.
        """
        if agent_ctx.get("confirm_dangerous", True):
            reasons = command_safety.assess(command, agent_ctx.get("base"))
            if reasons:
                warning = detail + "\n\nPede confirmação porque:\n" + "\n".join("- " + reason for reason in reasons)
                decision = self._ask_approval("dangerous", "Comando perigoso — confirmação obrigatória", warning)
                return decision in ("allow", "session")
        return self._approve("command", summary, detail, agent_ctx)

    def _ask_approval(self, category: str, summary: str, detail: str) -> str:
        """Mostra o cartão de aprovação e espera pela decisão do utilizador."""
        if self._window is None:
            return "deny"  # sem UI não há como confirmar -> recusa (seguro)
        req_id = uuid.uuid4().hex
        event = threading.Event()
        self._approvals[req_id] = {"event": event, "decision": None}
        payload = json.dumps(
            {"id": req_id, "category": category, "summary": summary, "detail": detail},
            ensure_ascii=False,
        )
        try:
            self._window.evaluate_js(f"window.showApproval({payload})")
        except Exception:  # noqa: BLE001
            self._approvals.pop(req_id, None)
            return "deny"
        # o mesmo cartão vai para os telemóveis ligados pelo acesso remoto, que também podem responder
        self._remote('approval_asked', {"id": req_id, "category": category, "summary": summary, "detail": detail})
        allowed = event.wait(APPROVAL_TIMEOUT)
        rec = self._approvals.pop(req_id, {})
        self._remote('approval_done', req_id)
        if allowed:
            try:  # respondido no telemóvel: o cartão da janela também se fecha
                self._window.evaluate_js("window.hideApproval && window.hideApproval()")
            except Exception:  # noqa: BLE001
                pass
        if not allowed:
            try:
                self._window.evaluate_js("window.hideApproval && window.hideApproval()")
            except Exception:  # noqa: BLE001
                pass
            return "deny"
        return rec.get("decision") or "deny"
