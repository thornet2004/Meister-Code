import base64,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import bench_catalog,api

class BenchTests(unittest.TestCase):
    def test_inventory_does_not_claim_source_is_installed_or_start_processes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);bench_catalog.provision(root)
            (root/'Lemon/source').mkdir()
            (root/'Flashrom/app').mkdir()
            (root/'Flashrom/app/flashrom.exe').write_bytes(b'fixture')
            with patch('subprocess.Popen',side_effect=AssertionError('No processes during inventory')):
                items={r['key']:r for r in bench_catalog.inventory(root)}
            self.assertFalse(items['Lemon']['installed']);self.assertTrue(items['Lemon']['source_installed'])
            self.assertTrue(items['Flashrom']['installed']);self.assertFalse(items['Pillow']['installed'])
            # Configuração do utilizador não é substituída numa nova preparação.
            settings=root/'Flashrom/configuracao.json';settings.write_text('{"executable":"custom"}')
            bench_catalog.provision(root);self.assertEqual(json.loads(settings.read_text())['executable'],'custom')

    def test_mcp_binary_preview_saved_without_base64_in_tool_text(self):
        png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j5YQAAAAASUVORK5CYII=')
        instance=api.Api();generated=[]
        try:
            with tempfile.TemporaryDirectory() as temp:
                folder=Path(temp);result=instance._capture_mcp_images({'content':[{'type':'image','mimeType':'image/png','data':base64.b64encode(png).decode()}]},generated,folder/'meta',folder/'media')
                self.assertEqual(Path(generated[0]['path']).read_bytes(),png)
                self.assertNotIn('data',result['content'][0]);self.assertTrue(generated[0]['mcp_preview'])
                rejected=instance._capture_mcp_images({'content':[{'type':'image','mimeType':'image/png','data':'!!!!'}]},generated,folder/'meta',folder/'media')
                self.assertEqual(len(generated),1);self.assertEqual(rejected['content'][0]['type'],'text')
        finally:instance._folder_tools.close();instance._mcp.close()
