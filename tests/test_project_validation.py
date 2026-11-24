import json,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from command_jobs import CommandJobs
from coding_tools import Checkpoints
import project_validation as validation
import agent_isolation

class ValidationTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve();self.work=self.root/'project';self.work.mkdir();self.meta=self.work/'.studio';self.commands=CommandJobs();self.runs=validation.ValidationRuns(self.commands)
    def tearDown(self):self.runs.close();self.commands.close();self.tmp.cleanup()
    def suite(self,work):
        (work/'tests').mkdir();(work/'maths.py').write_text('def add(a,b): return a-b\n');(work/'tests/test_maths.py').write_text('import unittest\nfrom maths import add\nclass TestAdd(unittest.TestCase):\n def test_add(self): self.assertEqual(add(2,3),5)\n')
    def execute(self,root=None,meta=None,**kwargs):
        root=root or self.work;meta=meta or self.meta;r=self.runs.start(meta,root,**kwargs);return self.runs.wait(meta,r['id'])
    def test_real_unittest_fail_then_pass_and_output(self):
        self.suite(self.work);plan=validation.discover(self.work);self.assertEqual(plan['checks'][0]['id'],'python:unittest')
        failed=self.execute();self.assertEqual(failed['state'],'failed');self.assertIn('AssertionError',failed['checks'][0]['output'])
        (self.work/'maths.py').write_text('def add(a,b): return a+b\n');passed=self.execute();self.assertEqual(passed['state'],'passed',passed)
        self.assertNotEqual(failed['after_fingerprint'],passed['after_fingerprint']);self.assertEqual(len(validation.listing(self.meta)),2)
    def test_real_worktree_dirty_overlay_deleted_file_and_apply_gate(self):
        git=lambda *args:subprocess.run(['git','-C',str(self.work),*args],capture_output=True,check=True)
        git('init');git('config','user.name','Test');git('config','user.email','test@example.invalid');(self.work/'a.txt').write_text('committed');(self.work/'removed.txt').write_text('old');git('add','.');git('commit','-m','Seed');(self.work/'a.txt').write_text('dirty');(self.work/'removed.txt').unlink();(self.work/'extra.txt').write_text('untracked')
        key='b'*32;fork=agent_isolation.prepare(self.meta,self.work,key);self.assertEqual((fork/'a.txt').read_text(),'dirty');self.assertFalse((fork/'removed.txt').exists());self.assertEqual((fork/'extra.txt').read_text(),'untracked');self.assertEqual(agent_isolation.review(self.meta,key)['isolation'],'git-worktree')
        (fork/'a.txt').write_text('proposal')
        with self.assertRaisesRegex(ValueError,'verificações'):agent_isolation.apply(self.meta,key)
        report=self.execute(fork,agent_isolation.folder(self.meta,key)/'metadata');self.assertEqual(report['state'],'no_checks')
        self.assertTrue(agent_isolation.review(self.meta,key)['can_apply']);cp=agent_isolation.apply(self.meta,key)['checkpoint_id'];self.assertEqual((self.work/'a.txt').read_text(),'proposal');Checkpoints(self.meta).restore(cp);self.assertEqual((self.work/'a.txt').read_text(),'dirty')
    def test_changed_after_validation_blocks_and_failed_tests_block(self):
        self.suite(self.work);key='c'*32;fork=agent_isolation.prepare(self.meta,self.work,key);childmeta=agent_isolation.folder(self.meta,key)/'metadata'
        self.execute(fork,childmeta)
        with self.assertRaises(ValueError):agent_isolation.apply(self.meta,key)
        (fork/'maths.py').write_text('def add(a,b): return a+b\n');self.assertEqual(self.execute(fork,childmeta)['state'],'passed');self.assertTrue(agent_isolation.review(self.meta,key)['can_apply'])
        (fork/'new.txt').write_text('after validation');self.assertFalse(agent_isolation.review(self.meta,key)['can_apply'])
        with self.assertRaises(ValueError):agent_isolation.apply(self.meta,key)
    def test_cancel_denied_no_checks_and_zero_tests(self):
        (self.work/'.meister').mkdir();(self.work/'.meister/validation.json').write_text(json.dumps({'checks':[{'id':'slow','argv':[sys.executable,'-c','import time; time.sleep(20)']}]}))
        r=self.runs.start(self.meta,self.work,approve=lambda c:False);denied=self.runs.wait(self.meta,r['id']);self.assertEqual(denied['checks'][0]['state'],'denied')
        r=self.runs.start(self.meta,self.work);self.runs.cancel(self.meta,r['id']);self.assertEqual(self.runs.wait(self.meta,r['id'])['state'],'cancelled')
        with self.assertRaises(ValueError):self.runs.start(self.meta,self.work,['missing'])
        (self.work/'.meister/validation.json').unlink();self.assertEqual(self.execute()['state'],'no_checks')
        (self.work/'tests').mkdir();(self.work/'tests/test_empty.py').write_text('import unittest\n');empty=self.execute();self.assertEqual(empty['checks'][0]['state'],'no_tests');self.assertEqual(empty['state'],'failed')
    def test_real_local_venv_preparation(self):
        self.suite(self.work);(self.work/'requirements.txt').write_text('')
        prepared=self.execute(prepare=True);self.assertEqual(prepared['state'],'passed',prepared)
        interpreter=validation.python_runtime(self.work);self.assertTrue(Path(interpreter).is_relative_to(self.work/'.venv'));self.assertTrue(Path(interpreter).is_file())
        (self.work/'maths.py').write_text('def add(a,b): return a+b\n');self.assertEqual(self.execute()['state'],'passed')
    def test_real_npm_script(self):
        if not validation.npm_runtime():self.skipTest('Node/npm não disponíveis')
        (self.work/'package.json').write_text(json.dumps({'name':'validation-fixture','version':'1.0.0','scripts':{'test':'node -e "console.log(42)"'}}))
        result=self.execute();self.assertEqual(result['state'],'passed',result);self.assertIn('42',result['checks'][0]['output'])
    def test_discovery_declared_npm_scripts_and_custom_path(self):
        (self.work/'package.json').write_text(json.dumps({'scripts':{'test':'node test.js','build':'node build.js','lint':'eslint .'}}))
        with patch('project_validation.npm_runtime',return_value=['node','npm-cli.js']):
            plan=validation.discover(self.work);self.assertEqual({c['id'] for c in plan['checks']},{'npm:test','npm:lint','npm:build'});self.assertFalse(next(c for c in plan['checks'] if c['id']=='npm:build')['recommended'])
        (self.work/'.meister').mkdir();(self.work/'.meister/validation.json').write_text(json.dumps({'checks':[{'id':'bad','argv':['python'],'cwd':'..'}]}))
        with self.assertRaises(ValueError):validation.discover(self.work)
    def test_mixed_python_suite_uses_pytest(self):
        self.suite(self.work);(self.work/'tests/test_function.py').write_text('def test_value(): assert 1 == 1\n')
        self.assertEqual(validation.discover(self.work)['checks'][0]['id'],'python:pytest')
    def test_declared_pytest_is_detected_without_conventional_test_names(self):
        (self.work/'pytest.ini').write_text('[pytest]\npython_files=spec_*.py\n');(self.work/'spec_feature.py').write_text('def test_spec(): assert True\n')
        self.assertEqual(validation.discover(self.work)['checks'][0]['id'],'python:pytest')

if __name__=='__main__':unittest.main()
