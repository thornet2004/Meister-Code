import tempfile,unittest,subprocess
from pathlib import Path
import agent_isolation,git_workspace
from execution_limits import ExecutionLimits,validate
from workspace_snapshot import WorkspaceSnapshot,recover
from coding_tools import Checkpoints

class RoadmapTest(unittest.TestCase):
    def test_isolation_review_preflight_and_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'project';root.mkdir();meta=root/'.studio';file=root/'a.py';file.write_text('before');key='a'*32
            fork=agent_isolation.prepare(meta,root,key);(fork/'a.py').write_text('after');(fork/'b.py').write_text('created')
            self.assertEqual(file.read_text(),'before');self.assertEqual(len(agent_isolation.review(meta,key)['files']),2)
            from project_validation import ValidationRuns
            from command_jobs import CommandJobs
            manager=CommandJobs();runs=ValidationRuns(manager)
            try:
                run=runs.start(agent_isolation.folder(meta,key)/'metadata',fork);self.assertEqual(runs.wait(agent_isolation.folder(meta,key)/'metadata',run['id'])['state'],'no_checks')
            finally:runs.close();manager.close()
            file.write_text('human')
            with self.assertRaisesRegex(ValueError,'mudou'):agent_isolation.apply(meta,key)
            self.assertFalse((root/'b.py').exists());file.write_text('before');result=agent_isolation.apply(meta,key)
            self.assertEqual(file.read_text(),'after');Checkpoints(meta).restore(result['checkpoint_id']);self.assertEqual(file.read_text(),'before');self.assertFalse((root/'b.py').exists())
    def test_snapshot_restart_recovery_and_exclusions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'project';root.mkdir();meta=root/'.studio';file=root/'a';file.write_text('before');(root/'node_modules').mkdir();(root/'node_modules/dep').write_text('excluded')
            snap=WorkspaceSnapshot(meta,root,'external');key=snap.begin();file.unlink();(root/'new').write_text('new');store=Checkpoints(meta);cp=store.load(key);cp['owner_pid']=2147483000;store.save(cp);snap.abandon();recover(meta)
            cp=store.preview(key);self.assertTrue(cp['interrupted']);self.assertEqual(len(cp['files']),2);store.restore(key);self.assertEqual(file.read_text(),'before')
    def test_limits_and_repetition(self):
        guard=ExecutionLimits({'tokens':10});guard.add_usage({'total_tokens':11});self.assertIn('tokens',guard.reason())
        guard=ExecutionLimits({'cost':.5,'input_per_million':1000000});guard.add_usage({'prompt_tokens':1});self.assertIn('Orçamento',guard.reason())
        guard=ExecutionLimits()
        for _ in range(3):guard.observe({'name':'aplicar_patch','arguments':{'x':1}},'erro')
        self.assertIn('repetidas',guard.reason())
        for invalid in [dict(tokens=0),dict(cost=-1),dict(seconds=float('nan'))]:
            with self.assertRaises(ValueError):validate(invalid)
    def test_git_stage_commit_branch_worktree_and_path_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'repo';root.mkdir();subprocess.run(['git','init',str(root)],capture_output=True,check=True)
            for key,value in [('user.name','Test'),('user.email','test@example.invalid')]:git_workspace.run(root,'config',key,value)
            file=root/'a.txt';file.write_text('first');self.assertEqual(len(git_workspace.status(root)['changes']),1)
            git_workspace.action(root,'stage',{'paths':['a.txt']});git_workspace.action(root,'commit',{'message':'Initial'})
            git_workspace.action(root,'branch',{'branch':'codex/test'});git_workspace.action(root,'switch',{'branch':'codex/test'});self.assertEqual(git_workspace.status(root)['branch'],'codex/test')
            file.write_text('second');self.assertIn('+second',git_workspace.action(root,'diff',{'paths':['a.txt']})['text'])
            with self.assertRaises(ValueError):git_workspace.action(root,'switch',{'branch':'master'})
            with self.assertRaises(ValueError):git_workspace.action(root,'stage',{'paths':['../outside']})
            git_workspace.action(root,'branch',{'branch':'codex/worktree'});destination=Path(tmp)/'other';git_workspace.action(root,'worktree',{'branch':'codex/worktree','path':str(destination)});self.assertEqual((destination/'a.txt').read_text(),'first')
            git_workspace.run(root,'worktree','remove',str(destination))

if __name__=='__main__':unittest.main()
