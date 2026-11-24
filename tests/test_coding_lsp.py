"""Tabela de servidores LSP: que servidor trata cada ficheiro e o que se responde quando não há servidor.

Não arranca servidores verdadeiros; isso é o ``tests/lsp_languages_real_smoke.py``.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import coding_lsp
from coding_lsp import SERVERS, LanguageServers, kind_for


class FakeProcess:
    def poll(self):
        return None


class FakeClient:
    created = []

    def __init__(self, command, workspace, kind):
        self.command, self.workspace, self.kind, self.process, self.closed = command, workspace, kind, FakeProcess(), False
        FakeClient.created.append(self)

    def diagnose(self, path, timeout):
        return dict(path=str(path), server=self.kind, status='complete', diagnostics=[])

    def navigate(self, path, action, line, column):
        return dict(status='complete', server=self.kind, action=action, results=[])

    def close(self):
        self.closed = True


class ServerTableTests(unittest.TestCase):
    def test_every_extension_has_one_server_and_a_language_id(self):
        seen = {}
        for kind, server in SERVERS.items():
            self.assertTrue(('node' in server) != ('path' in server), kind)
            self.assertTrue(server['label'] and isinstance(server['args'], list), kind)
            for ext, language in server['languages'].items():
                self.assertEqual(ext, ext.lower())
                self.assertNotIn(ext, seen, 'a extensão %s está em dois servidores' % ext)
                seen[ext] = kind
                self.assertTrue(language)
        cases = {'a.py': 'python', 'a.PYI': 'python', 'a.tsx': 'typescript', 'a.cjs': 'typescript', 'index.HTML': 'html', 'a.scss': 'css', 'package.json': 'json',
                 'run.sh': 'bash', 'ci.yml': 'yaml', 'a.php': 'php', 'lib.rs': 'rust', 'a.hpp': 'cpp', 'a.c': 'cpp'}
        for name, kind in cases.items():
            self.assertEqual(kind_for(name), kind, name)
        for name in ('notas.txt', 'LEIA-ME.md', 'Makefile', 'foto.png', 'a.java', 'main.go'):
            self.assertIsNone(kind_for(name), name)
        self.assertEqual(coding_lsp.LANGUAGE_IDS['.h'], 'c')
        self.assertEqual(coding_lsp.LANGUAGE_IDS['.sh'], 'shellscript')

    def test_original_two_servers_keep_their_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            node = root / 'Ferramentas/REA/runtime/node-v24.22.1-win-x64/node.exe'
            node.parent.mkdir(parents=True)
            node.write_bytes(b'')
            modules = root / 'Ferramentas/_Runtime/lsp/node_modules'
            for rel in ('pyright/langserver.index.js', 'typescript-language-server/lib/cli.mjs'):
                (modules / rel).parent.mkdir(parents=True)
                (modules / rel).write_text('')
            with patch('config.application_root', return_value=root), patch('shutil.which', return_value=None):
                servers = LanguageServers()
                self.assertEqual(servers.command('python'), [str(node), str(modules / 'pyright/langserver.index.js'), '--stdio'])
                self.assertEqual(servers.command('typescript'), [str(node), str(modules / 'typescript-language-server/lib/cli.mjs'), '--stdio'])
                self.assertIsNone(servers.command('html'), 'pacote por instalar')
                self.assertIsNone(servers.command('rust'))
                self.assertEqual(servers.installed_extensions(), {'.py', '.pyi', '.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs'})
                status = {row['name']: row for row in servers.status()}
                self.assertEqual(list(status), list(SERVERS))
                self.assertTrue(status['python']['installed'] and not status['python']['connected'])
                self.assertEqual((status['php']['installed'], status['php']['source']), (False, 'bundled'))
                self.assertEqual((status['rust']['installed'], status['rust']['source'], status['rust']['executable']), (False, 'path', 'rust-analyzer'))

    def test_path_servers_are_used_only_when_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            source = root / 'lib.rs'
            source.write_text('fn main() {}\n')
            FakeClient.created = []
            with patch('config.application_root', return_value=root / 'app'), patch.object(coding_lsp, 'Client', FakeClient):
                servers = LanguageServers()
                with patch('shutil.which', return_value=None):
                    missing = servers.diagnose(root, source)
                    self.assertEqual(missing['status'], 'unavailable')
                    self.assertIn('rust-analyzer', missing['message'])
                    self.assertIn('PATH', missing['message'])
                    self.assertEqual(FakeClient.created, [])
                    self.assertEqual(servers.installed_extensions(), set())
                found = lambda name: 'C:/rust/bin/rust-analyzer.exe' if name == 'rust-analyzer' else None  # noqa: E731
                with patch('shutil.which', side_effect=found):
                    self.assertEqual(servers.diagnose(root, source)['server'], 'rust')
                    self.assertEqual(FakeClient.created[0].command, ['C:/rust/bin/rust-analyzer.exe'])
                    self.assertEqual(servers.navigate(root, source, 'symbols')['server'], 'rust')
                    self.assertEqual(len(FakeClient.created), 1, 'o mesmo workspace e linguagem reutilizam o processo')
                    self.assertEqual(servers.installed_extensions(), {'.rs'})
                    self.assertTrue(next(row for row in servers.status() if row['name'] == 'rust')['connected'])
                servers.close()
                self.assertTrue(FakeClient.created[0].closed)

    def test_unsupported_outside_workspace_and_missing_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / 'projeto').mkdir()
            with patch('config.application_root', return_value=root / 'app'), patch('shutil.which', return_value=None):
                servers = LanguageServers()
                other = servers.diagnose(root / 'projeto', root / 'projeto' / 'notas.txt')
                self.assertEqual(other['status'], 'unsupported')
                for word in ('Python', 'HTML', 'CSS', 'JSON', 'Bash', 'YAML', 'PHP', 'rust-analyzer', 'clangd'):
                    self.assertIn(word, other['message'])
                self.assertEqual(servers.diagnose(root / 'projeto', root / 'projeto' / 'a.css'), dict(path=str(root / 'projeto' / 'a.css'), status='unavailable', diagnostics=[], message='Servidor LSP não instalado.'))
                with self.assertRaises(ValueError):
                    servers.diagnose(root / 'projeto', root / 'fora.css')

    def test_results_say_what_the_server_does_not_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            which = {'shellcheck': None}
            found = lambda name: which.get(name, 'C:/bin/' + name)  # noqa: E731
            with patch('config.application_root', return_value=root / 'app'), patch.object(coding_lsp, 'Client', FakeClient), \
                    patch.object(LanguageServers, 'command', return_value=['servidor']), patch('shutil.which', side_effect=found):
                servers = LanguageServers()
                bash = servers.diagnose(root, root / 'run.sh')
                self.assertIn('shellcheck', bash['limits'])
                self.assertIn('NÃO significa', bash['limits'])
                which['shellcheck'] = 'C:/bin/shellcheck.exe'
                self.assertNotIn('limits', servers.diagnose(root, root / 'run.sh'))
                self.assertIn('estrutura do HTML', servers.diagnose(root, root / 'a.html')['limits'])
                self.assertIn('não são descarregados', servers.diagnose(root, root / 'a.json')['limits'])
                self.assertIn('esquema', servers.diagnose(root, root / 'a.yml')['limits'])
                for name in ('a.py', 'a.ts', 'a.css', 'a.php'):
                    self.assertNotIn('limits', servers.diagnose(root, root / name), name)
                self.assertNotIn('limits', servers.navigate(root, root / 'run.sh', 'symbols'))
                servers.close()

    def test_no_more_than_six_servers_stay_alive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            FakeClient.created = []
            with patch('config.application_root', return_value=root / 'app'), patch.object(coding_lsp, 'Client', FakeClient), \
                    patch.object(LanguageServers, 'command', return_value=['servidor']), patch('shutil.which', return_value='x'):
                servers = LanguageServers()
                for name in ('a.py', 'a.ts', 'a.html', 'a.css', 'a.json', 'a.sh', 'a.yaml', 'a.php'):
                    servers.diagnose(root, root / name)
                self.assertEqual(len(servers.clients), 6)
                self.assertEqual([client.kind for client in FakeClient.created if client.closed], ['python', 'typescript'])
                servers.close()

    def test_settings_keep_network_and_telemetry_off(self):
        settings = coding_lsp.Client.settings(None)
        self.assertIs(settings['intelephense']['telemetry']['enabled'], False)
        self.assertIs(settings['yaml']['schemaStore']['enable'], False)
        self.assertEqual(settings['telemetry']['telemetryLevel'], 'off')
        self.assertEqual(settings['python']['analysis']['typeCheckingMode'], 'basic', 'o que já existia não mudou')


if __name__ == '__main__':
    unittest.main()
