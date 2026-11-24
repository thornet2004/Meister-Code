"""Ponte ``Api``: servidores MCP, ferramentas numa pasta e presets de integrações.

Classe-base de ``api.Api`` (extraída de ``api.py`` sem alterações ao código).
Os métodos sem ``_`` inicial são chamados pela interface através da ponte do
pywebview.

Depende do que ``api.Api`` cria ou define:
  - ``self._mcp``, ``self._oauth``, ``self._folder_tools``, ``self._presets``
    (criados em ``Api.__init__``);
  - ``self._preset_status`` (método de ``Api``).
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import config
import folder_tools
import integration_catalog
from api_helpers import _err, _ok
from mcp_bridge import validate_server
from mcp_oauth import OAuthStore


class McpApi:
    def get_mcp_servers(self) -> dict:
        try:
            cfg=config.load_config()
            return _ok(servers=self._mcp.status(cfg.get("mcp_servers",[])))
        except Exception as exc:return _err(str(exc))

    def get_folder_tools(self) -> dict:
        try:
            return _ok(tools=self._folder_tools.status(config.load_config()),root=str(folder_tools.root()),job=self._folder_tools.installer.status())
        except Exception as exc:return _err(str(exc))

    def open_tools_folder(self, tool_id: str = "") -> dict:
        try:
            cfg=config.load_config()
            if tool_id:
                row=next((r for r in folder_tools.scan(cfg) if r["id"]==tool_id),None)
                if not row:return _err("Ferramenta não encontrada.")
                path=Path(row["path"])
            else:path=folder_tools.ensure_layout()
            os.startfile(str(path))
            return _ok()
        except Exception as exc:return _err(str(exc))

    def set_folder_tool(self, tool_id: str, enabled=None, approval=None) -> dict:
        try:
            cfg=config.load_config()
            row=next((r for r in folder_tools.scan(cfg) if r["id"]==tool_id and r.get("server")),None)
            if not row:return _err("Ferramenta ou manifesto inválido.")
            value=dict(cfg.setdefault("folder_tools",{}).get(tool_id,{}))
            if enabled is not None:
                if not isinstance(enabled,bool):return _err("Estado inválido.")
                value["enabled"]=enabled
            if approval is not None:
                if approval not in ("each","auto"):return _err("Aprovação inválida.")
                value["approval"]=approval
            cfg["folder_tools"][tool_id]=value
            config.save_config(cfg)
            self._folder_tools.manager.reset(tool_id)
            return self.get_folder_tools()
        except Exception as exc:return _err(str(exc))

    def test_folder_tool(self, tool_id: str) -> dict:
        try:
            cfg=config.load_config()
            self._folder_tools.manager.reset(tool_id)
            _row,_client,definitions=self._folder_tools._connect(cfg,tool_id,test=True)
            return _ok(count=len(definitions),tools=[t["name"] for t in definitions])
        except Exception as exc:return _err(str(exc))

    def get_mcp_presets(self) -> dict:
        try:
            cfg=config.load_config()
            return _ok(presets=self._preset_status(cfg), mcp_profile=cfg.get("preferences", {}).get("mcp_profile", "all"))
        except Exception as exc:return _err(str(exc))

    def save_mcp_server(self, data: dict) -> dict:
        try:
            cfg=config.load_config();servers=cfg.setdefault("mcp_servers",[])
            old=next((s for s in servers if isinstance(s,dict) and s.get("id")==data.get("id")),None)
            server=validate_server(data,old)
            server["id"]=old["id"] if old else uuid.uuid4().hex[:12]
            if old and (old.get("url") != server.get("url") or old.get("oauth_client_id") != server.get("oauth_client_id")):
                self._oauth.cancel(old["id"],discard=True);self._oauth.wait(old["id"])
                if old.get("auth_mode") == "oauth": OAuthStore(old).clear()
            if old and old.get("auth_mode") == "oauth" and server.get("auth_mode") != "oauth":
                OAuthStore(old).clear()
            if "oauth_client_secret" in data and server.get("auth_mode") == "oauth":
                OAuthStore(server).update(manual_client_secret=data["oauth_client_secret"] or None, client=None, tokens=None, expires_at=None)
            cfg["mcp_servers"]=[s for s in servers if not (isinstance(s,dict) and s.get("id")==server["id"])]+[server]
            config.save_config(cfg);self._mcp.reset(server["id"])
            return self.get_mcp_servers()
        except Exception as exc:return _err(str(exc))

    def remove_mcp_server(self, server_id: str) -> dict:
        try:
            cfg=config.load_config()
            old=next((s for s in cfg.get("mcp_servers",[]) if isinstance(s,dict) and s.get("id")==server_id),None)
            self._oauth.cancel(server_id,discard=True);self._oauth.wait(server_id)
            if old and old.get("auth_mode") == "oauth": OAuthStore(old).clear()
            cfg["mcp_servers"]=[s for s in cfg.get("mcp_servers",[]) if not (isinstance(s,dict) and s.get("id")==server_id)]
            config.save_config(cfg);self._mcp.reset(server_id)
            return self.get_mcp_servers()
        except Exception as exc:return _err(str(exc))

    def test_mcp_server(self, server_id: str) -> dict:
        try:
            cfg=config.load_config()
            server=next((s for s in cfg.get("mcp_servers",[]) if isinstance(s,dict) and s.get("id")==server_id),None)
            if server is None:return _err("Servidor MCP não encontrado.")
            probe={**server,"enabled":True}
            _meta,workspace=config.resolve_context(cfg)
            self._mcp.reset(server_id)
            self._mcp.tools([probe],str(workspace.resolve()),prune=False,timeout=30,total_timeout=35)
            state=self._mcp.status([probe])[0]
            if state["connected"] and server.get("preset") in ("fetch", "brave", "postgres", "mysql", "discord"):
                alias=next((a for a, route in self._mcp.routes.items() if route == (server_id,"connection_test")),None)
                if not alias:return _err("O conector não disponibilizou o teste de ligação.")
                result=self._mcp.call(alias,{},[probe],lambda *args: True)
                message=" ".join(p.get("text","") for p in result.get("content",[]))
                with self._mcp.lock:
                    entry=self._mcp.entries.get(server_id,{})
                    entry["service_verified"]=not result.get("isError",False)
                    entry["service_error"]=message if result.get("isError") else ""
                if result.get("isError"):
                    return _err(message)
                state=self._mcp.status([probe])[0]
            return _ok(server=state) if state["connected"] else _err(state["error"] or "Não foi possível ligar ao servidor MCP.")
        except Exception as exc:return _err(str(exc))

    def add_mcp_demo(self) -> dict:
        cfg=config.load_config()
        existing=next((s for s in cfg.get("mcp_servers",[]) if isinstance(s,dict) and s.get("name")=="Demonstração local"),None)
        if existing:
            result=self.save_mcp_server({**existing,"enabled":True})
        else:
            args=["--mcp-demo-server"] if getattr(sys,"frozen",False) else ["-u",str(Path(__file__).resolve().parent/"mcp_demo.py")]
            result=self.save_mcp_server({"name":"Demonstração local", "transport":"stdio", "command":sys.executable,"args":args,"enabled":True,"approval":"auto"})
        if result.get("ok"):
            server_id=next((s.get("id","") for s in result.get("servers",[]) if s.get("name")=="Demonstração local"),"")
            if server_id:self.test_mcp_server(server_id)
        return result

    def start_mcp_oauth(self, server_id: str) -> dict:
        try:
            cfg=config.load_config()
            server=next((s for s in cfg.get("mcp_servers",[]) if isinstance(s,dict) and s.get("id")==server_id),None)
            if server is None:return _err("Servidor MCP não encontrado.")
            if server.get("auth_mode") != "oauth" or server.get("transport") != "http":
                return _err("Escolhe OAuth e transporte HTTP na configuração do servidor.")
            self._mcp.reset(server_id)
            return _ok(job=self._oauth.start(dict(server)))
        except Exception as exc:return _err(str(exc))

    def mcp_oauth_status(self, server_id: str) -> dict:
        return _ok(job=self._oauth.status(server_id))

    def cancel_mcp_oauth(self, server_id: str) -> dict:
        try:
            self._oauth.cancel(server_id)
            return _ok(job=self._oauth.status(server_id))
        except Exception as exc:return _err(str(exc))

    def disconnect_mcp_oauth(self, server_id: str) -> dict:
        try:
            cfg=config.load_config()
            server=next((s for s in cfg.get("mcp_servers",[]) if isinstance(s,dict) and s.get("id")==server_id),None)
            if server is None:return _err("Servidor MCP não encontrado.")
            self._oauth.cancel(server_id,discard=True);self._oauth.wait(server_id)
            OAuthStore(server).clear();self._mcp.reset(server_id)
            return self.get_mcp_servers()
        except Exception as exc:return _err(str(exc))

    # ------------------------------------------------------------------ #
    # Presets de integrações MCP (remotos e componentes Node)
    # ------------------------------------------------------------------ #
    def _component_success(self, kind):
        try:
            cfg=config.load_config()
            server=integration_catalog.find_server(cfg,kind)
            if server and server.get("id"):self._mcp.reset(server["id"])
        except Exception:pass

    def install_mcp_component(self, kind: str, authorize: bool = False) -> dict:
        try:
            cfg=config.load_config()
            item=integration_catalog.CATALOG.get(kind)
            if item is None:return _err("Integração MCP desconhecida.")
            if item["mode"] != "node":return _err("Esta integração não precisa de instalação local.")
            settings=dict((cfg.get("mcp_preset_settings") or {}).get(kind, {}))
            job=self._presets.components.start(kind,authorize=bool(authorize),settings=settings)
            return _ok(job=job,presets=self._preset_status(cfg))
        except Exception as exc:return _err(str(exc))

    def mcp_component_status(self, kind: str) -> dict:
        try:
            if kind not in integration_catalog.CATALOG:return _err("Integração MCP desconhecida.")
            return _ok(job=self._presets.components.status(kind))
        except Exception as exc:return _err(str(exc))

    def save_mcp_preset(self, kind: str, data: dict = None) -> dict:
        try:
            cfg=config.load_config()
            item=integration_catalog.CATALOG.get(kind)
            if item is None:return _err("Integração MCP desconhecida.")
            data=data or {}
            settings=dict((cfg.get("mcp_preset_settings") or {}).get(kind, {}))
            if item["mode"]=="bundled":
                return self._save_bundled_preset(kind,data,cfg)
            for field in item.get("fields", []):
                if field["key"] in data and data[field["key"]] is not None:
                    value=data[field["key"]]
                    if not isinstance(value,str):return _err("Campo inválido: "+field["label"])
                    settings[field["key"]]=value.strip()
                if field.get("required") and not settings.get(field["key"]):
                    return _err("Falta: "+field["label"])
            if kind=="google_drive":
                integration_catalog.google_environment(settings)
            server=integration_catalog.server_for(kind,settings)
            existing=integration_catalog.find_server(cfg,kind)
            if existing:
                server["id"]=existing.get("id","")
            for key in ("approval","enabled"):
                if key in data:server[key]=data[key]
            if item["mode"]=="remote":
                if data.get("auth_mode") in ("manual","oauth"):server["auth_mode"]=data["auth_mode"]
                for key in ("headers","env"):
                    if key in data:server[key]=data[key]
            for key in ("oauth_client_id","oauth_callback_port","oauth_scope"):
                if key in data:server[key]=data[key]
            if data.get("oauth_client_secret"):server["oauth_client_secret"]=data["oauth_client_secret"]
            result=self.save_mcp_server(server)
            if not result.get("ok"):return result
            cfg=config.load_config()
            cfg.setdefault("mcp_preset_settings",{})[kind]=settings
            config.save_config(cfg)
            result=dict(result)
            result["presets"]=self._preset_status(cfg)
            result["server_id"]=next((s.get("id","") for s in result.get("servers",[]) if s.get("preset")==kind),"")
            return result
        except Exception as exc:return _err(str(exc))

    def _save_bundled_preset(self, kind, data, cfg):
        from integration_services import SettingsStore, validate_settings
        item=integration_catalog.CATALOG[kind]
        store=SettingsStore(kind)
        previous=store.read()
        settings=dict(previous)
        for field in item.get("fields",[]):
            value=data.get(field["key"])
            if value is not None and not isinstance(value,str):return _err("Campo inválido: "+field["label"])
            if value is not None and (value or not field.get("secret")):
                settings[field["key"]]=value.strip()
            elif field["key"] not in settings:
                settings[field["key"]]=field.get("default","")
        settings=validate_settings(kind,settings)
        server=integration_catalog.server_for(kind)
        existing=integration_catalog.find_server(cfg,kind)
        if existing:server["id"]=existing["id"]
        for key in ("approval","enabled"):
            if key in data:server[key]=data[key]
        # Validar antes de gravar credenciais; rollback se a config falhar.
        validate_server({**server,"id":server.get("id","validate")})
        store.write(settings)
        result=self.save_mcp_server(server)
        if not result.get("ok"):
            store.write(previous)
            return result
        cfg=config.load_config()
        cfg.setdefault("mcp_preset_settings",{})[kind]={f["key"]:settings.get(f["key"],"") for f in item.get("fields",[]) if not f.get("secret")}
        config.save_config(cfg)
        result["presets"]=self._preset_status(cfg)
        result["server_id"]=next((s["id"] for s in result.get("servers",[]) if s.get("preset")==kind),"")
        return result
