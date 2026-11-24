import tempfile,time,unittest
from pathlib import Path
from command_jobs import CommandJobs,load,listing
from workspace_snapshot import WorkspaceSnapshot
from coding_tools import Checkpoints

class JobsTest(unittest.TestCase):
    def test_command_persists_output_and_checkpoint_with_undo(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'workspace';root.mkdir();meta=Path(tmp)/'meta';file=root/'a.txt';file.write_text('before')
            manager=CommandJobs()
            try:
                job=manager.start(meta,"[IO.File]::WriteAllText('a.txt','after'); Write-Output 'proof-42'",root,20,WorkspaceSnapshot(meta,root,'test'))
                deadline=time.monotonic()+25
                while time.monotonic()<deadline:
                    result=load(meta,job['id'])
                    if result['state'] not in ('starting','running'):break
                    time.sleep(.05)
                self.assertEqual(result['state'],'completed',result);self.assertIn('proof-42',result['output']);self.assertEqual(file.read_text(),'after')
                key=result['checkpoint']['id'];Checkpoints(meta).restore(key);self.assertEqual(file.read_text(),'before')
                Checkpoints(meta).restore(key,True);self.assertEqual(file.read_text(),'after');self.assertEqual(len(listing(meta)),1)
            finally:manager.close()
    def test_cancel_process_tree_and_snapshot_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'work';root.mkdir();meta=Path(tmp)/'meta';manager=CommandJobs()
            try:
                job=manager.start(meta,'Start-Sleep -Seconds 20',root,30)
                deadline=time.monotonic()+5
                while load(meta,job['id'])['state']=='starting' and time.monotonic()<deadline:time.sleep(.05)
                manager.cancel(meta,job['id']);manager.close();self.assertEqual(load(meta,job['id'])['state'],'cancelled')
                file=root/'a';file.write_text('before');snap=WorkspaceSnapshot(meta,root,'change');key=snap.begin();file.write_text('after');(root/'new').write_text('new');snap.finish(key);file.write_text('human change')
                with self.assertRaisesRegex(ValueError,'Conflito'):Checkpoints(meta).restore(key)
                self.assertTrue((root/'new').exists())
            finally:manager.close()
