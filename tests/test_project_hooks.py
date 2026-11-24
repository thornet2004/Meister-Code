import json,sys,threading,time,unittest
from unittest.mock import patch
import api,config,project_hooks
import test_task_recovery as recovery_tests
from task_recovery import Journal,location

class HooksTests(unittest.TestCase):
    setUp=recovery_tests.RecoveryApiTests.setUp
    tearDown=recovery_tests.RecoveryApiTests.tearDown
    def activate(self,hooks=None,deny=None):
        text=json.dumps(dict(version=1,deny_tools=deny or [],hooks=hooks or []));r=self.app.save_project_hooks(text);self.assertTrue(r['ok'],r);return r
    def hook(self,key,event,code,**kw):return dict(id=key,event=event,argv=[sys.executable,'-c',code],**kw)
    def append(self,text):return "from pathlib import Path;p=Path('events.txt');p.write_text((p.read_text() if p.exists() else '')+"+repr(text)+")"
    def chat(self,calls=None):
        seq=iter([recovery_tests.tool(name,args) for name,args in (calls or [])]+[dict(content='Concluído.',tool_calls=[])])
        with patch('providers.get_chat_adapter',return_value=lambda *a:next(seq)):return self.app.chat('Testar hooks.')
    def test_activation_change_and_disable(self):
        r=self.activate();self.assertTrue(r['configuration']['active'])
        p=self.project/'.meister/hooks.json';p.write_text(p.read_text()+' ');self.assertFalse(self.app.get_project_hooks()['configuration']['active'])
        self.activate();self.assertTrue(self.app.save_project_hooks('',False)['ok']);self.assertFalse(self.app.get_project_hooks()['configuration']['active'])
    def test_invalid_configuration_and_escape(self):
        for bad in [dict(version=2),dict(version=1,hooks=[dict(id='x',event='bad',argv=['x'])]),dict(version=1,hooks=[self.hook('x','task_end','pass',cwd='../out')]),dict(version=1,hooks=[self.hook('x','task_end','pass',timeout=301)])]:
            self.assertFalse(self.app.save_project_hooks(json.dumps(bad))['ok'])
    def test_real_order_and_separate_snapshots(self):
        self.activate([self.hook('before','before_tool',self.append('B'),tool='executar_comando'),self.hook('after','after_tool',self.append('A'),tool='executar_comando'),self.hook('end','task_end',self.append('E'))])
        self.assertTrue(self.chat([('executar_comando',dict(comando="Add-Content -LiteralPath command.txt -Value X"))])['ok'])
        self.assertEqual((self.project/'events.txt').read_text(),'BAE');self.assertTrue((self.project/'command.txt').exists())
        runs=self.app.get_project_hooks()['runs'];self.assertEqual(len(runs),3);self.assertTrue(all(r['state']=='completed' for r in runs),runs)
    def test_rule_blocks_tool_before_command_or_hook(self):
        self.activate([self.hook('before','before_tool',self.append('B'))],['executar_*'])
        self.chat([('executar_comando',dict(comando='Set-Content denied.txt BAD'))]);self.assertFalse((self.project/'denied.txt').exists());self.assertFalse((self.project/'events.txt').exists())
    def test_blocking_before_failure_never_executes_tool(self):
        self.activate([self.hook('fail','before_tool','raise SystemExit(3)',tool='executar_comando')]);self.chat([('executar_comando',dict(comando='Set-Content denied.txt BAD'))]);self.assertFalse((self.project/'denied.txt').exists());self.assertEqual(self.app.get_chat_recovery()['runs'][0]['state'],'validation_failed')
    def test_warning_end_failure_is_visible_without_blocking(self):
        self.activate([self.hook('warning','task_end','raise SystemExit(2)',on_failure='warn')]);self.chat();self.assertEqual(self.app.get_chat_recovery()['runs'][0]['state'],'completed');self.assertEqual(self.app.get_project_hooks()['runs'][0]['returncode'],2)
    def test_readonly_never_executes_hook_commands(self):
        self.activate([self.hook('end','task_end',self.append('E'))]);self.app.set_preference('agent_profile','plan');self.chat();self.assertFalse((self.project/'events.txt').exists());self.assertEqual(self.app.get_project_hooks()['runs'],[])
    def test_timeout_and_permission_refusal(self):
        self.activate([self.hook('slow','task_end','import time;time.sleep(30)',timeout=1)]);start=time.monotonic();self.chat();self.assertLess(time.monotonic()-start,15);self.assertEqual(self.app.get_project_hooks()['runs'][0]['state'],'timed_out')
        self.activate([self.hook('denied','task_end',self.append('E'))])
        with patch.object(self.app,'_approve',return_value=False):self.chat()
        self.assertFalse((self.project/'events.txt').exists());self.assertEqual(self.app.get_project_hooks()['runs'][0]['state'],'denied')
    def test_resume_reuses_observed_hook_and_unknown_blocks(self):
        self.activate([self.hook('end','task_end',self.append('E'))]);plan=self.app.get_project_hooks()['configuration']['plan'];j=Journal(location(self.meta,'a'*32,'turn'));j.create('a'*32,'x',self.project);ctx=dict(on=True,readonly=False,_recovery_journal=j);steps=[]
        args=(plan,'task_end','',self.project,self.meta,self.app._commands,ctx,steps,lambda h:True,threading.Event())
        self.assertTrue(project_hooks.run(*args));j.finish('interrupted');j.reopen('p','m');self.assertTrue(project_hooks.run(*args));self.assertEqual((self.project/'events.txt').read_text(),'E')
        j.begin(dict(name='project_hook',arguments={}),True);self.assertFalse(project_hooks.run(*args));self.assertEqual((self.project/'events.txt').read_text(),'E')
    def test_end_hook_changes_are_validated(self):
        self.activate([self.hook('end','task_end',"from pathlib import Path;Path('x.py').write_text('x=1')")]);reports=[]
        with patch.object(self.app,'_run_validation',side_effect=lambda *a,**kw:reports.append((self.project/'x.py').read_text()) or dict(state='passed',checks=[])):self.chat()
        self.assertEqual(reports,['x=1'])
    def test_child_uses_activated_parent_plan_in_isolated_workspace(self):
        self.activate([self.hook('end','task_end',self.append('E'))]);cfg=config.load_config();provider=cfg['providers'][0];payload=dict(cfg=cfg,workspace=str(self.project),meta=str(self.meta),provider=provider,model=provider['models'][0]);task=dict(id='b'*32,profile='build',prompt='Analisar.')
        with patch('providers.get_chat_adapter',return_value=lambda *a:dict(content='Pronto.',tool_calls=[])):
            result=self.app._run_subagent(payload,task,threading.Event())
        self.assertTrue(result['hooks_passed']);self.assertFalse((self.project/'events.txt').exists());work=api.agent_isolation.workspace(self.meta,task['id']);self.assertEqual((work/'events.txt').read_text(),'E')
    def test_resume_rechecks_failed_after_hook_without_repeating_tool(self):
        h=self.hook('verify','after_tool',"from pathlib import Path;raise SystemExit(0 if Path('fixed.txt').exists() else 4)",tool='executar_comando',repeat_on_resume=True);self.activate([h])
        self.chat([('executar_comando',dict(comando='Add-Content -LiteralPath counter.txt -Value X'))]);run=self.app.get_chat_recovery()['runs'][0];self.assertEqual(run['state'],'validation_failed')
        (self.project/'fixed.txt').write_text('fixed')
        with patch('providers.get_chat_adapter',return_value=lambda *a:dict(content='Retoma.',tool_calls=[])):
            r=self.app.resume_chat_turn(run['id'])
        self.assertTrue(r['ok'],r);self.assertEqual((self.project/'counter.txt').read_text().splitlines(),['X']);self.assertEqual(self.app.get_chat_recovery(run['id'])['recovery']['state'],'completed')
        self.assertEqual(len(self.app.get_project_hooks()['runs']),2)
    def test_readonly_cannot_activate_configuration(self):
        self.app.set_preference('agent_profile','plan');self.assertFalse(self.app.save_project_hooks(json.dumps(project_hooks.DEFAULT))['ok'])
    def test_cancelling_hook_preserves_cancelled_turn_state(self):
        self.activate([self.hook('slow','task_end','import time;time.sleep(30)')]);timer=threading.Timer(.6,self.app._cancel_chat.set);timer.start()
        try:self.chat()
        finally:timer.cancel();timer.join()
        self.assertEqual(self.app.get_chat_recovery()['runs'][0]['state'],'cancelled');self.assertEqual(self.app.get_project_hooks()['runs'][0]['state'],'cancelled')
    def test_rule_also_blocks_automatic_validation(self):
        cfg=config.load_config();ctx=self.app._agent_context(cfg);ctx['_hook_plan']={'deny_tools':['projeto_validar']}
        with patch.object(self.app,'_run_validation') as runner:
            result=self.app._recovery_validation(cfg,ctx,self.meta,threading.Event())
        self.assertEqual(result['state'],'failed');runner.assert_not_called()
    def test_invalid_after_hook_cwd_keeps_actual_tool_result_known(self):
        self.activate([self.hook('missing','after_tool','pass',cwd='missing',tool='executar_comando')]);self.chat([('executar_comando',dict(comando='Add-Content -LiteralPath counter.txt -Value X'))]);run=self.app.get_chat_recovery()['runs'][0];details=self.app.get_chat_recovery(run['id'])['recovery'];self.assertEqual(details['state'],'validation_failed');self.assertEqual(details['unknown'],[]);self.assertEqual(self.app.get_project_hooks()['runs'][0]['state'],'invalid');self.assertEqual((self.project/'counter.txt').read_text().splitlines(),['X'])

if __name__=='__main__':unittest.main()
