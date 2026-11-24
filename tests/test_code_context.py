import json,tempfile,unittest,os
from pathlib import Path
from code_context import CodeIndex,Continuity

class CodeContextTests(unittest.TestCase):
    def test_index_incremental_search_symbols_stale_and_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);meta=root/'.studio';path=root/'engine.py';path.write_text('class Motor:\n def calcular_bonus(self, valor):\n  return valor * 2\n',encoding='utf-8');(root/'node_modules').mkdir();(root/'node_modules/secret.py').write_text('def calcular_bonus(): pass')
            index=CodeIndex(meta,root);report=index.refresh();self.assertEqual(report['indexed'],1);self.assertEqual(index.refresh()['updated'],0)
            found=index.search('calcular_bonus');self.assertEqual(found['results'][0]['path'],'engine.py');self.assertIn('return valor',found['results'][0]['excerpt'])
            self.assertEqual(index.search('calcular_bonus',symbol_query=True)['results'][0]['name'],'calcular_bonus')
            packed=index.context('calcular_bonus');self.assertLessEqual(len(packed),14000);json.loads(packed)
            path.write_text('class Outro: pass\n');self.assertTrue(index.search('calcular_bonus')['results'][0]['stale']);index.refresh();self.assertEqual(index.search('calcular_bonus')['results'],[])
            path.unlink();self.assertEqual(index.refresh()['indexed'],0)
    def test_index_root_guard_sensitive_files_and_utf8_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);meta=root/'.studio';(root/'credentials.json').write_text('{"token":"secret"}');(root/'bad.py').write_bytes(b'\0abc');(root/'large.py').write_bytes(b'x'*(1024*1024+1));(root/'a.py').write_text('def seguro(): pass')
            report=CodeIndex(meta,root).refresh();self.assertEqual(report['indexed'],1);self.assertTrue(report['truncated'])
            with self.assertRaises(ValueError):CodeIndex(meta,root/'other').search('seguro')
    def test_continuity_update_done_remove_and_bounded_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Continuity(tmp);data=store.update('decision','Usar SQLite.');decision=data['decisions'][0]['id'];data=store.update('task','Implementar cache.');task=data['tasks'][0]['id'];store.update('task','Implementar cache.',task,'done')
            self.assertEqual(Continuity(tmp).load()['tasks'][0]['state'],'done');self.assertIn('SQLite',store.prompt());store.update('remove',item_id=decision);self.assertFalse(store.load()['decisions'])
            with self.assertRaises(ValueError):store.update('task','alterar',item_id='missing')
    def test_stale_content_with_preserved_timestamp_can_be_refreshed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'a.py';p.write_text('def before(): pass\n');stamp=p.stat();index=CodeIndex(root/'.studio',root);index.refresh();p.write_text('def afterx(): pass\n');os.utime(p,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
            self.assertTrue(index.search('before')['results'][0]['stale']);index.refresh();self.assertEqual(index.search('afterx',symbol_query=True)['results'][0]['name'],'afterx')
