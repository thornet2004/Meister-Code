import json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import config
from installer.export_portable import replace_paths

class PortableIdentityTests(unittest.TestCase):
    def test_portable_executable_uses_its_own_settings_and_storage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'MeisterCode';root.mkdir();(root/'meistercode-portable.json').write_text('{}');global_dir=Path(tmp)/'Global'
            with patch.object(sys,'frozen',True,create=True),patch.object(sys,'executable',str(root/'MeisterCode.exe')),patch.dict(os.environ,{'APPDATA':str(global_dir)}):
                self.assertEqual(config.config_dir(),root/'Configuracao');self.assertEqual(config.application_root(),root);self.assertEqual(config.conversations_root(),root/'Conversas');self.assertEqual(config.projects_root(),root/'Projectos')
                cfg=config.default_config();cfg.update(storage_layout=2,storage_root=str(root));config.save_config(cfg);self.assertEqual(config.load_config()['storage_root'],str(root));self.assertFalse(global_dir.exists())
    def test_source_in_final_codigo_uses_same_portable_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'meistercode-portable.json').write_text('{}');(root/'Codigo').mkdir()
            with patch.object(sys,'frozen',False,create=True),patch('config.__file__',str(root/'Codigo/config.py')):self.assertEqual(config.portable_root(),root)
    def test_export_rebases_escaped_and_forward_slash_paths(self):
        old=Path('C:/source');new=Path('D:/MeisterCode');text=json.dumps(dict(a=str(old/'Ferramentas/a'),b=(old/'Conversas/c').as_posix()));out=json.loads(replace_paths(text,[(old,new)]));self.assertEqual(Path(out['a']),new/'Ferramentas/a');self.assertEqual(Path(out['b']),new/'Conversas/c')

if __name__=='__main__':unittest.main()
