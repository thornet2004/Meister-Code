import hashlib,json,os,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
import config,release_updates as updates,system_diagnostics as diagnostics
from app_version import VERSION

class Response:
    status_code=200;headers={}
    def __init__(self,raw):self.raw=raw
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def iter_content(self,*a):yield self.raw
    def raise_for_status(self):pass
    def close(self):pass

class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.patch=patch('config.config_dir',return_value=self.root);self.patch.start();self.body=b'MZsynthetic-installer';self.release=dict(schema=1,version='9.0.0',platform='windows-x64',url='https://example.test/setup.exe',sha256=hashlib.sha256(self.body).hexdigest(),size=len(self.body));self.u=updates.Updates()
    def tearDown(self):self.patch.stop();self.tmp.cleanup()
    def check(self):
        with patch('release_updates.fetch',return_value=Response(json.dumps(self.release).encode())):return self.u.check('https://example.test/release.json')
    def test_check_stage_and_tamper_guard(self):
        self.assertTrue(self.check()['available'])
        with patch('release_updates.fetch',return_value=Response(self.body)):r=self.u.stage()
        self.assertTrue(r['verified']);self.assertEqual(self.u.ready().read_bytes(),self.body);Path(r['path']).write_bytes(b'altered')
        with self.assertRaises(ValueError):self.u.ready()
    def test_hash_size_failure_removes_staging(self):
        self.check()
        with patch('release_updates.fetch',return_value=Response(b'bad')):
            with self.assertRaises(ValueError):self.u.stage()
        self.assertFalse(list((self.root/'updates').glob('*.part')));self.assertIsNone(self.u.download)
    def test_current_version_does_not_download(self):
        self.release['version']=VERSION;self.assertFalse(self.check()['available'])
        with self.assertRaises(ValueError):self.u.stage()
    def test_schema_and_urls(self):
        for url in ['http://example.test/x','https://user:pass@example.test/x','https://example.test/x?token=secret','file:///C:/x']:
            with self.assertRaises(ValueError):updates.https(url)
        for key,value in [('size',updates.MAX_SETUP+1),('sha256','bad'),('version','latest'),('platform','linux')]:
            with self.assertRaises(ValueError):updates.manifest({**self.release,key:value})
    def test_redirect_cannot_downgrade_https(self):
        r=Response(b'');r.status_code=302;r.headers={'Location':'http://example.test/x'}
        with patch('release_updates.requests.get',return_value=r):
            with self.assertRaises(ValueError):updates.fetch('https://example.test/x')
    def test_manifest_size_limit_and_reset_after_error(self):
        with patch('release_updates.fetch',return_value=Response(b' '*65537)):
            with self.assertRaises(ValueError):self.u.check('https://example.test/x')
        self.assertFalse(self.u.busy);self.assertIsNone(self.u.release)
    def test_failed_storage_preparation_does_not_leave_updater_busy(self):
        self.check()
        with patch('config.config_dir',side_effect=PermissionError('locked')):
            with self.assertRaises(PermissionError):self.u.stage()
        self.assertFalse(self.u.busy);self.assertTrue(self.check()['available'])
    def test_receipt_failure_does_not_authorize_launch(self):
        self.check()
        with patch('release_updates.fetch',return_value=Response(self.body)),patch('release_updates.atomic',side_effect=PermissionError('locked')):
            with self.assertRaises(PermissionError):self.u.stage()
        self.assertIsNone(self.u.download);self.assertFalse(self.u.busy)
    def test_release_builder_rejects_stale_executable_version(self):
        from installer.build_release import verify_binary_version
        from types import SimpleNamespace
        ffi=SimpleNamespace(fileVersionMS=0,fileVersionLS=0)
        with patch('PyInstaller.utils.win32.versioninfo.read_version_info_from_executable',return_value=SimpleNamespace(ffi=ffi)):
            with self.assertRaises(ValueError):verify_binary_version('old.exe')

class InstalledDataTests(unittest.TestCase):
    def test_managed_conversations_are_copied_when_data_root_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);old=root/'old';new=root/'new';settings=root/'settings';settings.mkdir();source=old/'Conversas/c';source.mkdir(parents=True);(source/'conversation.json').write_text('[{"text":"preservar"}]');cfg=dict(storage_layout=2,storage_root=str(old),conversations=[dict(id='c')],projects=[])
            with patch('config.application_root',return_value=new),patch('config.config_dir',return_value=settings):self.assertTrue(config._migrate_storage(cfg))
            self.assertEqual((new/'Conversas/c/conversation.json').read_text(),'[\n  {\n    "text": "preservar"\n  }\n]');self.assertTrue((source/'conversation.json').exists())
    def test_installed_root_reuses_existing_data_and_falls_back_outside_binaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);binary=root/'bin';binary.mkdir();(binary/'studio-install.json').write_text('{}');settings=root/'settings';settings.mkdir();existing=root/'existing';existing.mkdir();(settings/'config.json').write_text(json.dumps(dict(storage_layout=2,storage_root=str(existing))))
            with patch('config.config_dir',return_value=settings),patch.object(sys,'frozen',True,create=True),patch.object(sys,'executable',str(binary/'Studio.exe')),patch.dict(os.environ,{'LOCALAPPDATA':str(root/'local')}):
                self.assertEqual(config.application_root(),existing.resolve());(settings/'config.json').unlink();self.assertEqual(config.application_root(),root/'local/Meister IA IDE')
    def test_no_marker_keeps_portable_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(sys,'frozen',True,create=True),patch.object(sys,'executable',str(Path(tmp)/'Studio.exe')):self.assertEqual(config.application_root(),Path(tmp))

class ProviderDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.patch=patch('config.config_dir',return_value=self.root);self.patch.start();self.jobs=diagnostics.ProviderTests();self.p=dict(id='p',kind='openai',api_key='test-secret',base_url='http://127.0.0.1:1/v1');self.m=dict(id='m',type='chat');self.calls=0
    def tearDown(self):
        self.jobs.close()
        for _ in range(100):
            if not self.jobs.jobs:break
            time.sleep(.01)
        self.patch.stop();self.tmp.cleanup()
    def adapter(self,p,m,messages,tools,params):
        self.calls+=1;self.assertEqual(m['defaults']['max_tokens'],256)
        if tools:
            token=messages[-1]['content'];call=dict(id='c',name='diagnostico_eco',arguments=dict(token=token));return dict(tool_calls=[call],raw_message=dict(role='assistant',content='',tool_calls=[]),usage=dict(total_tokens=5))
        return dict(content=json.loads(messages[-1]['content'])['token'],tool_calls=[],usage=dict(total_tokens=2))
    def wait(self,key):
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            if not self.jobs.jobs:return diagnostics.load(key)
            time.sleep(.01)
        self.fail('Diagnostic did not terminate')
    def test_synthetic_real_adapter_cycles_and_no_secrets_on_disk(self):
        with patch('providers.get_chat_adapter',return_value=self.adapter):r=self.jobs.start(self.p,self.m,3);d=self.wait(r['id'])
        self.assertEqual(d['state'],'passed');self.assertEqual(len(d['results']),3);self.assertEqual(self.calls,6);self.assertEqual(d['usage']['total_tokens'],21);self.assertNotIn('test-secret',diagnostics.location(r['id']).read_text());self.assertNotIn('defaults',self.m)
    def test_provider_errors_are_redacted(self):
        with patch('providers.get_chat_adapter',return_value=lambda *a:(_ for _ in ()).throw(ValueError('test-secret unavailable'))):r=self.jobs.start(self.p,self.m,1);d=self.wait(r['id'])
        self.assertEqual(d['state'],'failed');self.assertNotIn('test-secret',json.dumps(d))
    def test_cancel_and_bounds(self):
        for n in [0,11,True,'3']:
            with self.assertRaises(ValueError):self.jobs.start(self.p,self.m,n)
        def slow(*args):
            args[-1]['_cancel'].wait(3);return dict(cancelled=True)
        with patch('providers.get_chat_adapter',return_value=slow):r=self.jobs.start(self.p,self.m,3);self.jobs.cancel(r['id']);d=self.wait(r['id'])
        self.assertEqual(d['state'],'cancelled')
    def test_wrong_tool_never_dispatches_any_local_action(self):
        with patch('providers.get_chat_adapter',return_value=lambda *a:dict(tool_calls=[dict(name='executar_comando',arguments={})])):r=self.jobs.start(self.p,self.m,1);d=self.wait(r['id'])
        self.assertEqual(d['state'],'failed');self.assertEqual(d['results'],[])
    def test_dead_owner_is_interrupted(self):
        d=dict(id='f'*32,state='running',owner_pid=0);p=diagnostics.location(d['id']);p.parent.mkdir(parents=True);p.write_text(json.dumps(d));self.assertEqual(diagnostics.load(d['id'])['state'],'interrupted')
    def test_openrouter_receives_the_explicit_token_limit(self):
        from providers import openrouter
        with patch('providers.openrouter._chat_stream',return_value={}) as stream:
            openrouter.chat(dict(api_key='key'),dict(id='m',defaults={'max_tokens':4096}),[],params=dict(max_tokens=256,_on_delta=lambda s:None))
        self.assertEqual(stream.call_args.args[2]['max_tokens'],256)
    def test_output_limit_is_distinguished_from_missing_tool(self):
        for reason in ('length','max_output_tokens','max_tokens','MAX_TOKENS'):
            with patch('providers.get_chat_adapter',return_value=lambda *a:dict(content='',tool_calls=[],finish_reason=reason)):
                r=self.jobs.start(self.p,self.m,1);d=self.wait(r['id'])
            self.assertEqual(d['failure']['code'],'output_limit');self.assertEqual(d['failure']['stage'],'tool');self.assertEqual(d['failure']['round'],1);self.assertEqual(len(d['responses']),1)
        with patch('providers.get_chat_adapter',return_value=lambda *a:dict(content='No tools',tool_calls=[],finish_reason='stop')):
            r=self.jobs.start(self.p,self.m,1);d=self.wait(r['id'])
        self.assertEqual(d['failure']['code'],'no_tool_call')
    def test_provider_filter_is_not_reported_as_a_model_choice(self):
        with patch('providers.get_chat_adapter',return_value=lambda *a:dict(content='',tool_calls=[],finish_reason='content_filter')):
            r=self.jobs.start(self.p,self.m,1);d=self.wait(r['id'])
        self.assertEqual(d['failure']['code'],'provider_stop')
    def test_configurable_limit_and_bounds(self):
        for n in (0,63,4097,True,'256'):
            with self.assertRaises(ValueError):self.jobs.start(self.p,self.m,1,n)
        def adapter(*args):
            self.assertEqual(args[1]['defaults']['max_tokens'],1024);self.assertEqual(args[-1]['max_tokens'],1024);return dict(content='',tool_calls=[],finish_reason='stop')
        with patch('providers.get_chat_adapter',return_value=adapter):r=self.jobs.start(self.p,self.m,1,1024);d=self.wait(r['id'])
        self.assertEqual(d['max_tokens'],1024)
    def test_final_output_limit_is_recorded_with_stage(self):
        def adapter(*args):
            if args[3]:return self.adapter(*args)
            return dict(content='',tool_calls=[],finish_reason='length')
        with patch('providers.get_chat_adapter',return_value=adapter):r=self.jobs.start(self.p,self.m,1);d=self.wait(r['id'])
        self.assertEqual(d['failure']['code'],'output_limit');self.assertEqual(d['failure']['stage'],'final');self.assertEqual(len(d['responses']),2)

if __name__=='__main__':unittest.main()
