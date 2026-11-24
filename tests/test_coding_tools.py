import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import api,coding_tools
from coding_tools import Checkpoints,digest

class CodingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve();self.meta=self.root/'.studio'
        self.app=api.Api();self.ctx=dict(on=True,scope='project',base=str(self.root),approval='auto',_checkpoint_meta=str(self.meta),_checkpoint_title='Corrigir código')
        self.mock=patch.object(self.app._lsp,'diagnose',return_value=dict(status='complete',diagnostics=[]));self.mock.start()
    def tearDown(self):
        self.mock.stop();self.app._lsp.close();self.app._mcp.close();self.app._folder_tools.close();self.tmp.cleanup()
    def tool(self,name,**args):return json.loads(self.app._dispatch_coding_tool(name,args,self.ctx,[]))
    def test_patch_preserves_bom_crlf_and_checkpoint_undo_redo(self):
        p=self.root/'a.py';original=b'\xef\xbb\xbfx = 1\r\ny = 2\r\n';p.write_bytes(original)
        read=self.tool('ler_codigo',caminho='a.py');self.assertEqual(read['lines'][0]['line'],1)
        result=self.tool('aplicar_patch',alteracoes=[dict(caminho='a.py',sha256=read['sha256'],trecho_antigo='x = 1\ny = 2',trecho_novo='x = 3\ny = 2')])
        self.assertNotIn('error',result);self.assertEqual(p.read_bytes(),b'\xef\xbb\xbfx = 3\r\ny = 2\r\n')
        store=Checkpoints(self.meta);key=result['checkpoint_id']
        with self.assertRaises(ValueError):store.restore(key)
        store.finish(key);changed=p.read_bytes();self.assertIn('+x = 3',store.preview(key)['files'][0]['diff'])
        store.restore(key);self.assertEqual(p.read_bytes(),original)
        store.restore(key,True);self.assertEqual(p.read_bytes(),changed)
    def test_stale_hash_and_duplicate_snippet_do_not_write(self):
        p=self.root/'a.py';p.write_text('x = 1\nx = 1\n');sha=digest(p.read_bytes())
        result=self.tool('aplicar_patch',alteracoes=[dict(caminho='a.py',sha256=sha,trecho_antigo='x = 1',trecho_novo='x = 2')]);self.assertIn('exatamente uma vez',result['error'])
        result=self.tool('aplicar_patch',alteracoes=[dict(caminho='a.py',sha256='stale',trecho_antigo='x = 1',trecho_novo='x = 2')]);self.assertIn('SHA-256',result['error']);self.assertEqual(p.read_text(),'x = 1\nx = 1\n')
    def test_multi_file_preflight_and_approval_race(self):
        a=self.root/'a.txt';b=self.root/'b.txt';a.write_text('old');b.write_text('old')
        edits=[dict(caminho=p.name,sha256=digest(p.read_bytes()),trecho_antigo='old',trecho_novo='new') for p in (a,b)]
        edits[1]['sha256']='stale';r=self.tool('aplicar_patch',alteracoes=edits);self.assertIn('error',r);self.assertEqual(a.read_text(),'old')
        edits[1]['sha256']=digest(b.read_bytes())
        def approve(*args):b.write_text('external');return True
        with patch.object(self.app,'_approve',side_effect=approve):r=self.tool('aplicar_patch',alteracoes=edits)
        self.assertIn('Conflito',r['error']);self.assertEqual(a.read_text(),'old');self.assertEqual(b.read_text(),'external')
    def test_restore_conflict_leaves_all_files_unchanged(self):
        a=self.root/'a';b=self.root/'b';a.write_bytes(b'a');b.write_bytes(b'b');store=Checkpoints(self.meta);key=store.begin()
        store.apply(key,[(a,b'a',b'A'),(b,b'b',b'B')]);store.finish(key);b.write_bytes(b'external')
        with self.assertRaises(ValueError):store.restore(key)
        self.assertEqual(a.read_bytes(),b'A');self.assertEqual(b.read_bytes(),b'external');self.assertTrue(store.preview(key)['files'][1]['conflict'])
    def test_created_file_retired_and_redone_without_loss(self):
        p=self.root/'new';store=Checkpoints(self.meta);key=store.begin();store.apply(key,[(p,None,b'data')]);store.finish(key)
        Checkpoints(self.meta).restore(key);self.assertFalse(p.exists());self.assertEqual(next((store._path(key)/'recovered').iterdir()).read_bytes(),b'data')
        Checkpoints(self.meta).restore(key,True);self.assertEqual(p.read_bytes(),b'data')
    def test_partial_io_failure_rolls_back_successful_writes(self):
        a=self.root/'a';b=self.root/'b';a.write_bytes(b'a');b.write_bytes(b'b');store=Checkpoints(self.meta);key=store.begin();original_atomic=coding_tools.atomic
        def fail(path,data):
            if Path(path)==b and data==b'B':raise OSError('disk failure')
            return original_atomic(path,data)
        with patch('coding_tools.atomic',side_effect=fail):
            with self.assertRaises(OSError):store.apply(key,[(a,b'a',b'A'),(b,b'b',b'B')])
        self.assertEqual(a.read_bytes(),b'a');self.assertEqual(b.read_bytes(),b'b');self.assertEqual(store.load(key)['files'],[])
    def test_search_lines_exclusions_and_scope(self):
        (self.root/'one.py').write_text('hello\nTARGET\n');(self.root/'node_modules').mkdir();(self.root/'node_modules/skip.py').write_text('TARGET')
        result=self.tool('pesquisar_conteudo',texto='target',padrao='*.py');self.assertEqual(result['results'],[dict(path='one.py',line=2,text='TARGET')])
        self.assertIn('error',self.tool('ler_codigo',caminho='../outside.py'))
    def test_legacy_write_requires_read_and_records_checkpoint(self):
        p=self.root/'a.txt';p.write_text('old')
        r=self.app._dispatch_agent_tool('escrever_ficheiro',dict(caminho='a.txt',conteudo='new'),self.ctx,[]);self.assertIn('Lê primeiro',r)
        self.app._agent_read('a.txt',self.ctx,[]);r=self.app._agent_write('a.txt','new',self.ctx,[]);self.assertIn('checkpoint_id',json.loads(r))
    def test_multiple_edits_share_turn_checkpoint(self):
        for name in ['a.txt','b.txt']:
            self.app._agent_write(name,'created',self.ctx,[])
        self.assertEqual(len(Checkpoints(self.meta).list()),1);self.assertEqual(Checkpoints(self.meta).list()[0]['file_count'],2)
    def test_abandoned_write_ahead_journal_can_be_recovered(self):
        p=self.root/'a';q=self.root/'b';p.write_bytes(b'old');q.write_bytes(b'untouched');store=Checkpoints(self.meta);key=store.begin()
        store.apply(key,[(p,b'old',b'new')]);cp=store.load(key)
        cp['files'].append(dict(path=str(q),before=store._blob(key,b'untouched'),after=store._blob(key,b'planned')));cp['owner_pid']=2147483647;store.save(cp)
        store.recover_abandoned();self.assertTrue(store.load(key)['interrupted']);self.assertFalse(any(f['conflict'] for f in store.preview(key)['files']))
        store.restore(key);self.assertEqual(p.read_bytes(),b'old');self.assertEqual(q.read_bytes(),b'untouched')
    def test_corrupt_backup_blocks_restore_before_writes(self):
        p=self.root/'a';p.write_bytes(b'old');store=Checkpoints(self.meta);key=store.begin();store.apply(key,[(p,b'old',b'new')]);store.finish(key)
        sha=store.load(key)['files'][0]['before'];(store._path(key)/'blobs'/sha).write_bytes(b'corrupt')
        with self.assertRaises(ValueError):store.restore(key)
        self.assertEqual(p.read_bytes(),b'new')
    def test_disabled_agent_does_not_execute_file_tools(self):
        ctx={**self.ctx,'on':False};path=self.root/'not-created.txt'
        result=self.app._dispatch_agent_tool('escrever_ficheiro',dict(caminho=str(path),conteudo='no'),ctx,[])
        self.assertIn('desativado',result);self.assertFalse(path.exists())
