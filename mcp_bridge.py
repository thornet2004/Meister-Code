"""Cliente MCP de ferramentas: stdio e Streamable HTTP, versões 2026 e legadas."""
import base64
import hashlib
import json
import os
import queue
import re
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from urllib.parse import urlsplit
import requests

MODERN = "2026-07-28"
LEGACY = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
CLIENT = {"name":"studio-media", "version":"2.0"}

# Tempos de ligação automática (chat). "Testar" usa um limite maior.
MCP_CONNECT_TIMEOUT = 8
MCP_TOTAL_CONNECT_TIMEOUT = 10
MAX_TOTAL_TOOLS = 200
MAX_TOOL_SCHEMA_CHARS = 20000

# Ambiente mínimo entregue aos servidores stdio. Credenciais devem ser
# declaradas no campo "env" do servidor, não herdadas de todo o sistema.
_ENV_ALLOW = {
    "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "TMPDIR",
    "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "HOMEDRIVE", "HOMEPATH",
    "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432",
    "OS", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "PROCESSOR_IDENTIFIER",
    "LANG", "LANGUAGE", "LC_ALL", "LC_CTYPE", "LC_MESSAGES", "TERM", "SHELL",
    "USER", "LOGNAME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME",
    "NODE_OPTIONS", "NODE_EXTRA_CA_CERTS", "PYTHONIOENCODING", "PYTHONUTF8",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE",
}


def _base_env():
    return {key: value for key, value in os.environ.items() if key.upper() in _ENV_ALLOW}


def _run_with_timeout(function, timeout):
    """Executa uma função bloqueante com limite; o chamador fecha o cliente."""
    result = {}

    def run():
        try:
            result["value"] = function()
        except Exception as exc:  # noqa: BLE001
            result["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(max(0.1, timeout))
    if thread.is_alive():
        raise TimeoutError("O servidor MCP excedeu o tempo de ligação.")
    if "error" in result:
        raise result["error"]
    return result.get("value")


class RPCError(RuntimeError):
    def __init__(self, error):
        self.code=error.get("code")
        self.data=error.get("data", {})
        super().__init__(error.get("message", "Erro MCP"))


def redact(value, server):
    # Opções públicas conhecidas não são credenciais: ocultá-las também alteraria
    # valores de enums e descrições nos schemas devolvidos pelo REA.
    public_options={"REA_MCP_INPUT_SCHEMA_PROFILE":{"compact","full"},"REA_MCP_OUTPUT_SCHEMA_PROFILE":{"compact","full","off"}}
    secrets=[v for k,v in server.get("env",{}).items() if not (isinstance(v,str) and v in public_options.get(k,set()))]+list(server.get("headers", {}).values())
    if server.get("auth_mode") == "oauth":
        from mcp_oauth import secret_values
        secrets += secret_values(server)
    secrets += [s[7:] for s in secrets if isinstance(s,str) and s.lower().startswith("bearer ")]
    secrets = [s for s in secrets if isinstance(s,str) and s]
    def clean(item):
        if isinstance(item, str):
            for secret in secrets:
                if len(secret)>=4:
                    item=item.replace(secret,"[credencial oculta]")
                else:
                    # Segredos curtos só são substituídos como token isolado,
                    # para não destruir texto comum (ex.: a letra "a").
                    item=re.sub(r"(?<![A-Za-z0-9])"+re.escape(secret)+r"(?![A-Za-z0-9])","[credencial oculta]",item)
            return item
        if isinstance(item,dict):return {k:clean(v) for k,v in item.items()}
        if isinstance(item,list):return [clean(v) for v in item]
        return item
    return clean(value)


def validate_server(data, old=None):
    result=dict(old or {})
    if isinstance(data.get("id"),str) and re.fullmatch(r"[A-Za-z0-9_-]{1,64}",data["id"]):result["id"]=data["id"]
    for key in ("name","transport","command","args","url","cwd","enabled","approval","env","headers","auth_mode","oauth_client_id","oauth_callback_port","oauth_scope","preset"):
        if key in data:result[key]=data[key]
    result.setdefault("transport","stdio");result.setdefault("args",[])
    result.setdefault("env",{});result.setdefault("headers",{})
    result.setdefault("approval","each");result.setdefault("enabled",True)
    result.setdefault("auth_mode", "manual")
    if result["auth_mode"] not in ("manual", "oauth"):raise ValueError("Autenticação MCP inválida.")
    if result.get("preset") not in (None, "") and (not isinstance(result["preset"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", result["preset"])):raise ValueError("Preset MCP inválido.")
    result["preset"] = result.get("preset") or ""
    if result.get("oauth_scope") is not None:
        if not isinstance(result["oauth_scope"], str) or any(ord(c)<32 for c in result["oauth_scope"]) or len(result["oauth_scope"])>500:raise ValueError("Scope OAuth inválido.")
        result["oauth_scope"] = result["oauth_scope"].strip()
    if result["auth_mode"] == "oauth" and result["transport"] != "http":raise ValueError("OAuth da app requer um servidor HTTP.")
    port = result.get("oauth_callback_port") or 0
    if not isinstance(port, int) or not 0 <= port <= 65535:raise ValueError("Porta de retorno OAuth inválida.")
    if not isinstance(result.get("name"),str) or not result["name"].strip():raise ValueError("Dá um nome ao servidor MCP.")
    if result["transport"] not in ("stdio","http"):raise ValueError("Transporte MCP inválido.")
    if result["approval"] not in ("each","auto"):raise ValueError("Aprovação MCP inválida.")
    if not isinstance(result["args"],list) or any(not isinstance(x,str) for x in result["args"]):raise ValueError("Os argumentos devem ser uma lista JSON de textos.")
    for key in ("env","headers"):
        if not isinstance(result[key],dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in result[key].items()):raise ValueError(key+" deve ser um objeto JSON com valores de texto.")
    for key,value in result["headers"].items():
        if not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+",key) or any(c in value for c in "\r\n"):raise ValueError("Cabeçalho HTTP inválido.")
        reserved=("content-type","accept","mcp-protocol-version","mcp-session-id","mcp-method","mcp-name","host","content-length","connection","transfer-encoding","proxy-connection","upgrade","te","trailer")
        if key.lower() in reserved or key.lower().startswith("mcp-param-"):raise ValueError("Cabeçalho reservado pelo protocolo MCP.")
    if result["transport"]=="stdio":
        if not isinstance(result.get("command"),str) or not result["command"].strip():raise ValueError("Indica o executável do servidor.")
        if result.get("cwd") and not Path(result["cwd"]).is_dir():raise ValueError("A pasta de execução não existe.")
    else:
        parsed=urlsplit(result.get("url", ""))
        if parsed.scheme not in ("http","https") or not parsed.hostname or parsed.username or parsed.password:raise ValueError("URL MCP inválido; usa os cabeçalhos para autenticação.")
        if parsed.scheme=="http" and parsed.hostname not in ("localhost","127.0.0.1","::1"):raise ValueError("Servidores remotos requerem HTTPS; HTTP só é permitido em localhost.")
    return result


def public_server(server):
    keys=("id","name","transport","command","args","url","cwd","enabled","approval","auth_mode","oauth_client_id","oauth_callback_port","oauth_scope","preset")
    result={key:server.get(key) for key in keys}
    result["env_names"]=list(server.get("env",{}))
    result["header_names"]=list(server.get("headers",{}))
    if server.get("auth_mode") == "oauth":
        from mcp_oauth import token_status
        result["oauth"] = token_status(server)
    return result


def header_value(value):
    text=str(value).lower() if isinstance(value,bool) else str(value)
    if text!=text.strip() or any(ord(c)<32 or ord(c)>126 for c in text) or (text.startswith("=?base64?") and text.endswith("?=")):
        return "=?base64?"+base64.b64encode(text.encode()).decode()+"?="
    return text


def header_rules(schema):
    rules=[];names=set()
    def walk(value,path):
        if isinstance(value,list):
            for child in value:walk(child,None)
        elif isinstance(value,dict):
            if "x-mcp-header" in value:
                label=value["x-mcp-header"]
                if not path or not isinstance(label,str) or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+",label) or value.get("type") not in ("integer","boolean","string") or label.lower() in names:
                    raise ValueError("Anotação x-mcp-header inválida ou duplicada.")
                names.add(label.lower());rules.append((path,label,value["type"]))
            for key,child in value.items():
                if key=="properties" and path is not None and isinstance(child,dict):
                    for name,prop in child.items():walk(prop,path+(name,))
                elif isinstance(child,(dict,list)):walk(child,None)
    walk(schema,())
    return rules


class StdioTransport:
    def __init__(self,server,workspace):
        env={**_base_env(),**server.get("env",{}),"STUDIO_WORKSPACE":workspace}
        self.stderr=deque(maxlen=40)
        self.process=subprocess.Popen([server["command"],*server.get("args",[])],cwd=server.get("cwd") or workspace,env=env,
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding="utf-8",errors="strict",bufsize=1,
            creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        self.lines=queue.Queue(maxsize=1000)
        def reader():
            try:
                while True:
                    line=self.process.stdout.readline(4*1024*1024+1)
                    if not line:break
                    if len(line)>4*1024*1024:raise ValueError("Mensagem MCP demasiado grande.")
                    self.lines.put(json.loads(line))
            except Exception as exc:self.lines.put({"transport_error":str(exc)})
            finally:self.lines.put(None)
        self.reader=threading.Thread(target=reader,daemon=True);self.reader.start()
        def read_stderr():
            try:
                for line in self.process.stderr:
                    self.stderr.append(line.rstrip())
            except Exception:pass
        self.stderr_reader=threading.Thread(target=read_stderr,daemon=True);self.stderr_reader.start()

    def _stderr_detail(self):
        text=" ".join(item for item in self.stderr if item).strip()
        return (" " + text[-800:]) if text else ""

    def send(self,message):
        self.process.stdin.write(json.dumps(message,ensure_ascii=True)+"\n");self.process.stdin.flush()

    def exchange(self,message,timeout,headers=None):
        self.send(message)
        if "id" not in message:return None
        deadline=time.monotonic()+timeout
        while True:
            try:item=self.lines.get(timeout=max(0,deadline-time.monotonic()))
            except queue.Empty:
                self.send({"jsonrpc":"2.0","method":"notifications/cancelled","params":{"requestId":message["id"],"reason":"timeout"}})
                raise TimeoutError("O servidor MCP excedeu o tempo de resposta."+self._stderr_detail())
            if item is None:
                try:self.process.wait(timeout=0.5)
                except subprocess.TimeoutExpired:pass
                self.stderr_reader.join(timeout=0.2)
                code=self.process.poll()
                suffix=(" (código "+str(code)+")") if code is not None else ""
                raise RuntimeError("O processo MCP terminou."+suffix+self._stderr_detail())
            if item.get("transport_error"):raise RuntimeError(item["transport_error"]+self._stderr_detail())
            if item.get("id")==message["id"] and ("result" in item or "error" in item):return item
            if "method" in item and "id" in item:
                # Sampling/elicitation/roots não foram anunciados como capacidades.
                self.send({"jsonrpc":"2.0","id":item["id"],"error":{"code":-32601,"message":"Client capability not available"}})

    def close(self):
        if self.process.poll() is None:
            try:self.process.stdin.close();self.process.wait(timeout=0.5)
            except (OSError,subprocess.TimeoutExpired):
                if os.name=="nt":
                    subprocess.run(["taskkill","/PID",str(self.process.pid),"/T","/F"],capture_output=True,timeout=5,creationflags=subprocess.CREATE_NO_WINDOW)
                if self.process.poll() is None:self.process.kill()
                self.process.wait(timeout=5)
        if not self.process.stdin.closed:self.process.stdin.close()
        reader=getattr(self,"reader",None)
        if reader:
            reader.join(timeout=1)
            if not reader.is_alive() and self.process.stdout:self.process.stdout.close()
        stderr_reader=getattr(self,"stderr_reader",None)
        if stderr_reader:
            stderr_reader.join(timeout=1)
            if not stderr_reader.is_alive() and self.process.stderr and not self.process.stderr.closed:
                self.process.stderr.close()


class HTTPTransport:
    def __init__(self,server,workspace):
        self.server=server;self.session=requests.Session();self.session_id=None
    def exchange(self,message,timeout,headers=None):
        protocol=(message.get("params",{}).get("_meta",{}).get("io.modelcontextprotocol/protocolVersion") or self.protocol)
        def post(force=False):
            values={**self.server.get("headers",{}),"Content-Type":"application/json","Accept":"application/json, text/event-stream","MCP-Protocol-Version":protocol}
            if self.server.get("auth_mode") == "oauth":
                from mcp_oauth import access_token
                values["Authorization"] = "Bearer " + access_token(self.server,force_refresh=force)
            if self.session_id and protocol!=MODERN:values["Mcp-Session-Id"]=self.session_id
            if protocol==MODERN:
                values["Mcp-Method"]=message["method"]
                if message.get("params",{}).get("name") is not None:values["Mcp-Name"]=header_value(message["params"]["name"])
                values.update(headers or {})
            return self.session.post(self.server["url"],json=message,headers=values,timeout=(min(timeout,10),timeout),stream=True,allow_redirects=False)
        response=post()
        if response.status_code==401 and self.server.get("auth_mode")=="oauth":
            # O pedido não foi executado: renovar o token e repetir uma vez é seguro.
            response.close()
            response=post(True)
        with response:
            if response.status_code in (401,403):raise PermissionError("Autenticação MCP recusada. Configura as credenciais do servidor.")
            if 300<=response.status_code<400:raise PermissionError("O endpoint MCP redirecionou o pedido; usa o endereço final diretamente.")
            if response.headers.get("Mcp-Session-Id") and protocol!=MODERN:self.session_id=response.headers["Mcp-Session-Id"]
            if "id" not in message and response.status_code in (200,202,204):return None
            if "text/event-stream" in response.headers.get("Content-Type", ""):
                parts=[];deadline=time.monotonic()+timeout
                for line in response.iter_lines(chunk_size=1,decode_unicode=False):
                    if time.monotonic()>deadline:raise TimeoutError("Stream MCP excedeu o tempo de resposta.")
                    line=line.decode("utf-8")
                    if line.startswith("data:"):parts.append(line[5:].lstrip())
                    elif not line and parts:
                        data=json.loads("\n".join(parts));parts=[]
                        if data.get("id")==message["id"]:return data
                raise RuntimeError("O stream MCP terminou sem resposta ao pedido.")
            chunks=[];size=0
            for block in response.iter_content(65536):
                size+=len(block)
                if size>4*1024*1024:raise RuntimeError("Resposta MCP demasiado grande.")
                chunks.append(block)
            try:data=json.loads(b"".join(chunks))
            except ValueError:raise RPCError({"message":"Endpoint MCP devolveu HTTP "+str(response.status_code)+" sem JSON-RPC."})
            if response.status_code>=400 and "error" not in data:raise RPCError({"message":"Endpoint MCP devolveu HTTP "+str(response.status_code)})
            return data
    def close(self):self.session.close()


class MCPClient:
    def __init__(self,server,workspace):
        self.server=server;self.lock=threading.RLock();self.sequence=0;self.version=MODERN;self.definitions={};self.warnings=[]
        self.transport=StdioTransport(server,workspace) if server["transport"]=="stdio" else HTTPTransport(server,workspace)
    def request(self,method,params=None,timeout=20,headers=None,notify=False):
        with self.lock:
            values=dict(params or {})
            if self.version==MODERN:values["_meta"]={"io.modelcontextprotocol/protocolVersion":MODERN,"io.modelcontextprotocol/clientInfo":CLIENT,"io.modelcontextprotocol/clientCapabilities":{}}
            self.sequence+=1
            message={"jsonrpc":"2.0","method":method,"params":values}
            if not notify:message["id"]=self.sequence
            if isinstance(self.transport,HTTPTransport):self.transport.protocol=self.version
            reply=self.transport.exchange(message,timeout,headers)
            if notify:return {}
            if isinstance(reply,dict) and "error" in reply and reply.get("id") in (None,message["id"]):
                raise RPCError(reply["error"])
            if not isinstance(reply,dict) or reply.get("id")!=message["id"]:raise RuntimeError("Resposta MCP sem o identificador esperado.")
            if "error" in reply:raise RPCError(reply["error"])
            if not isinstance(reply.get("result"),dict):raise RuntimeError("Resultado MCP inválido.")
            return reply["result"]
    def _legacy_version(self,supported):
        for version in LEGACY:
            if version in supported:return version
        return None
    def _initialize(self,version):
        initialized=self.request("initialize",{"protocolVersion":version,"capabilities":{},"clientInfo":CLIENT},timeout=10)
        if initialized.get("protocolVersion") not in LEGACY:raise RuntimeError("Versão MCP não suportada pelo cliente.")
        self.version=initialized["protocolVersion"]
        self.request("notifications/initialized",notify=True)
        return self.discover_tools()
    def connect(self):
        try:
            discovered=self.request("server/discover",timeout=3)
        except TimeoutError:
            return self._initialize(LEGACY[0])
        except RPCError as exc:
            # -32020 (HeaderMismatch) e -32021 (MissingRequiredClientCapability)
            # identificam um servidor moderno: não se faz fallback para initialize.
            if exc.code in (-32020,-32021):raise
            if exc.code==-32022:
                supported=exc.data.get("supported",[]) if isinstance(exc.data,dict) else []
                if isinstance(supported,list) and supported:
                    version=self._legacy_version(supported)
                    if version:return self._initialize(version)
                    raise RuntimeError("O servidor não suporta nenhuma versão MCP compatível com esta app.")
            return self._initialize(LEGACY[0])
        supported=discovered.get("supportedVersions",[])
        if isinstance(supported,list):
            if MODERN in supported:return self.discover_tools()
            version=self._legacy_version(supported)
            if version:return self._initialize(version)
        raise RuntimeError("O servidor não suporta nenhuma versão MCP compatível com esta app.")
    def discover_tools(self):
        definitions={};cursor=None;seen=set()
        for page in range(20):
            result=self.request("tools/list",{"cursor":cursor} if cursor else {})
            for item in result.get("tools",[]):
                if isinstance(item,dict) and isinstance(item.get("name"),str) and isinstance(item.get("inputSchema",{}),dict):
                    if self.version==MODERN and isinstance(self.transport,HTTPTransport):
                        try:header_rules(item.get("inputSchema",{}))
                        except ValueError:
                            self.warnings.append("Ferramenta excluída por cabeçalhos inválidos: "+item["name"])
                            continue
                    definitions[item["name"]]=item
                if len(definitions)>500:raise RuntimeError("O servidor excedeu o limite de 500 ferramentas.")
            cursor=result.get("nextCursor")
            if not cursor:break
            if cursor in seen:raise RuntimeError("Paginação MCP repetida.")
            seen.add(cursor)
        else:raise RuntimeError("Demasiadas páginas de ferramentas MCP.")
        self.definitions=definitions
        return list(definitions.values())
    def call(self,name,arguments):
        if name not in self.definitions:raise ValueError("Ferramenta MCP não descoberta.")
        headers={}
        if self.version==MODERN and isinstance(self.transport,HTTPTransport):
            for path,label,kind in header_rules(self.definitions[name].get("inputSchema",{})):
                value=arguments
                for part in path:value=value.get(part) if isinstance(value,dict) else None
                if value is None:continue
                if kind=="integer" and (not isinstance(value,int) or isinstance(value,bool) or abs(value)>2**53-1):raise ValueError("Parâmetro de cabeçalho inteiro inválido.")
                if kind=="boolean" and not isinstance(value,bool):raise ValueError("Parâmetro de cabeçalho booleano inválido.")
                if kind=="string" and not isinstance(value,str):raise ValueError("Parâmetro de cabeçalho de texto inválido.")
                headers["Mcp-Param-"+label]=header_value(value)
        result=self.request("tools/call",{"name":name,"arguments":arguments},timeout=60,headers=headers)
        if result.get("resultType") not in (None,"complete") or result.get("inputRequests"):
            raise RuntimeError("Este servidor requer tarefas assíncronas ou interação adicional ainda não suportadas.")
        # Não enviar grandes imagens/áudio em base64 ao modelo de texto.
        clean=[]
        for part in result.get("content",[]):
            if part.get('type')=='image' and part.get('mimeType') in ('image/png','image/jpeg','image/webp') and isinstance(part.get('data'),str) and len(part['data'])<=2800000:
                clean.append(part)
            elif part.get("type") in ("image","audio"):clean.append({"type":"text","text":"Conteúdo binário omitido: formato ou tamanho não suportado."})
            else:clean.append(part)
        if "content" in result:result["content"]=clean
        return redact(result,self.server)
    def close(self):self.transport.close()


class MCPManager:
    def __init__(self):self.entries={};self.routes={};self.lock=threading.RLock();self.warnings=[]
    def close(self):
        with self.lock:
            for entry in list(self.entries.values()):
                client=entry.get("client")
                if client:
                    try:client.close()
                    except Exception:pass
            self.entries.clear();self.routes.clear()
    def reset(self,server_id):
        with self.lock:
            entry=self.entries.pop(server_id,None)
            client=entry.get("client") if entry else None
            if client:
                try:client.close()
                except Exception:pass
            self.routes={name:route for name,route in self.routes.items() if route[0]!=server_id}
    def tools(self,servers,workspace,force=False,prune=True,connect=True,timeout=None,total_timeout=None):
        timeout=MCP_CONNECT_TIMEOUT if timeout is None else timeout
        total_timeout=MCP_TOTAL_CONNECT_TIMEOUT if total_timeout is None else total_timeout
        with self.lock:
            ids={s.get("id") for s in servers if isinstance(s,dict) and s.get("enabled")}
            for sid in list(self.entries):
                if prune and sid not in ids:self.reset(sid)
            tools=[]
            self.warnings=[]
            if prune:self.routes={}
            deadline=time.monotonic()+total_timeout if connect else 0
            limit_reached=False
            for raw in servers:
                if not isinstance(raw,dict) or not raw.get("enabled") or not raw.get("id"):continue
                sid=raw["id"]
                fingerprint=hashlib.sha256(json.dumps([raw,workspace],sort_keys=True,default=str).encode()).hexdigest()
                entry=self.entries.get(sid)
                if not connect:
                    if not entry or entry.get("error"):continue
                elif force or not entry or entry["fingerprint"]!=fingerprint or (entry.get("error") and time.monotonic()-entry["updated"]>15):
                    self.reset(sid);entry={"fingerprint":fingerprint,"updated":time.monotonic(),"error":"","client":None,"tools":[]};self.entries[sid]=entry
                    try:
                        server=validate_server(raw)
                        client=MCPClient(server,workspace);entry["client"]=client
                        remaining=deadline-time.monotonic()
                        if remaining<=0:raise TimeoutError("O tempo total de ligação aos servidores MCP terminou.")
                        entry["tools"]=_run_with_timeout(client.connect,min(timeout,remaining))
                    except Exception as exc:
                        entry["error"]=redact(str(exc),raw)
                        client=entry.get("client");entry["client"]=None
                        if client:
                            try:client.close()
                            except Exception:pass
                elif not entry.get("error") and time.monotonic()-entry["updated"]>60:
                    remaining=deadline-time.monotonic()
                    if remaining>0:
                        try:entry["tools"]=_run_with_timeout(entry["client"].discover_tools,min(timeout,remaining));entry["updated"]=time.monotonic()
                        except Exception as exc:
                            entry["error"]=redact(str(exc),raw);entry["tools"]=[]
                            client=entry.get("client");entry["client"]=None
                            if client:
                                try:client.close()
                                except Exception:pass
                if entry.get("error"):continue
                for item in entry["tools"]:
                    if len(tools)>=MAX_TOTAL_TOOLS:
                        limit_reached=True;break
                    schema=item.get("inputSchema") or {"type":"object","properties":{}}
                    try:encoded=json.dumps(schema,ensure_ascii=False)
                    except (TypeError,ValueError):continue
                    if len(encoded)>MAX_TOOL_SCHEMA_CHARS:
                        self.warnings.append("Ferramenta "+raw["name"]+"/"+str(item.get("name"))+" ignorada: schema demasiado grande.")
                        continue
                    alias="mcp_"+hashlib.sha256((sid+":"+item["name"]).encode()).hexdigest()[:16]+"_"+re.sub("[^A-Za-z0-9_]","_",item["name"])[:30]
                    self.routes[alias]=(sid,item["name"])
                    function={"name":alias,"description":("MCP / "+raw["name"]+" / "+item["name"]+": "+item.get("description", ""))[:3000],"parameters":schema}
                    tools.append({"type":"function","function":redact(function,raw)})
                if limit_reached:
                    self.warnings.append("Limite total de "+str(MAX_TOTAL_TOOLS)+" ferramentas MCP atingido; algumas foram omitidas.")
                    break
            return tools
    def status(self,servers):
        with self.lock:
            result=[]
            for server in servers:
                if not isinstance(server,dict) or not server.get("id"):continue
                entry=self.entries.get(server["id"],{})
                result.append({**public_server(server),"connected":bool(entry.get("client") and not entry.get("error")),
                               "tool_count":len(entry.get("tools",[])),"error":entry.get("error",""),
                               "protocol":getattr(entry.get("client"),"version",None),
                               "service_verified":entry.get("service_verified",False),"service_error":entry.get("service_error","")})
            return result
    def call(self,alias,arguments,servers,approve):
        with self.lock:
            route=self.routes.get(alias)
            if not route:raise ValueError("Ferramenta MCP indisponível; atualiza o catálogo.")
            sid,name=route
            server=next((s for s in servers if isinstance(s,dict) and s.get("id")==sid and s.get("enabled")),None)
            if not server:raise ValueError("O servidor MCP está desligado.")
            entry=self.entries.get(sid)
            client=entry.get("client") if entry else None
            if not client:raise ValueError("O servidor MCP não está ligado; usa Testar ou tenta novamente.")
        # A aprovação e a chamada correm fora do lock do gestor: o catálogo
        # pode ser atualizado enquanto o utilizador decide.
        if server.get("approval","each")!="auto" and not approve(server,name,arguments):raise PermissionError("Chamada MCP recusada pelo utilizador.")
        with self.lock:
            entry=self.entries.get(sid)
            if not entry or entry.get("client") is not client:
                raise ValueError("O servidor MCP foi alterado; atualiza o catálogo.")
        try:return client.call(name,arguments)
        except Exception as exc:
            # Não repetir ferramentas após erros: podem já ter alterado o serviço externo.
            raise RuntimeError(redact(str(exc),server)) from None
