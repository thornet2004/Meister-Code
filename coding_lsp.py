"""LSP stdio local por workspace: diagnósticos e navegação para as linguagens da tabela SERVERS."""
from __future__ import annotations
import hashlib,json,os,queue,shutil,subprocess,tempfile,threading,time
from pathlib import Path
from urllib.parse import unquote
from urllib.parse import urlsplit
from urllib.request import url2pathname
import config

def uri_key(uri):
    uri=unquote(uri)
    return uri.casefold() if os.name=='nt' else uri

# Servidores conhecidos. "node": ficheiro de entrada dentro de Ferramentas/_Runtime/lsp/node_modules
# (instalado com a app). "path": executável que se procura no PATH; "tool": pasta em Ferramentas onde a lista
# de ferramentas da app o instala (clangd e rust-analyzer), vista primeiro.
# "languages": extensão -> languageId do protocolo.
SERVERS={
 'python':dict(label='Python · Pyright',node='pyright/langserver.index.js',args=['--stdio'],languages={'.py':'python','.pyi':'python'}),
 'typescript':dict(label='JavaScript/TypeScript',node='typescript-language-server/lib/cli.mjs',args=['--stdio'],languages={'.js':'javascript','.jsx':'javascriptreact','.ts':'typescript','.tsx':'typescriptreact','.mjs':'javascript','.cjs':'javascript'}),
 'html':dict(label='HTML',node='vscode-langservers-extracted/bin/vscode-html-language-server',args=['--stdio'],languages={'.html':'html','.htm':'html'}),
 'css':dict(label='CSS/SCSS/Less',node='vscode-langservers-extracted/bin/vscode-css-language-server',args=['--stdio'],languages={'.css':'css','.scss':'scss','.less':'less'}),
 'json':dict(label='JSON',node='vscode-langservers-extracted/bin/vscode-json-language-server',args=['--stdio'],languages={'.json':'json','.jsonc':'jsonc'}),
 'bash':dict(label='Bash',node='bash-language-server/out/cli.js',args=['start'],languages={'.sh':'shellscript','.bash':'shellscript'}),
 'yaml':dict(label='YAML',node='yaml-language-server/bin/yaml-language-server',args=['--stdio'],languages={'.yaml':'yaml','.yml':'yaml'}),
 'php':dict(label='PHP · Intelephense',node='intelephense/lib/intelephense.js',args=['--stdio'],languages={'.php':'php'}),
 'rust':dict(label='Rust · rust-analyzer',path='rust-analyzer',tool='RustAnalyzer',args=[],languages={'.rs':'rust'}),
 'cpp':dict(label='C/C++ · clangd',path='clangd',tool='Clangd',args=[],languages={'.c':'c','.h':'c','.cpp':'cpp','.cc':'cpp','.cxx':'cpp','.hpp':'cpp','.hh':'cpp'}),
}
LANGUAGE_IDS={ext:language for server in SERVERS.values() for ext,language in server['languages'].items()}
KIND_BY_EXTENSION={ext:kind for kind,server in SERVERS.items() for ext in server['languages']}
SUPPORTED='Python, JavaScript/TypeScript, HTML, CSS, JSON, Bash, YAML e PHP; C/C++ e Rust com o clangd e o rust-analyzer instalados pela lista de ferramentas (ou no PATH)'
_ENV={'PATH','PATHEXT','SYSTEMROOT','WINDIR','COMSPEC','TEMP','TMP','APPDATA','LOCALAPPDATA','USERPROFILE','HOME','PROGRAMFILES','PROGRAMFILES(X86)',
      'GOPATH','GOROOT','GOCACHE','GOMODCACHE','GOFLAGS','CARGO_HOME','RUSTUP_HOME','RUSTUP_TOOLCHAIN'}

def limits(kind):
    """O que este servidor não verifica, para uma lista vazia não ser lida como «sem erros»."""
    if kind=='bash' and not shutil.which('shellcheck'):return 'O servidor Bash só devolve diagnósticos com o shellcheck instalado e no PATH, e não está: uma lista vazia NÃO significa que o script esteja correto. Símbolos, definições e referências funcionam.'
    if kind=='html':return 'O servidor HTML valida o CSS e o JavaScript embutidos, não a estrutura do HTML (etiquetas por fechar não são assinaladas).'
    if kind=='json':return 'Sintaxe JSON e esquemas locais. Esquemas indicados por endereço http(s) não são descarregados nem aplicados.'
    if kind=='yaml':return 'Sintaxe YAML. O catálogo de esquemas da Internet está desligado: não há validação por esquema.'
    return ''

def kind_for(path):
    """Servidor que trata este ficheiro, ou None."""
    return KIND_BY_EXTENSION.get(Path(path).suffix.lower())

class Client:
    def __init__(self,command,workspace,kind):
        self.workspace=Path(workspace).resolve();self.kind=kind
        self.write_lock=threading.Lock();self.pending={};self.diagnostics={};self.documents={};self.seq=0;self.closed=False
        self.events=threading.Condition();self.errors=[]
        env={k:v for k,v in os.environ.items() if k.upper() in _ENV}
        self.process=subprocess.Popen(command,cwd=self.workspace,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        threading.Thread(target=self._reader,daemon=True).start()
        threading.Thread(target=self._stderr,daemon=True).start()
        try:
            options=dict(hostInfo='studio-media')
            if kind=='typescript':options['tsserver']={'path':str(Path(command[1]).parents[2]/'typescript/lib/tsserver.js')}
            # JSON: esquemas http(s) não são descarregados pelo servidor (o pedido vem ter à app, que não responde).
            if kind=='json':options.update(handledSchemaProtocols=['file'],provideFormatter=False)
            if kind=='html':options.update(embeddedLanguages={'css':True,'javascript':True},provideFormatter=False)
            if kind=='php':
                storage=Path(tempfile.gettempdir())/'meistercode-lsp'/'intelephense';storage.mkdir(parents=True,exist_ok=True)
                options.update(storagePath=str(storage),globalStoragePath=str(storage),clearCache=False)
            self.request('initialize',dict(processId=os.getpid(),rootUri=self.workspace.as_uri(),workspaceFolders=[dict(uri=self.workspace.as_uri(),name=self.workspace.name)],capabilities=dict(workspace=dict(configuration=True,workspaceFolders=True),textDocument=dict(publishDiagnostics=dict(versionSupport=True),documentSymbol=dict(hierarchicalDocumentSymbolSupport=True))),initializationOptions=options),20)
            self.notify('initialized',{})
            self.notify('workspace/didChangeConfiguration',{'settings':self.settings()})
        except Exception:self.close();raise
    def settings(self):
        return {'python':{'analysis':{'diagnosticMode':'openFilesOnly','autoSearchPaths':True,'typeCheckingMode':'basic','exclude':['**/node_modules','**/.venv','**/Ferramentas','**/build','**/dist']}},'javascript':{'validate':{'enable':True}},'typescript':{'validate':{'enable':True}},
                'css':{'validate':True},'scss':{'validate':True},'less':{'validate':True},'html':{'validate':{'scripts':True,'styles':True}},
                'json':{'validate':{'enable':True},'schemas':[],'format':{'enable':False}},
                # sem pedidos à rede nem telemetria: nada de catálogo de esquemas, nada de Application Insights
                'yaml':{'validate':True,'schemaStore':{'enable':False},'schemas':{},'format':{'enable':False}},'redhat':{'telemetry':{'enabled':False}},
                'intelephense':{'telemetry':{'enabled':False},'files':{'exclude':['**/.git/**','**/node_modules/**','**/vendor/**/{Tests,tests}/**','**/Ferramentas/**']}},
                'telemetry':{'telemetryLevel':'off','enableTelemetry':False},'http':{'proxy':'','proxyStrictSSL':True}}
    def send(self,value):
        data=json.dumps(value,ensure_ascii=False).encode('utf-8')
        with self.write_lock:
            if self.closed:raise RuntimeError('Servidor LSP fechado.')
            self.process.stdin.write(('Content-Length: '+str(len(data))+'\r\n\r\n').encode()+data);self.process.stdin.flush()
    def notify(self,method,params):self.send(dict(jsonrpc='2.0',method=method,params=params))
    def request(self,method,params,timeout=15):
        with self.write_lock:self.seq+=1;key=self.seq;response=queue.Queue(maxsize=1);self.pending[key]=response
        try:
            self.send(dict(jsonrpc='2.0',id=key,method=method,params=params))
            try:message=response.get(timeout=timeout)
            except queue.Empty:raise TimeoutError('O servidor LSP não respondeu a '+method+'.') from None
            if 'error' in message:raise RuntimeError(str(message['error'].get('message','Erro LSP')))
            return message.get('result')
        finally:self.pending.pop(key,None)
    def _stderr(self):
        for line in iter(self.process.stderr.readline,b''):
            self.errors.append(line.decode('utf-8',errors='replace')[:500]);self.errors=self.errors[-8:]
    def _reader(self):
        try:
            while not self.closed:
                headers={}
                while True:
                    line=self.process.stdout.readline(8192)
                    if not line:return
                    if line in (b'\r\n',b'\n'):break
                    name,_,value=line.decode('ascii').partition(':');headers[name.lower()]=value.strip()
                size=int(headers.get('content-length','0'))
                if size<1 or size>16*1024*1024:raise ValueError('Mensagem LSP inválida.')
                raw=bytearray()
                while len(raw)<size:
                    chunk=self.process.stdout.read(size-len(raw))
                    if not chunk:return
                    raw.extend(chunk)
                msg=json.loads(raw)
                if 'method' not in msg:
                    pending=self.pending.get(msg.get('id'))
                    if pending:pending.put_nowait(msg)
                elif 'id' in msg:
                    method=msg['method'];params=msg.get('params',{})
                    if method=='workspace/configuration':
                        result=[]
                        for item in params.get('items',[]):
                            value=self.settings()
                            for part in item.get('section','').split('.'):
                                if part:value=value.get(part,{}) if isinstance(value,dict) else {}
                            result.append(value)
                    elif method=='workspace/workspaceFolders':result=[dict(uri=self.workspace.as_uri(),name=self.workspace.name)]
                    elif method=='workspace/applyEdit':result={'applied':False,'failureReason':'Usar as ferramentas de edição com checkpoint da app.'}
                    else:result=None
                    self.send(dict(jsonrpc='2.0',id=msg['id'],result=result))
                elif msg['method']=='textDocument/publishDiagnostics':
                    params=msg.get('params',{})
                    with self.events:self.diagnostics[uri_key(params['uri'])]=(time.monotonic(),params);self.events.notify_all()
        except Exception as exc:self.errors.append(str(exc))
        finally:
            for pending in list(self.pending.values()):
                try:pending.put_nowait({'error':{'message':'O servidor LSP terminou.'}})
                except queue.Full:pass
    def diagnose(self,path,timeout=12):
        p=Path(path).resolve();uri=p.as_uri();key=uri_key(uri);data=p.read_bytes()
        if len(data)>2*1024*1024:raise ValueError('Diagnósticos limitados a ficheiros até 2 MiB.')
        text=data.decode('utf-8-sig');sha=hashlib.sha256(data).hexdigest()
        previous=self.documents.get(key)
        if previous and previous[0]==sha and key in self.diagnostics:
            stamp,cached=self.diagnostics[key]
            if cached.get('version',previous[1])==previous[1] and time.monotonic()-stamp>=1.2:return self._result(p,sha,cached)
        same=previous and previous[0]==sha
        version=previous[1] if same else (previous[1]+1) if previous else 1
        self.documents[key]=(sha,version);started=time.monotonic()
        if not same:self.diagnostics.pop(key,None)
        if previous and not same:self.notify('textDocument/didChange',dict(textDocument=dict(uri=uri,version=version),contentChanges=[dict(text=text)]))
        elif not previous:
            language=LANGUAGE_IDS.get(p.suffix.lower(),'plaintext')
            self.notify('textDocument/didOpen',dict(textDocument=dict(uri=uri,languageId=language,version=version,text=text)))
        with self.events:
            while time.monotonic()-started<timeout:
                value=self.diagnostics.get(key)
                if value:
                    stamp,params=value
                    if params.get('version',version)==version and time.monotonic()-stamp>=1.2 and time.monotonic()-started>=2:
                        return self._result(p,sha,params)
                if self.process.poll() is not None:raise RuntimeError('O servidor LSP terminou: '+' '.join(self.errors)[-1000:])
                self.events.wait(.15)
        return dict(path=str(p),sha256=sha,server=self.kind,status='pending',diagnostics=[],message='Análise ainda em curso; volta a consultar os diagnósticos.')
    def _result(self,path,sha,params):
        result=[]
        for d in params.get('diagnostics',[])[:200]:
            start=d.get('range',{}).get('start',{})
            result.append(dict(line=start.get('line',0)+1,column=start.get('character',0)+1,severity={1:'error',2:'warning',3:'information',4:'hint'}.get(d.get('severity'),'information'),message=d.get('message',''),source=d.get('source',''),code=d.get('code')))
        return dict(path=str(path),sha256=sha,server=self.kind,status='complete',diagnostics=result,truncated=len(params.get('diagnostics',[]))>200)
    def navigate(self,path,action,line=1,column=1):
        p=Path(path).resolve()
        if not p.is_relative_to(self.workspace):raise ValueError('Ficheiro fora do workspace LSP.')
        analysis=self.diagnose(p,5) # Aguarda a primeira análise para resolver imports entre ficheiros.
        methods={'definitions':'textDocument/definition','references':'textDocument/references','symbols':'textDocument/documentSymbol'}
        if action not in methods:raise ValueError('Navegação LSP inválida.')
        params={'textDocument':{'uri':p.as_uri()}}
        if action!='symbols':
            lines=p.read_text(encoding='utf-8-sig').splitlines();line=int(line);column=int(column)
            if line<1 or line>len(lines) or column<1 or column>len(lines[line-1].encode('utf-16-le'))//2+1:raise ValueError('Linha/coluna UTF-16 inválida.')
            params['position']={'line':line-1,'character':column-1}
        if action=='references':params['context']={'includeDeclaration':True}
        raw=self.request(methods[action],params,20);results=[];excluded=0
        def location(uri,position,**extra):
            nonlocal excluded
            parsed=urlsplit(uri or '')
            if parsed.scheme!='file' or parsed.netloc not in ('','localhost'):excluded+=1;return
            uri_path=parsed.path
            if os.name=='nt' and len(uri_path)>5 and uri_path[0]=='/' and uri_path[1].isalpha() and uri_path[2:5].lower()=='%3a':uri_path=uri_path[:2]+':'+uri_path[5:]
            target=Path(url2pathname(uri_path)).resolve()
            if not target.is_relative_to(self.workspace):excluded+=1;return
            results.append(dict(path=str(target),line=position.get('line',0)+1,column=position.get('character',0)+1,**extra))
        if action=='symbols':
            def flatten(items,parent=''):
                for item in items or []:
                    if len(results)>=300:return
                    pos=(item.get('selectionRange') or item.get('range') or item.get('location',{}).get('range') or {}).get('start',{})
                    location(item.get('location',{}).get('uri',p.as_uri()),pos,name=item.get('name',''),kind=item.get('kind'),container=parent or item.get('containerName',''))
                    flatten(item.get('children'),item.get('name',''))
            flatten(raw)
        else:
            for item in ([raw] if isinstance(raw,dict) else raw or [])[:300]:
                position=(item.get('targetSelectionRange') or item.get('targetRange') or item.get('range') or {}).get('start',{})
                location(item.get('targetUri') or item.get('uri'),position)
        return dict(status='complete',analysis_status=analysis['status'],server=self.kind,action=action,results=results,excluded_outside_workspace=excluded,column_encoding='utf-16',truncated=len(results)>=300)
    def close(self):
        if self.closed:return
        self.closed=True
        try:self.process.stdin.close()
        except OSError:pass
        if self.process.poll() is None:
            if os.name=='nt':subprocess.run(['taskkill','/PID',str(self.process.pid),'/T','/F'],capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=5)
            else:self.process.terminate()
        try:self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:self.process.kill()

class LanguageServers:
    def __init__(self):self.clients={};self.lock=threading.RLock()
    def locations(self):
        import folder_tools
        root=config.application_root()/'Ferramentas';node=folder_tools.node_runtime(root);modules=root/'_Runtime/lsp/node_modules'
        return node,{kind:modules/server['node'] for kind,server in SERVERS.items() if 'node' in server}
    def tool_binary(self,server):
        """Executável instalado pela lista de ferramentas da app em Ferramentas/<pasta>/app, se existir."""
        if 'tool' not in server:return None
        folder=config.application_root()/'Ferramentas'/server['tool']/'app'
        try:matches=sorted(folder.rglob(server['path']+'.exe')) if folder.is_dir() else []
        except OSError:matches=[]
        return str(matches[0]) if matches else None
    def command(self,kind):
        """Linha de comando do servidor, ou None se não estiver instalado."""
        server=SERVERS[kind]
        if 'node' in server:
            node,paths=self.locations()
            return [str(node),str(paths[kind]),*server['args']] if node.is_file() and paths[kind].is_file() else None
        found=self.tool_binary(server) or shutil.which(server['path'])
        return [found,*server['args']] if found else None
    def installed_extensions(self):
        """Extensões com servidor pronto a usar (para os diagnósticos automáticos depois de editar)."""
        return {ext for kind,server in SERVERS.items() if self.command(kind) for ext in server['languages']}
    def status(self):
        return [dict(name=kind,label=server['label'],source='bundled' if 'node' in server else 'path',executable=server.get('path',''),extensions=sorted(server['languages']),installed=self.command(kind) is not None,connected=any(c.kind==kind and c.process.poll() is None for c in self.clients.values())) for kind,server in SERVERS.items()]
    def diagnose(self,workspace,path,timeout=12):
        return self._query(workspace,path,lambda client,p:client.diagnose(p,timeout))
    def navigate(self,workspace,path,action,line=1,column=1):
        return self._query(workspace,path,lambda client,p:client.navigate(p,action,line,column))
    def _query(self,workspace,path,callback):
        p=Path(path).resolve();kind=kind_for(p)
        if not p.is_relative_to(Path(workspace).resolve()):raise ValueError('Ficheiro fora do workspace LSP.')
        if not kind:return dict(path=str(p),status='unsupported',diagnostics=[],message='LSP disponível para '+SUPPORTED+'.')
        with self.lock:
            command=self.command(kind)
            if not command:
                server=SERVERS[kind]
                message='Servidor LSP não instalado.' if 'node' in server else ('Servidor LSP não instalado: instala «'+server['label'].split(' · ')[1]+'» em Ferramentas → Atualizar ferramentas (ou põe '+server['path']+' no PATH) para ter '+server['label'].split(' ·')[0]+'.' if 'tool' in server else 'Servidor LSP não encontrado: instala '+server['path']+' e põe-no no PATH para ter '+server['label'].split(' ·')[0]+'.')
                return dict(path=str(p),status='unavailable',diagnostics=[],message=message)
            key=(str(Path(workspace).resolve()),kind)
            client=self.clients.get(key)
            if not client or client.process.poll() is not None:
                # Limit background processes when switching projects or languages repeatedly.
                if len(self.clients)>=6:
                    old=next(iter(self.clients));self.clients.pop(old).close()
                client=Client(command,workspace,kind);self.clients[key]=client
            result=callback(client,p);note=limits(kind)
            if note and isinstance(result,dict) and 'diagnostics' in result:result['limits']=note
            return result
    def close(self):
        with self.lock:
            for client in self.clients.values():client.close()
            self.clients.clear()
