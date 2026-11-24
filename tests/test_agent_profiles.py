import json,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
import api,config,project_guidance
from agent_runtime import AgentTasks,get_task,list_tasks,READ_TOOLS

class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve();self.project=self.root/'project';self.project.mkdir();self.settings=self.root/'settings';self.settings.mkdir()
        self.patches=[patch('config.config_dir',return_value=self.settings),patch('config.application_root',return_value=self.root/'app')]
        for p in self.patches:p.start()
        cfg=config.default_config();cfg.update(storage_layout=2,storage_root=str(self.root/'app'),projects=[dict(id='p',name='Project',path=str(self.project))],active_project_id='p',providers=[dict(id='provider',kind='openrouter',api_key='private-secret',models=[dict(id='model',type='chat')])],chat=dict(provider_id='provider',model_id='model'))
        cfg['preferences']['agent']=dict(enabled=True,scope='project',approval='auto');config.save_config(cfg);self.app=api.Api()
    def tearDown(self):
        jobs=list(self.app._tasks.jobs.values());self.app._tasks.close()
        for j in jobs:j['done'].wait(3)
        self.app._validations.close();self.app._commands.close()
        self.app._lsp.close();self.app._mcp.close();self.app._folder_tools.close()
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()
    def test_readonly_catalog_and_guessed_calls_cannot_write_execute_or_mcp(self):
        cfg=config.load_config();cfg['preferences']['agent_profile']='plan';ctx=self.app._agent_context(cfg)
        with patch.object(self.app._mcp,'tools',side_effect=AssertionError('MCP must not start')):
            tools=self.app._available_tools(cfg,ctx)
        names={t['function']['name'] for t in tools};self.assertTrue(names<=READ_TOOLS);self.assertIn('ler_codigo',names)
        meta,_=config.resolve_context(cfg)
        for name in ['escrever_ficheiro','aplicar_patch','executar_comando','ferramentas_executar','mcp_fake','browser_clicar','memoria_guardar','gerar_imagem']:
            with patch('subprocess.run',side_effect=AssertionError('No command')):
                result=json.loads(self.app._handle_tool(cfg,dict(name=name,arguments={}),[],[],ctx,meta,self.project))
            self.assertIn('bloqueada',result['error'])
    def test_project_rules_nested_scope_skills_and_prompt(self):
        (self.project/'AGENTS.md').write_text('Usar nomes portugueses.',encoding='utf-8');(self.project/'src').mkdir();(self.project/'src/AGENTS.md').write_text('Testar alterações de src.',encoding='utf-8');(self.project/'src/a.txt').write_text('content')
        skill=self.project/'.agents/skills/verify';skill.mkdir(parents=True);(skill/'SKILL.md').write_text('---\nname: verify\ndescription: Verificar projeto\n---\nExecutar a verificação autorizada.',encoding='utf-8')
        cfg=config.load_config();ctx=self.app._agent_context(cfg);tools=self.app._available_tools(cfg,ctx,connect=False)
        messages=api._build_model_messages([dict(role='user',text='Analisa')],ctx,tools)
        self.assertIn('Usar nomes portugueses',messages[0]['content']);self.assertIn('verify',messages[0]['content']);self.assertNotIn('Executar a verificação autorizada.',messages[0]['content'])
        result=json.loads(self.app._dispatch_coding_tool('ler_codigo',dict(caminho='src/a.txt'),ctx,[]));self.assertEqual(len(result['instructions']),2)
        row=project_guidance.skills(self.project)[0];self.assertIn('Executar a verificação',project_guidance.load_skill(self.project,row['id'])['text'])
        self.assertEqual(project_guidance.rules(self.project,self.root/'outside.txt'),[])
        with self.assertRaises(ValueError):project_guidance.load_skill(self.project,'../../outside')
    def test_real_task_tool_loop_and_readonly_enforcement(self):
        (self.project/'a.txt').write_text('evidence-42');calls=[]
        def model(provider,model,messages,tools,params):
            calls.append(messages)
            self.assertNotIn('agente_delegar',[t['function']['name'] for t in tools])
            name='executar_comando' if len(calls)==1 else 'ler_codigo'
            args={'comando':'danger'} if len(calls)==1 else {'caminho':'a.txt'}
            if len(calls)<=2:
                raw=dict(role='assistant',content=None,tool_calls=[dict(id=str(len(calls)),type='function',function=dict(name=name,arguments=json.dumps(args)))])
                return dict(content='',raw_message=raw,tool_calls=[dict(id=str(len(calls)),name=name,arguments=args)])
            self.assertIn('evidence-42',messages[-1]['content']);self.assertTrue(any('bloqueada' in m.get('content','') for m in messages if m['role']=='tool'))
            return dict(content='a.txt:1 contém evidence-42. private-secret',tool_calls=[],usage=dict(total_tokens=13))
        with patch('providers.get_chat_adapter',return_value=model):
            result=self.app.start_agent_task('review','Verificar a.txt');self.assertTrue(result['ok'],result);key=result['task']['id'];meta,_=config.resolve_context(config.load_config());done=self.app._tasks.wait(meta,key,10)
        self.assertEqual(done['state'],'completed');self.assertEqual(done['usage']['total_tokens'],13);self.assertNotIn('private-secret',json.dumps(done));self.assertIn('a.txt:1',done['result'])
        self.assertEqual(get_task(meta,key)['result'],done['result']);self.assertEqual(len(list_tasks(meta)),1)
    def test_external_mcp_snapshot_and_readonly_build_delegation(self):
        file=self.project/'mcp.txt';file.write_text('before');cfg=config.load_config();ctx=self.app._agent_context(cfg);meta,_=config.resolve_context(cfg)
        def change(*args):file.write_text('after');return dict(content=[dict(type='text',text='changed')])
        with patch.object(self.app._mcp,'call',side_effect=change):
            result=json.loads(self.app._handle_tool(cfg,dict(name='mcp_fixture_change',arguments={}),[],[],ctx,meta,self.project))
        self.assertEqual(result['content'][0]['text'],'changed')
        from coding_tools import Checkpoints
        store=Checkpoints(meta);cp=store.list()[0];self.assertIn('mcp_fixture_change',cp['title']);store.restore(cp['id']);self.assertEqual(file.read_text(),'before')
        cfg['preferences']['agent_profile']='plan'
        with self.assertRaisesRegex(ValueError,'leitura'):self.app._start_agent_task(cfg,self.app._agent_context(cfg),meta,'build','Change')
    def test_role_selection_routes_and_provider_removal_cleans_override(self):
        cfg=config.load_config();cfg['providers'].append(dict(id='other',kind='ollama',models=[dict(id='local',type='chat')]))
        config.save_config(cfg);result=self.app.set_agent_model('review','other','local');self.assertTrue(result['ok'],result)
        self.assertEqual(api._resolve_agent_model(config.load_config(),'review')[0]['id'],'other')
        result=self.app.remove_provider('other');self.assertTrue(result['ok'],result);self.assertNotIn('review',config.load_config()['preferences']['agent_models'])
    def _repair_fixture(self):
        (self.project/'maths.py').write_text('def add(a,b): return a-b\n');(self.project/'tests').mkdir();(self.project/'tests/test_maths.py').write_text('import unittest\nfrom maths import add\nclass TestAdd(unittest.TestCase):\n def test_add(self): self.assertEqual(add(2,3),5)\n');calls=[]
        def model(provider,selected,messages,tools,params):
            calls.append(messages);n=len(calls)
            if n in (3,6):return dict(content='Alteração pronta.',tool_calls=[])
            if n==4:self.assertIn('AssertionError',messages[-1]['content'])
            if n in (1,4):name='ler_codigo';args=dict(caminho='maths.py')
            else:
                data=json.loads(messages[-1]['content']);name='aplicar_patch';args=dict(alteracoes=[dict(caminho='maths.py',sha256=data['sha256'],trecho_antigo='a-b' if n==2 else 'a*b',trecho_novo='a*b' if n==2 else 'a+b')])
            key=str(n);return dict(content='',tool_calls=[dict(id=key,name=name,arguments=args)],raw_message=dict(role='assistant',content=None,tool_calls=[dict(id=key,type='function',function=dict(name=name,arguments=json.dumps(args)))]))
        return model,calls
    def test_build_agent_corrects_real_failed_tests_before_review(self):
        model,calls=self._repair_fixture()
        with patch('providers.get_chat_adapter',return_value=model):
            start=self.app.start_agent_task('build','Corrigir add');self.assertTrue(start['ok'],start);meta,_=config.resolve_context(config.load_config());result=self.app._tasks.wait(meta,start['task']['id'],10)
        self.assertEqual(result['state'],'awaiting_review',result);self.assertEqual(len(calls),6);self.assertEqual(result['validation']['state'],'passed');self.assertIn('a-b',(self.project/'maths.py').read_text())
        applied=self.app.apply_agent_proposal(start['task']['id']);self.assertTrue(applied['ok'],applied);self.assertIn('a+b',(self.project/'maths.py').read_text())
    def test_primary_agent_corrects_real_failed_tests_before_completion(self):
        model,calls=self._repair_fixture()
        with patch('providers.get_chat_adapter',return_value=model):result=self.app.chat('Corrigir add')
        self.assertTrue(result['ok'],result);self.assertEqual(len(calls),6);self.assertIn('a+b',(self.project/'maths.py').read_text())
        meta,_=config.resolve_context(config.load_config());conversation=api._load_conversation(meta);self.assertEqual(conversation[-1]['validation']['state'],'passed')
    def test_isolated_build_inherits_registered_project_decisions(self):
        self.app.update_context_record('decision','DECISION_PRESERVED_42: usar SQLite.')
        def model(provider,selected,messages,tools,params):
            self.assertIn('DECISION_PRESERVED_42','\n'.join(m.get('content','') or '' for m in messages));return dict(content='Decisão considerada.',tool_calls=[])
        with patch('providers.get_chat_adapter',return_value=model):
            start=self.app.start_agent_task('build','Analisar a decisão do projeto');meta,_=config.resolve_context(config.load_config());result=self.app._tasks.wait(meta,start['task']['id'],10)
        self.assertEqual(result['state'],'awaiting_review',result)
    def test_noncode_mcp_output_does_not_trigger_project_tests(self):
        self._repair_fixture();calls=[]
        def model(provider,selected,messages,tools,params):
            calls.append(messages)
            if len(calls)==1:return dict(content='',tool_calls=[dict(id='m',name='mcp_fixture_export',arguments={})],raw_message=dict(role='assistant',content=None,tool_calls=[dict(id='m',type='function',function=dict(name='mcp_fixture_export',arguments='{}'))]))
            return dict(content='Exportação pronta.',tool_calls=[])
        def export(*args):(self.project/'export.txt').write_text('exportado');return dict(content=[dict(type='text',text='exportado')])
        with patch('providers.get_chat_adapter',return_value=model),patch.object(self.app._mcp,'call',side_effect=export),patch.object(self.app,'_run_validation',side_effect=AssertionError('Não testar uma exportação de texto')):
            result=self.app.chat('Exportar o texto')
        self.assertTrue(result['ok'],result);self.assertEqual((self.project/'export.txt').read_text(),'exportado')
    def test_parallel_limit_queue_cancel_and_no_resurrection_after_delete(self):
        started=[];release=threading.Event();lock=threading.Lock()
        def runner(payload,data,cancel):
            with lock:started.append(data['id'])
            while not release.wait(.01):
                if cancel.is_set():break
            return dict(result='done',steps=[])
        manager=AgentTasks(runner);meta=self.root/'tasks';payload=dict(provider=dict(id='p',api_key='secret'),model=dict(id='m'),workspace=str(self.project));jobs=[]
        try:
            for n in range(3):jobs.append(manager.submit(meta,'explore','Task '+str(n),payload))
            end=time.monotonic()+3
            while len(started)<2 and time.monotonic()<end:time.sleep(.01)
            self.assertEqual(len(started),2);manager.cancel(meta,jobs[2]['id']);self.assertEqual(get_task(meta,jobs[2]['id'])['state'],'cancelled')
            manager.detach_context(meta);saved=list(meta.rglob('*.json'))
            # Explicitly owned temporary metadata, no user content.
            for file in saved:file.unlink()
            for j in list(manager.jobs.values()):j['done'].wait(3)
            self.assertEqual(list(meta.rglob('*.json')),[])
        finally:release.set();manager.close()
    def test_invalid_profile_rejected_and_agent_disabled_cannot_delegate(self):
        self.assertFalse(self.app.set_preference('agent_profile','bad')['ok'])
        cfg=config.load_config();cfg['preferences']['agent']['enabled']=False;config.save_config(cfg)
        self.assertFalse(self.app.start_agent_task('explore','Do work')['ok'])
        cfg['preferences']['agent_profile']='plan';config.save_config(cfg);ctx=self.app._agent_context(cfg)
        self.assertTrue(ctx['readonly']);names={t['function']['name'] for t in self.app._available_tools(cfg,ctx)}
        self.assertTrue(names<=READ_TOOLS);self.assertNotIn('escrever_ficheiro',names)
