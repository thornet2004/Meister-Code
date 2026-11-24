import json
import importlib.util
import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import api
import config
from mcp_bridge import MCPClient,MCPManager,validate_server,redact,header_value,header_rules
ROOT=Path(__file__).resolve().parents[1]

class MCPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root=Path(self.temp.name).resolve();self.clients=[]
    def tearDown(self):
        for client in self.clients:client.close()
        self.temp.cleanup()
    def server(self,legacy=False,approval='auto'):
        return validate_server({'id':'test','name':'Local demo','transport':'stdio','command':sys.executable,'args':['-u',str(ROOT/'mcp_demo.py')]+(['--legacy'] if legacy else []),'enabled':True,'approval':approval})
    def test_stdio_modern_and_legacy(self):
        for legacy in (False,True):
            client=MCPClient(self.server(legacy),str(self.root));self.clients.append(client)
            definitions=client.connect()
            self.assertEqual(len(definitions),2)
            self.assertEqual(client.version,'2025-11-25' if legacy else '2026-07-28')
            result=client.call('demo_echo',{'texto':'Olá MCP'})
            self.assertEqual(result['structuredContent']['texto'],'Olá MCP')
    def test_permission_disable_and_process_cleanup(self):
        manager=MCPManager();self.clients.append(manager)
        server=self.server(approval='each')
        tools=manager.tools([server],str(self.root))
        alias=next(t['function']['name'] for t in tools if t['function']['name'].endswith('_demo_echo'))
        with self.assertRaises(PermissionError):manager.call(alias,{'texto':'x'},[server],lambda *args:False)
        result=manager.call(alias,{'texto':'approved'},[server],lambda *args:True)
        self.assertEqual(result['structuredContent']['texto'],'approved')
        process=manager.entries['test']['client'].transport.process
        self.assertEqual(manager.tools([{**server,'enabled':False}],str(self.root)),[])
        self.assertIsNotNone(process.poll())
    def test_config_credentials_not_returned_and_edit_preserves_them(self):
        settings=self.root/'settings';settings.mkdir()
        with patch('config.config_dir',return_value=settings),patch('config.application_root',return_value=self.root/'app'):
            app=api.Api();self.clients.append(app._mcp)
            server={**self.server(),'headers':{'Authorization':'Bearer private-test-value'},'env':{'TEST_KEY':'private-environment-value'},'enabled':False}
            server.pop('id')
            result=app.save_mcp_server(server)
            self.assertTrue(result['ok'],result)
            encoded=json.dumps(result)
            self.assertNotIn('private-test-value',encoded);self.assertNotIn('private-environment-value',encoded)
            sid=result['servers'][0]['id']
            self.assertTrue(app.save_mcp_server({'id':sid,'name':'Renamed'})['ok'])
            self.assertEqual(config.load_config()['mcp_servers'][0]['env']['TEST_KEY'],'private-environment-value')
            self.assertTrue(app.remove_mcp_server(sid)['ok']);self.assertEqual(config.load_config()['mcp_servers'],[])
    def test_model_discovers_and_calls_mcp_through_chat(self):
        settings=self.root/'settings';settings.mkdir()
        with patch('config.config_dir',return_value=settings),patch('config.application_root',return_value=self.root/'app'):
            cfg=config.load_config();cfg['providers']=[{'id':'fake','kind':'openrouter','models':[{'id':'text','type':'chat'}]}];cfg['chat']={'provider_id':'fake','model_id':'text'};cfg['mcp_servers']=[self.server()];config.save_config(cfg)
            app=api.Api();self.clients.append(app._mcp);calls=[]
            def adapter(provider,model,messages,tools,params):
                calls.append(messages[:])
                if len(calls)==1:
                    alias=next(t['function']['name'] for t in tools if t['function']['name'].endswith('_demo_echo'))
                    raw={'role':'assistant','content':None,'tool_calls':[{'id':'mcp1','type':'function','function':{'name':alias,'arguments':'{"texto":"Chat MCP"}'}}]}
                    return {'content':'','raw_message':raw,'tool_calls':[{'id':'mcp1','name':alias,'arguments':{'texto':'Chat MCP'}}]}
                self.assertTrue(any(m['role']=='tool' and 'Chat MCP' in m['content'] for m in messages))
                return {'content':'MCP funcionou.','tool_calls':[]}
            with patch('providers.get_chat_adapter',return_value=adapter),patch.object(app,'_ask_approval',side_effect=AssertionError('Auto MCP must not prompt')):
                result=app.chat('Usa a demonstração MCP')
            self.assertTrue(result['ok'],result)
            meta,_=config.resolve_context(config.load_config());history=json.loads((meta/'conversation.json').read_text(encoding='utf-8'))
            self.assertEqual(history[-1]['steps'][0]['kind'],'mcp')
    def test_http_sse_auth_and_parameter_headers(self):
        token='local-private-token';failures=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                if self.headers.get('Authorization')!='Bearer '+token:
                    self.send_response(401);self.end_headers();return
                message=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                method=message['method'];params=message.get('params',{})
                if method=='server/discover':result={'supportedVersions':['2026-07-28'],'capabilities':{'tools':{}}}
                elif method=='tools/list':result={'tools':[{'name':'web_echo','description':'HTTP test','inputSchema':{'type':'object','properties':{'regiao':{'type':'string','x-mcp-header':'Region'}}}}]}
                elif method=='tools/call':
                    if self.headers.get('Mcp-Param-Region')!=header_value(params['arguments']['regiao']):failures.append('parameter header mismatch')
                    if self.headers.get('Mcp-Method')!='tools/call':failures.append('method header missing')
                    result={'content':[{'type':'text','text':self.headers['Authorization']}],'structuredContent':params['arguments']}
                else:result={}
                response={'jsonrpc':'2.0','id':message['id'],'result':result}
                data=('event: message\ndata: '+json.dumps(response,ensure_ascii=False)+'\n\n').encode() if method=='tools/call' else json.dumps(response).encode()
                self.send_response(200);self.send_header('Content-Type','text/event-stream' if method=='tools/call' else 'application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        http=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=http.serve_forever,daemon=True).start()
        try:
            server=validate_server({'id':'http','name':'HTTP local','transport':'http','url':f'http://127.0.0.1:{http.server_port}/mcp','headers':{'Authorization':'Bearer '+token}})
            client=MCPClient(server,str(self.root));self.clients.append(client);client.connect()
            result=client.call('web_echo',{'regiao':'Lisboa á'})
            self.assertEqual(result['structuredContent']['regiao'],'Lisboa á');self.assertNotIn(token,json.dumps(result));self.assertEqual(failures,[])
            wrong=MCPClient({**server,'headers':{}},str(self.root));self.clients.append(wrong)
            with self.assertRaises(PermissionError):wrong.connect()
        finally:http.shutdown();http.server_close()
    def test_parameter_header_schema_validation(self):
        self.assertEqual(header_rules({'type':'object','properties':{'area':{'type':'string','x-mcp-header':'Region'}}}),[(('area',),'Region','string')])
        for schema in ({'properties':{'x':{'type':'number','x-mcp-header':'X'}}},{'oneOf':[{'properties':{'x':{'type':'string','x-mcp-header':'X'}}}]},{'properties':{'x':{'type':'string','x-mcp-header':'Same'},'y':{'type':'integer','x-mcp-header':'same'}}}):
            with self.assertRaises(ValueError):header_rules(schema)

    def test_validation_rejects_remote_plain_http_and_header_injection(self):
        for data in ({'url':'http://example.com/mcp'},{'url':'https://example.com/mcp','headers':{'Authorization':'x\r\ny'}}):
            with self.assertRaises(ValueError):validate_server({'name':'Invalid','transport':'http',**data})
        for header in ("Host","Content-Length","Connection","Transfer-Encoding"):
            with self.assertRaises(ValueError):
                validate_server({'name':'Invalid','transport':'http','url':'https://example.com/mcp','headers':{header:'x'}})

    def test_stdio_receives_only_allowlisted_and_configured_environment(self):
        code="import os,sys; print('secret='+str(os.environ.get('STUDIO_TEST_SECRET')),file=sys.stderr); print('allowed='+str(os.environ.get('ALLOWED_TEST')),file=sys.stderr); print('workspace='+str(os.environ.get('STUDIO_WORKSPACE')),file=sys.stderr); sys.exit(2)"
        server=validate_server({"id":"env","name":"Env","transport":"stdio","command":sys.executable,"args":["-c",code],"env":{"ALLOWED_TEST":"ok"},"enabled":True,"approval":"auto"})
        client=MCPClient(server,str(self.root))
        try:
            with patch.dict(os.environ,{"STUDIO_TEST_SECRET":"topsecret"}):
                with self.assertRaises(RuntimeError) as error:
                    client.connect()
            text=str(error.exception)
            self.assertIn("secret=None",text)
            self.assertIn("allowed=ok",text)
            self.assertIn("workspace="+str(self.root),text)
            self.assertNotIn("topsecret",text)
        finally:
            client.close()

    def test_tool_and_schema_caps(self):
        manager=MCPManager();self.clients.append(manager)
        server={"id":"cap","name":"Cap","enabled":True}
        big={"name":"big","description":"x","inputSchema":{"type":"object","properties":{"x":{"type":"string","description":"x"*30000}}}}
        many=[{"name":"t"+str(i),"description":"x","inputSchema":{"type":"object","properties":{}}} for i in range(205)]
        manager.entries["cap"]={"fingerprint":"","updated":0,"error":"","client":None,"tools":[big]+many}
        tools=manager.tools([server],str(self.root),connect=False)
        self.assertEqual(len(tools),200)
        self.assertTrue(any("schema demasiado grande" in item for item in manager.warnings))
        self.assertTrue(any("Limite total" in item for item in manager.warnings))

    def test_approval_does_not_block_status(self):
        manager=MCPManager();self.clients.append(manager)
        server=self.server(approval='each')
        tools=manager.tools([server],str(self.root))
        alias=next(t['function']['name'] for t in tools if t['function']['name'].endswith('_demo_echo'))
        started=threading.Event();release=threading.Event();result={}
        def approve(*args):
            started.set();return release.wait(2)
        def call():
            try:result["value"]=manager.call(alias,{"texto":"x"},[server],approve)
            except Exception as exc:result["error"]=exc
        thread=threading.Thread(target=call);thread.start()
        self.assertTrue(started.wait(2))
        began=time.monotonic();status=manager.status([server])
        self.assertLess(time.monotonic()-began,1)
        self.assertTrue(status[0]["connected"])
        release.set();thread.join(5)
        self.assertNotIn("error",result)
        self.assertEqual(result["value"]["structuredContent"]["texto"],"x")

    def test_hanging_server_is_bounded_in_automatic_mode(self):
        server=validate_server({"id":"hang-auto","name":"Hang auto","transport":"stdio","command":sys.executable,"args":["-c","import time; time.sleep(60)"],"enabled":True,"approval":"auto"})
        manager=MCPManager();self.clients.append(manager)
        started=time.monotonic()
        with patch("mcp_bridge.MCP_CONNECT_TIMEOUT",1),patch("mcp_bridge.MCP_TOTAL_CONNECT_TIMEOUT",1.5):
            self.assertEqual(manager.tools([server],str(self.root)),[])
        self.assertLess(time.monotonic()-started,5)
        self.assertIn("tempo",manager.entries["hang-auto"]["error"].lower())

    def test_catalog_does_not_spawn_hanging_server(self):
        server=validate_server({"id":"hang","name":"Hang","transport":"stdio","command":sys.executable,"args":["-c","import time; time.sleep(60)"],"enabled":True,"approval":"auto"})
        manager=MCPManager();self.clients.append(manager)
        started=time.monotonic()
        self.assertEqual(manager.tools([server],str(self.root),connect=False),[])
        self.assertLess(time.monotonic()-started,1)
        self.assertEqual(manager.entries,{})

    def test_unexpected_exit_includes_stderr(self):
        server=validate_server({"id":"stderr","name":"Stderr","transport":"stdio","command":sys.executable,"args":["-c","import sys; print('falha explicita', file=sys.stderr); sys.exit(3)"],"enabled":True,"approval":"auto"})
        client=MCPClient(server,str(self.root))
        try:
            with self.assertRaises(RuntimeError) as error:
                client.connect()
            self.assertIn("falha explicita",str(error.exception))
            self.assertIn("código 3",str(error.exception))
        finally:
            client.close()

    def test_disabled_server_can_be_tested_and_demo_is_idempotent(self):
        settings=self.root/'api-settings';settings.mkdir()
        with patch('config.config_dir',return_value=settings),patch('config.application_root',return_value=settings/'app'):
            app=api.Api();self.clients.append(app._mcp)
            saved=app.save_mcp_server({**self.server(),'enabled':False})
            self.assertTrue(saved['ok'],saved)
            server_id=saved['servers'][0]['id']
            tested=app.test_mcp_server(server_id)
            self.assertTrue(tested['ok'],tested)
            self.assertGreaterEqual(tested['server']['tool_count'],1)
            self.assertTrue(app.add_mcp_demo()['ok'])
            self.assertTrue(app.add_mcp_demo()['ok'])
            names=[item['name'] for item in config.load_config()['mcp_servers']]
            self.assertEqual(names.count('Demonstração local'),1)

    def test_redact_short_secrets_without_mangling_text(self):
        self.assertEqual(redact("valor=abc",{"env":{"T":"abc"},"headers":{}}),"valor=[credencial oculta]")
        self.assertEqual(redact("banana",{"env":{"T":"a"},"headers":{}}),"banana")

    def _http_legacy(self, discover, version):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                message=json.loads(self.rfile.read(int(self.headers.get("Content-Length",0))))
                method=message.get("method")
                if method=="server/discover":
                    data=discover(message);status=404 if "error" in data else 200
                elif method=="initialize":
                    data={"jsonrpc":"2.0","id":message["id"],"result":{"protocolVersion":version,"capabilities":{"tools":{}},"serverInfo":{"name":"legacy","version":"1"}}}
                    status=200
                elif method=="notifications/initialized":
                    self.send_response(202);self.end_headers();return
                elif method=="tools/list":
                    data={"jsonrpc":"2.0","id":message["id"],"result":{"tools":[]}}
                    status=200
                else:
                    data={"jsonrpc":"2.0","id":message["id"],"error":{"code":-32601,"message":"?"}}
                    status=404
                body=json.dumps(data).encode()
                self.send_response(status);self.send_header("Content-Type","application/json")
                self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body)
        http=ThreadingHTTPServer(("127.0.0.1",0),Handler)
        threading.Thread(target=http.serve_forever,daemon=True).start()
        return http

    def test_http_legacy_error_with_null_id_falls_back(self):
        def discover(message):
            return {"jsonrpc":"2.0","id":None,"error":{"code":-32601,"message":"Method not found"}}
        http=self._http_legacy(discover,"2025-03-26")
        try:
            server=validate_server({"id":"legacy-null","name":"Legacy","transport":"http","url":f"http://127.0.0.1:{http.server_port}/mcp","approval":"auto"})
            client=MCPClient(server,str(self.root));self.clients.append(client)
            client.connect();self.assertEqual(client.version,"2025-03-26")
        finally:
            http.shutdown();http.server_close()

    def test_unsupported_version_uses_supported_legacy(self):
        def discover(message):
            return {"jsonrpc":"2.0","id":message["id"],"error":{"code":-32022,"message":"Unsupported protocol version","data":{"supported":["2027-01-01","2025-06-18"],"requested":"2026-07-28"}}}
        http=self._http_legacy(discover,"2025-06-18")
        try:
            server=validate_server({"id":"legacy-version","name":"Legacy","transport":"http","url":f"http://127.0.0.1:{http.server_port}/mcp","approval":"auto"})
            client=MCPClient(server,str(self.root));self.clients.append(client)
            client.connect();self.assertEqual(client.version,"2025-06-18")
        finally:
            http.shutdown();http.server_close()
    @unittest.skipUnless(importlib.util.find_spec("mcp") is not None,"SDK mcp não instalado neste ambiente")
    def test_official_python_sdk_server(self):
        server=self.server(approval='auto');server['args']=['-u',str(ROOT/'tests/mcp_sdk_server.py')]
        client=MCPClient(server,str(self.root));self.clients.append(client)
        client.connect();self.assertEqual(client.version,'2025-11-25')
        result=client.call('sdk_echo',{'texto':'teste real'})
        self.assertIn('SDK: teste real',json.dumps(result,ensure_ascii=False))

if __name__=='__main__':unittest.main()
