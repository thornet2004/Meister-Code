import json,tempfile,unittest,base64,os
from pathlib import Path
from unittest.mock import patch
import api,config,agent_isolation
from coding_tools import Checkpoints,process_identity
from task_recovery import Journal,location

def tool(name,args,key='call'):
    return dict(content='',tool_calls=[dict(id=key,name=name,arguments=args)],raw_message=dict(role='assistant',content=None,tool_calls=[dict(id=key,type='function',function=dict(name=name,arguments=json.dumps(args)))]))

class JournalTests(unittest.TestCase):
    def test_reused_pid_is_not_confused_with_original_owner(self):
        if process_identity() is None:self.skipTest('Identidade de criação não disponível neste sistema')
        with tempfile.TemporaryDirectory() as tmp:
            j=Journal(location(tmp,'1'*32));data=j.create('1'*32,'work',tmp);data['owner_pid']=os.getpid();data['owner_identity']='previous-process-with-same-pid';j.save(data);self.assertEqual(j.load()['state'],'interrupted')
            from agent_runtime import save,get_task
            save(tmp,dict(id='2'*32,state='running',owner_pid=os.getpid(),owner_identity='previous-process-with-same-pid'));self.assertEqual(get_task(tmp,'2'*32)['state'],'interrupted')
    def test_filesystem_evidence_and_redacted_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);meta=root/'.studio';file=root/'a';file.write_bytes(b'before');j=Journal(location(meta,'a'*32),'secret-key');j.create('a'*32,'change',root)
            action=j.begin(dict(name='aplicar_patch',arguments={'note':'secret-key'}),True);store=Checkpoints(meta);cp=store.begin('change');data=store.load(cp);data['recovery_action']=action;data['owner_pid']=2147483000;store.save(data);store.apply(cp,[(file,b'before',b'after')]);j.progress('secret-key',[],{});j.finish('interrupted')
            self.assertNotIn('secret-key',j.path.read_text());self.assertEqual(len(j.unknown()),1);j.reconcile(meta);self.assertEqual(j.unknown(),[]);self.assertEqual(j.load()['actions'][0]['outcome'],'completed');self.assertEqual(file.read_bytes(),b'after')
    def test_unknown_action_requires_explicit_verification_and_no_repeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            j=Journal(location(tmp,'b'*32));j.create('b'*32,'work',tmp);call=dict(name='executar_comando',arguments={'comando':'send-once'});key=j.begin(call,True);j.finish('error')
            with self.assertRaises(ValueError):j.resolve(key,'completed','')
            j.resolve(key,'completed','Resultado confirmado no destino.');j.reopen('p','m');self.assertIsNotNone(j.previous_effect(call));self.assertEqual(j.unknown(),[])
    def test_changed_files_are_not_assumed_completed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);meta=root/'.studio';file=root/'a';file.write_bytes(b'before');j=Journal(location(meta,'c'*32));j.create('c'*32,'change',root);action=j.begin(dict(name='aplicar_patch'),True);store=Checkpoints(meta);cp=store.begin();d=store.load(cp);d['recovery_action']=action;store.save(d);store.apply(cp,[(file,b'before',b'after')]);store.finish(cp);file.write_bytes(b'human');j.finish('error');j.reconcile(meta);self.assertEqual(len(j.unknown()),1);self.assertEqual(file.read_bytes(),b'human')
    def test_background_submission_without_final_result_becomes_uncertain(self):
        with tempfile.TemporaryDirectory() as tmp:
            j=Journal(location(tmp,'e'*32));j.create('e'*32,'start',tmp);a=j.begin(dict(name='processo_iniciar',arguments={'comando':'work'}),True);key='f'*32;j.returned(a,json.dumps({'id':key,'state':'starting'}));folder=Path(tmp)/'command-jobs'/key;folder.mkdir(parents=True);(folder/'job.json').write_text(json.dumps(dict(id=key,state='running',owner_pid=2147483000,pid=None)))
            j.finish('interrupted');j.reconcile(tmp);self.assertEqual(j.unknown()[0]['job_id'],key)

class RecoveryApiTests(unittest.TestCase):
    def test_output_limit_is_resumable_and_does_not_execute_partial_tools_or_completion_hooks(self):
        answer=tool('executar_comando',dict(comando='Set-Content unexpected.txt BAD'));answer.update(content='Parcial.',finish_reason='length')
        with patch('providers.get_chat_adapter',return_value=lambda *a:answer),patch.object(self.app,'_project_hooks') as hooks:
            self.assertTrue(self.app.chat('Continuar até terminar.')['ok']);hooks.assert_not_called()
        run=self.app.get_chat_recovery()['runs'][0];self.assertEqual(run['state'],'limited');self.assertFalse((self.project/'unexpected.txt').exists())
        with patch('providers.get_chat_adapter',return_value=lambda *a:dict(content='Concluído após retoma.',tool_calls=[],finish_reason='stop')):self.assertTrue(self.app.resume_chat_turn(run['id'])['ok'])
        self.assertEqual(self.app.get_chat_recovery(run['id'])['recovery']['state'],'completed')
    def test_provider_filter_is_not_saved_as_success(self):
        with patch('providers.get_chat_adapter',return_value=lambda *a:dict(content='',tool_calls=[],finish_reason='content_filter')):self.assertTrue(self.app.chat('Analisar.')['ok'])
        self.assertEqual(self.app.get_chat_recovery()['runs'][0]['state'],'error')
    def test_truncated_child_stays_limited_and_skips_validation(self):
        with patch('providers.get_chat_adapter',return_value=lambda *a:dict(content='Parcial.',tool_calls=[],finish_reason='max_output_tokens')),patch.object(self.app,'_recovery_validation') as checks:
            created=self.app.start_agent_task('build','Analisar.');result=self.app._tasks.wait(self.meta,created['task']['id'],10)
        self.assertEqual(result['state'],'limited');self.assertNotIn('12 ciclos',result['result']);checks.assert_not_called()
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve();self.project=self.root/'project';self.project.mkdir();settings=self.root/'settings';settings.mkdir()
        self.patches=[patch('config.config_dir',return_value=settings),patch('config.application_root',return_value=self.root/'app')]
        for p in self.patches:p.start()
        cfg=config.default_config();cfg.update(storage_layout=2,storage_root=str(self.root/'app'),projects=[dict(id='p',name='P',path=str(self.project))],active_project_id='p',providers=[dict(id='provider',kind='openrouter',api_key='private-secret',models=[dict(id='model',type='chat')])],chat=dict(provider_id='provider',model_id='model'));cfg['preferences']['agent']=dict(enabled=True,scope='project',approval='auto');config.save_config(cfg);self.app=api.Api();self.meta,_=config.resolve_context(cfg)
    def tearDown(self):
        jobs=list(self.app._tasks.jobs.values());self.app._tasks.close()
        for job in jobs:job['done'].wait(3)
        self.app._validations.close();self.app._commands.close();self.app._lsp.close();self.app._mcp.close();self.app._folder_tools.close()
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()
    def test_main_chat_resumes_without_executing_same_command_twice(self):
        command="Add-Content -LiteralPath counter.txt -Value X";count=[0]
        def first(*args):
            count[0]+=1
            if count[0]==1:return tool('executar_comando',dict(comando=command))
            raise api.providers.ProviderError('network interrupted')
        with patch('providers.get_chat_adapter',return_value=first):self.assertFalse(self.app.chat('Gravar X uma vez')['ok'])
        run=self.app.get_chat_recovery()['runs'][0];self.assertEqual(run['state'],'error');self.assertEqual((self.project/'counter.txt').read_text().splitlines(),['X'])
        count[0]=0
        def resumed(provider,model,messages,tools,params):
            count[0]+=1
            if count[0]==1:
                self.assertIn('RETOMA','\n'.join(m.get('content','') or '' for m in messages));return tool('executar_comando',dict(comando=command))
            self.assertIn('already_observed',messages[-1]['content']);return dict(content='Resultado anterior confirmado; trabalho concluído.',tool_calls=[])
        with patch('providers.get_chat_adapter',return_value=resumed):result=self.app.resume_chat_turn(run['id'])
        self.assertTrue(result['ok'],result);self.assertEqual((self.project/'counter.txt').read_text().splitlines(),['X']);self.assertEqual(self.app.get_chat_recovery(run['id'])['recovery']['state'],'completed');self.assertEqual(len(api._load_conversation(self.meta)),4)
    def test_unknown_main_action_blocks_writes_until_reviewed(self):
        key='d'*32;j=Journal(location(self.meta,key,'turn'));j.create(key,'Continuar trabalho',self.project,'provider','model','turn');action=j.begin(dict(name='executar_comando',arguments={'comando':'unknown'}),True);j.finish('interrupted')
        count=[0]
        def model(*args):
            count[0]+=1
            return tool('escrever_ficheiro',dict(caminho='new.txt',conteudo='new')) if count[0]==1 else dict(content='A análise está disponível.',tool_calls=[])
        with patch('providers.get_chat_adapter',return_value=model):result=self.app.resume_chat_turn(key)
        self.assertTrue(result['ok'],result);self.assertFalse((self.project/'new.txt').exists());self.assertEqual(j.load()['state'],'needs_resolution')
        self.assertTrue(self.app.resolve_chat_recovery(key,action,'not_run','Confirmei no sistema que não arrancou.')['ok']);count[0]=0
        with patch('providers.get_chat_adapter',return_value=model):result=self.app.resume_chat_turn(key)
        self.assertTrue(result['ok'],result);self.assertEqual((self.project/'new.txt').read_text(),'new')
    def test_main_response_already_saved_is_not_generated_again(self):
        with patch('providers.get_chat_adapter',return_value=lambda *a:dict(content='Resultado confirmado.',tool_calls=[])):self.assertTrue(self.app.chat('Analisar')['ok'])
        key=self.app.get_chat_recovery()['runs'][0]['id'];j=Journal(location(self.meta,key,'turn'));j.finish('interrupted')
        with patch('providers.get_chat_adapter',side_effect=AssertionError('No new model call')):result=self.app.resume_chat_turn(key)
        self.assertFalse(result['ok']);self.assertEqual(j.load()['state'],'completed');self.assertEqual(len(api._load_conversation(self.meta)),2)
    def test_attachment_is_restored_after_original_message_was_compacted(self):
        with patch('providers.get_chat_adapter',return_value=lambda *a:(_ for _ in ()).throw(api.providers.ProviderError('offline'))):
            self.assertFalse(self.app.chat('Ler o anexo',[dict(name='notes.txt',mime='text/plain',b64=base64.b64encode(b'ATTACHMENT_EVIDENCE_42').decode())])['ok'])
        run=self.app.get_chat_recovery()['runs'][0];old=api._load_conversation(self.meta);original_file=old[0]['files'][0]['path'];old.extend(dict(role='user' if i%2==0 else 'assistant',text='Outro assunto '+str(i),media=[],files=[]) for i in range(18));api._save_conversation(old,self.meta)
        with patch('providers.get_chat_adapter',return_value=lambda *a:dict(content='Resumo.',tool_calls=[])):self.assertTrue(self.app.compact_context()['ok'])
        def resumed(provider,model,messages,tools,params):
            self.assertIn('ATTACHMENT_EVIDENCE_42',json.dumps(messages,ensure_ascii=False));return dict(content='Anexo recuperado.',tool_calls=[])
        with patch('providers.get_chat_adapter',return_value=resumed):result=self.app.resume_chat_turn(run['id'])
        self.assertTrue(result['ok'],result);self.assertEqual(api._load_conversation(self.meta)[-2]['files'][0]['path'],original_file)
    def test_completed_subagent_result_is_recovered_without_model(self):
        with patch('providers.get_chat_adapter',return_value=lambda *a:dict(content='Análise confirmada.',tool_calls=[])):
            start=self.app.start_agent_task('review','Analisar');key=start['task']['id'];self.app._tasks.wait(self.meta,key,10)
        from agent_runtime import task_path,save,get_task
        data=json.loads(task_path(self.meta,key).read_text());data['state']='interrupted';data.pop('result',None);save(self.meta,data)
        with patch('providers.get_chat_adapter',side_effect=AssertionError('No new model call')):self.assertTrue(self.app.get_agent_recovery(key)['ok'])
        recovered=get_task(self.meta,key);self.assertEqual(recovered['state'],'completed');self.assertEqual(recovered['result'],'Análise confirmada.')
    def test_resume_requires_explicit_choice_when_original_provider_was_removed(self):
        with patch('providers.get_chat_adapter',return_value=lambda *a:(_ for _ in ()).throw(api.providers.ProviderError('offline'))):
            start=self.app.start_agent_task('review','Analisar');key=start['task']['id'];self.app._tasks.wait(self.meta,key,10)
        cfg=config.load_config();cfg['providers']=[dict(id='other',kind='ollama',models=[dict(id='new',type='chat')])];cfg['chat']=dict(provider_id='other',model_id='new');config.save_config(cfg)
        self.assertFalse(self.app.resume_agent_task(key)['ok'])
        def model(provider,*args):self.assertEqual(provider['id'],'other');return dict(content='Retomado.',tool_calls=[])
        with patch('providers.get_chat_adapter',return_value=model):
            resumed=self.app.resume_agent_task(key,use_current_model=True);self.assertTrue(resumed['ok'],resumed);done=self.app._tasks.wait(self.meta,key,10)
        self.assertEqual(done['state'],'completed');self.assertEqual(done['provider_id'],'other')
    def test_subagent_resumes_in_same_copy_and_rechecks_current_file(self):
        (self.project/'a.txt').write_text('before');count=[0];original=None
        def first(*args):
            count[0]+=1
            if count[0]==1:return tool('ler_codigo',dict(caminho='a.txt'))
            if count[0]==2:
                data=json.loads(args[2][-1]['content']);return tool('aplicar_patch',dict(alteracoes=[dict(caminho='a.txt',sha256=data['sha256'],trecho_antigo='before',trecho_novo='after')]))
            raise api.providers.ProviderError('network interrupted')
        with patch('providers.get_chat_adapter',return_value=first):
            created=self.app.start_agent_task('build','Alterar before para after');key=created['task']['id'];result=self.app._tasks.wait(self.meta,key,10)
        self.assertEqual(result['state'],'error',result);original=agent_isolation.workspace(self.meta,key);self.assertEqual((original/'a.txt').read_text(),'after');self.assertEqual((self.project/'a.txt').read_text(),'before');count[0]=0
        def resumed(provider,model,messages,tools,params):
            count[0]+=1;self.assertEqual(provider['id'],'provider')
            if count[0]==1:
                self.assertIn('Verificar sem voltar a editar.',messages[-1]['content'])
                self.assertIn('RETOMA','\n'.join(m.get('content','') or '' for m in messages));return tool('ler_codigo',dict(caminho='a.txt'))
            self.assertIn('after',messages[-1]['content']);return dict(content='A alteração já está feita; foi verificada.',tool_calls=[])
        with patch('providers.get_chat_adapter',return_value=resumed):
            start=self.app.resume_agent_task(key,'Verificar sem voltar a editar.');self.assertTrue(start['ok'],start);done=self.app._tasks.wait(self.meta,key,10)
        self.assertEqual(done['state'],'awaiting_review',done);self.assertEqual(agent_isolation.workspace(self.meta,key),original);self.assertEqual(done['attempt'],2);self.assertTrue((Path(self.meta)/'agent-attempts'/key/'1.json').exists());self.assertEqual((self.project/'a.txt').read_text(),'before')
