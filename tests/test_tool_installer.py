"""Instalador das ferramentas (``tool_installer.py``), sem rede: os downloads são substituídos por ficheiros locais
e os programas do núcleo (7-Zip, npm, pip, msiexec) por uma função que imita o que produziriam.

O ensaio com downloads e programas verdadeiros faz-se à mão, numa pasta à parte:
``python tool_installer.py --root <pasta> instalar --tudo``.
"""
import subprocess
import re
import hashlib
import io
import json
import tarfile
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import tool_installer
from tool_installer import Installer, InstallError, expand, load_manifest, sources_markdown, state, validate


def make_zip(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as bundle:
        for name, content in files.items():
            bundle.writestr(name, content)
    return buffer.getvalue()


def make_tar(files):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w:gz') as bundle:
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            bundle.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


def sha(data):
    return hashlib.sha256(data).hexdigest()


class FakeResponse:
    def __init__(self, data, gate=None):
        self.data, self.gate, self.closed = data, gate, False

    def iter_content(self, size):
        for start in range(0, len(self.data), 4):
            if self.gate:
                self.gate()
            yield self.data[start:start + 4]

    def close(self):
        self.closed = True


def download(key, data, action='extract', to='app', **extra):
    url = 'https://example.test/%s-%s' % (key, extra.pop('name', 'ficheiro'))
    return url, dict(action=action, what=extra.pop('what', 'aplicação'), url=url, sha256=sha(data), bytes=len(data), file=url.rsplit('/', 1)[1], to=to, **extra)


def tool(key, steps, **extra):
    return dict(dict(key=key, name=key, group='A', repo='https://github.com/x/' + key.lower(), version='1.0', installed_mb=1, requires=[], note='', automatic=True, pending='', steps=steps), **extra)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'Ferramentas'
        self.served = {}
        self.requests = []
        self.patch = patch.object(tool_installer, '_open_url', side_effect=self.open_url)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def open_url(self, url):
        self.requests.append(url)
        if url not in self.served:
            raise OSError('404')
        return FakeResponse(self.served[url])

    def serve(self, key, data, **extra):
        url, step = download(key, data, **extra)
        self.served[url] = data
        return step

    def manifest(self, *tools):
        manifest = dict(version=1, reviewed='2026-11-19', groups={'A': 'Arquivos', 'N': 'Núcleo'}, tools=list(tools))
        validate(manifest)
        return manifest

    @staticmethod
    def results(job):
        return {row['key']: row['status'] for row in job['results']}


class InstallerTests(Base):
    def setUp(self):
        super().setUp()
        self.app = make_zip({'bin/tool.exe': b'binario', 'README.txt': b'ola'})
        self.source = make_zip({'repo-abc/main.c': b'int main(){}'})
        self.single = b'executavel unico'
        self.data = self.manifest(
            tool('Alpha', [self.serve('Alpha', self.app, publisher_digest=True)]),
            tool('Beta', [self.serve('Beta', self.source, action='source', to='source', what='código-fonte', repository='x/beta', commit='abc')], requires=['Alpha'], version=''),
            tool('Gamma', [self.serve('Gamma', self.single, action='copy', to='app/Gamma.exe')], version='2'),
            tool('Manual', [], automatic=False, pending='precisa de administrador'))
        self.alpha = self.data['tools'][0]['steps'][0]

    def test_installs_verifies_records_and_cleans_up(self):
        job = Installer(self.root, self.data).run(['Alpha', 'Beta', 'Gamma', 'Manual'])
        self.assertEqual(job['state'], 'done')
        self.assertEqual(self.results(job), dict(Alpha='installed', Beta='installed', Gamma='installed', Manual='pending'))
        self.assertIn('precisa de administrador', job['results'][3]['message'])
        self.assertEqual((self.root / 'Alpha/app/bin/tool.exe').read_bytes(), b'binario')
        self.assertEqual((self.root / 'Beta/source/repo-abc/main.c').read_bytes(), b'int main(){}')
        self.assertEqual((self.root / 'Gamma/app/Gamma.exe').read_bytes(), self.single)
        # registos no formato que o resto da app já lê
        self.assertEqual(json.loads((self.root / 'Alpha/instalacao.json').read_text()), dict(version='1.0', url=self.alpha['url'], sha256=sha(self.app), verified_publisher_digest=True))
        self.assertEqual(json.loads((self.root / 'Beta/fonte.json').read_text()), dict(repository='x/beta', commit='abc', sha256=sha(self.source)))
        self.assertEqual(json.loads((self.root / 'Alpha/instalado.json').read_text())['steps'], [sha(self.app)])
        # os ficheiros descarregados não ficam a ocupar espaço, nem sobram pastas temporárias
        leftovers = [str(p.relative_to(self.root)) for p in self.root.rglob('*') if 'downloads' in p.parts or p.name.startswith('.instalar-') or '.anterior-' in p.name or '.parte-' in p.name or p.name.endswith('.tmp')]
        self.assertEqual(leftovers, [])
        self.assertEqual({row['key']: row['status'] for row in state(self.root, self.data)}, dict(Alpha='installed', Beta='installed', Gamma='installed', Manual='pending'))
        # segunda vez: nada é descarregado
        before = len(self.requests)
        again = Installer(self.root, self.data).run(['Alpha', 'Beta', 'Gamma'])
        self.assertEqual(set(self.results(again).values()), {'already'})
        self.assertEqual(len(self.requests), before)

    def test_wrong_hash_is_rejected_and_previous_install_survives(self):
        Installer(self.root, self.data).run(['Alpha'])
        newer = make_zip({'bin/tool.exe': b'versao nova'})
        self.alpha['sha256'] = sha(newer)  # o manifesto pede outro ficheiro…
        self.data['tools'][0]['version'] = '1.1'
        job = Installer(self.root, self.data).run(['Alpha', 'Gamma'])   # …mas o servidor entrega o antigo
        self.assertEqual(self.results(job), dict(Alpha='failed', Gamma='installed'), 'uma falha não trava a seguinte')
        self.assertIn('SHA-256 diferente', job['results'][0]['message'])
        self.assertEqual((self.root / 'Alpha/app/bin/tool.exe').read_bytes(), b'binario', 'a instalação anterior ficou intacta')
        self.assertEqual(json.loads((self.root / 'Alpha/instalacao.json').read_text())['version'], '1.0')
        self.assertFalse((self.root / 'Alpha/downloads').exists())
        self.assertEqual(job['state'], 'done')
        # com o ficheiro certo, atualiza e substitui a pasta inteira
        self.served[self.alpha['url']] = newer
        job = Installer(self.root, self.data).run(['Alpha'])
        self.assertEqual(self.results(job), dict(Alpha='installed'))
        self.assertEqual((self.root / 'Alpha/app/bin/tool.exe').read_bytes(), b'versao nova')
        self.assertFalse((self.root / 'Alpha/app/README.txt').exists(), 'ficheiros da versão antiga não ficam misturados')

    def test_archive_escaping_the_folder_is_rejected(self):
        for name in ('../fora.txt', 'a/../../fora.txt', '/absoluto.txt'):
            evil = make_zip({'ok.txt': b'1', name: b'mau'})
            self.served[self.alpha['url']] = evil
            self.alpha['sha256'] = sha(evil)
            job = Installer(self.root, self.data).run(['Alpha'])
            self.assertEqual(self.results(job), dict(Alpha='failed'), name)
            self.assertFalse((self.root / 'Alpha/app').exists(), name)
            self.assertFalse((self.root / 'fora.txt').exists())
            self.assertFalse((self.root / 'Alpha/fora.txt').exists())
            self.assertEqual(job['state'], 'failed')

    def test_symbolic_links_inside_the_archive_are_skipped(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as bundle:
            bundle.writestr('repo/skills/bom/SKILL.md', b'conteudo')
            link = zipfile.ZipInfo('repo/.agents/skills/bom')
            link.external_attr = 0o120777 << 16
            bundle.writestr(link, '../../../../../fora')
        data = buffer.getvalue()
        self.served[self.alpha['url']] = data
        self.alpha['sha256'] = sha(data)
        job = Installer(self.root, self.data).run(['Alpha'])
        self.assertEqual(self.results(job), dict(Alpha='installed'))
        self.assertEqual((self.root / 'Alpha/app/repo/skills/bom/SKILL.md').read_bytes(), b'conteudo')
        self.assertFalse((self.root / 'Alpha/app/repo/.agents/skills/bom').exists(), 'a ligação não é criada nem escrita como ficheiro')

    def test_not_a_zip_download_error_and_oversized_file(self):
        garbage = b'isto nao e um zip'
        self.served[self.alpha['url']] = garbage
        self.alpha['sha256'] = sha(garbage)
        job = Installer(self.root, self.data).run(['Alpha'])
        self.assertIn('não é um zip válido', job['results'][0]['message'])
        gamma = self.data['tools'][2]['steps'][0]
        del self.served[gamma['url']]
        job = Installer(self.root, self.data).run(['Gamma'])
        self.assertIn('Falha ao descarregar', job['results'][0]['message'])
        self.served[gamma['url']] = b'x' * 100
        with patch.object(tool_installer, 'CHUNK', 4), patch('tool_installer.max', return_value=10, create=True):
            job = Installer(self.root, self.data).run(['Gamma'])
        self.assertEqual(self.results(job), dict(Gamma='failed'))
        self.assertIn('maior do que o esperado', job['results'][0]['message'])
        self.assertFalse(any(self.root.rglob('*.parte-*')))

    def test_cancel_stops_cleanly_and_keeps_what_was_installed(self):
        Installer(self.root, self.data).run(['Alpha'])
        started, release = threading.Event(), threading.Event()

        def gate():
            started.set()
            release.wait(5)

        self.patch.stop()
        self.patch = patch.object(tool_installer, '_open_url', side_effect=lambda url: FakeResponse(self.served[url], gate))
        self.patch.start()
        self.alpha['sha256'] = sha(make_zip({'outro': b'1'}))  # força nova descarga do Alpha
        installer = Installer(self.root, self.data)
        installer.start(['Alpha', 'Gamma'])
        with self.assertRaises(InstallError):
            installer.start(['Gamma'])          # uma instalação de cada vez
        self.assertTrue(started.wait(5))
        installer.cancel()
        release.set()
        installer.thread.join(10)
        job = installer.status()
        self.assertEqual(job['state'], 'cancelled')
        self.assertEqual(self.results(job), dict(Alpha='cancelled', Gamma='cancelled'))
        self.assertEqual((self.root / 'Alpha/app/bin/tool.exe').read_bytes(), b'binario')
        self.assertFalse((self.root / 'Gamma').exists())
        self.assertFalse(any(self.root.rglob('*.parte-*')))

    def test_dependencies_come_first_and_a_failed_one_blocks_its_dependents(self):
        self.assertEqual(expand(self.data, ['Beta', 'Gamma', 'Beta']), ['Alpha', 'Beta', 'Gamma'])
        job = Installer(self.root, self.data).run(['Beta'])
        self.assertEqual([(row['key'], row['status'], row.get('dependency', False)) for row in job['results']], [('Alpha', 'installed', True), ('Beta', 'installed', False)])
        with self.assertRaises(InstallError):
            Installer(self.root, self.data).start(['NaoExiste'])
        # dependência que falha: a dependente não é tentada, as outras continuam
        other = Path(self.tmp.name) / 'outra'
        self.alpha['sha256'] = '0' * 64
        job = Installer(other, self.data).run(['Beta', 'Gamma'])
        self.assertEqual(self.results(job), dict(Alpha='failed', Beta='failed', Gamma='installed'))
        self.assertIn('depende de Alpha', job['results'][1]['message'])
        self.assertFalse((other / 'Beta').exists())
        circular = json.loads(json.dumps(self.data))
        circular['tools'][0]['requires'] = ['Beta']
        with self.assertRaises(InstallError):
            expand(circular, ['Alpha'])

    def test_low_disk_space_is_refused_before_downloading(self):
        usage = type('Usage', (), {'free': 10})()
        with patch('shutil.disk_usage', return_value=usage):
            job = Installer(self.root, self.data).run(['Alpha'])
        self.assertIn('Espaço insuficiente', job['results'][0]['message'])
        self.assertEqual(self.requests, [])

    def test_manifest_validation(self):
        def broken(change):
            data = json.loads(json.dumps(self.data))
            change(data)
            with self.assertRaises(InstallError):
                validate(data)

        step = lambda data: data['tools'][0]['steps'][0]  # noqa: E731
        broken(lambda d: step(d).update(url='http://example.test/app.zip'))
        broken(lambda d: step(d).update(sha256=''))
        broken(lambda d: step(d).update(sha256='z' * 64))
        broken(lambda d: step(d).update(action='shell'))
        broken(lambda d: step(d).update(format='rar'))
        broken(lambda d: step(d).update(to='../fora'))
        broken(lambda d: step(d).update(to='C:/Windows'))
        broken(lambda d: step(d).update(file='sub/app.zip'))
        broken(lambda d: step(d).update(check='../../fora'))
        broken(lambda d: d['tools'][0].update(folder='../fora'))
        broken(lambda d: d['tools'][0].update(present='C:/Windows/System32'))
        broken(lambda d: d['tools'][0].update(cleanup=['..']))
        broken(lambda d: d['tools'][0]['steps'].append(dict(action='run', kind='powershell', check='x')))
        broken(lambda d: d['tools'][0]['steps'].append(dict(action='run', kind='npm-ci')))
        broken(lambda d: d['tools'][0]['steps'].append(dict(action='run', kind='npm-ci', check='x', dir='../..')))
        broken(lambda d: d['tools'][1].update(requires=['Fantasma']))
        broken(lambda d: d['tools'].append(dict(d['tools'][0])))
        broken(lambda d: d.update(version=2))


class FormatsAndRunStepsTests(Base):
    """Formatos além do zip e passos que executam programas do núcleo (aqui imitados)."""

    def fake_command(self, installer):
        calls = []

        def command(command, cwd, timeout, failure, env=None):
            # o msiexec recebe a linha de comando já escrita (texto); os outros programas recebem uma lista
            words = [command] if isinstance(command, str) else [str(word) for word in command]
            calls.append(words)
            if self.fail_on and any(self.fail_on in word for word in words):
                raise InstallError(failure + ' (código 1).')
            if 'ci' in words:                                   # npm ci
                (Path(cwd) / 'node_modules' / 'pacote').mkdir(parents=True, exist_ok=True)
                (Path(cwd) / 'node_modules' / 'pacote' / 'index.js').write_text('x')
            if 'run' in words and 'build' in words:             # npm run build
                (Path(cwd) / 'dist').mkdir(exist_ok=True)
                (Path(cwd) / 'dist' / 'index.js').write_text('x')
            if 'pip' in words:                                  # pip install --target
                target = Path(words[words.index('--target') + 1])
                (target / 'serial').mkdir(parents=True, exist_ok=True)
                (target / 'serial' / '__init__.py').write_text('')
                self.pip_listing = Path(words[words.index('-r') + 1]).read_text(encoding='utf-8').split()
            if words[0].endswith('7zr.exe'):                    # desempacotar o 7-Zip
                out = Path(next(word[2:] for word in words if word.startswith('-o')))
                out.mkdir(parents=True, exist_ok=True)
                (out / '7z.exe').write_bytes(b'7z')
            if words[0].lower().startswith('msiexec'):
                out = Path(re.search(r'TARGETDIR="([^"]+)"', words[0]).group(1))
                (out / 'bin').mkdir(parents=True, exist_ok=True)
                (out / 'bin' / 'app.exe').write_bytes(b'x')
            return ''

        installer._command = command
        return calls

    def setUp(self):
        super().setUp()
        self.fail_on = ''
        self.pip_listing = []
        # um Node e um Python «instalados» no núcleo
        for path in ('_Runtime/node/node-v1/node.exe', '_Runtime/node/node-v1/node_modules/npm/bin/npm-cli.js', '_Runtime/python/cpython-x/python.exe'):
            (self.root / path).parent.mkdir(parents=True, exist_ok=True)
            (self.root / path).write_bytes(b'')

    def test_tar_with_strip_and_merge_of_several_archives(self):
        python = make_tar({'python/python.exe': b'py', 'python/Lib/os.py': b'os'})
        one = make_tar({'.PKGINFO': b'x', 'ucrt64/bin/flashrom.exe': b'f'})
        two = make_tar({'.PKGINFO': b'y', 'ucrt64/bin/libusb.dll': b'u', 'ucrt64/share/doc.txt': b'd'})
        evil = make_tar({'../fora.txt': b'mau'})
        data = self.manifest(
            tool('CorePython', [self.serve('CorePython', python, format='tar', strip=1, to='cpython-1', check='cpython-1/python.exe')], folder='_Runtime/python2', group='N'),
            tool('Flash', [self.serve('Flash', one, name='um', format='tar', merge=True, only_top=['ucrt64'], check='app/ucrt64/bin/flashrom.exe'),
                           self.serve('Flash', two, name='dois', format='tar', merge=True, only_top=['ucrt64'], check='app/ucrt64/bin/libusb.dll')]),
            tool('Mau', [self.serve('Mau', evil, format='tar')]))
        job = Installer(self.root, data).run(['CorePython', 'Flash', 'Mau'])
        self.assertEqual(self.results(job), dict(CorePython='installed', Flash='installed', Mau='failed'))
        self.assertEqual((self.root / '_Runtime/python2/cpython-1/python.exe').read_bytes(), b'py', 'a pasta de topo do tar foi retirada')
        self.assertFalse((self.root / '_Runtime/python2/instalacao.json').exists(), 'o núcleo não leva os registos das ferramentas')
        self.assertEqual(sorted(p.name for p in (self.root / 'Flash/app/ucrt64/bin').iterdir()), ['flashrom.exe', 'libusb.dll'])
        self.assertFalse((self.root / 'Flash/app/.PKGINFO').exists())
        record = json.loads((self.root / 'Flash/instalacao.json').read_text())
        self.assertEqual(len(record['packages']), 2)
        self.assertFalse((Path(self.tmp.name) / 'fora.txt').exists())
        self.assertFalse((self.root / 'fora.txt').exists())
        self.assertEqual(Installer(self.root, data).run(['Flash'])['results'][0]['status'], 'already')

    def test_seven_zip_formats_need_the_core_seven_zip(self):
        data = self.manifest(tool('Magick', [self.serve('Magick', b'arquivo 7z', format='7zip', check='app/magick.exe')]))
        job = Installer(self.root, data).run(['Magick'])
        self.assertEqual(self.results(job), dict(Magick='failed'))
        self.assertIn('Falta o 7-Zip do núcleo', job['results'][0]['message'])
        seven = self.root / '_Runtime/7zip/full/7z.exe'
        seven.parent.mkdir(parents=True)
        seven.write_bytes(b'')
        installer = Installer(self.root, data)

        def command(command, cwd, timeout, failure, env=None):
            out = Path(next(str(word)[2:] for word in command if str(word).startswith('-o')))
            out.mkdir(parents=True, exist_ok=True)
            (out / 'magick.exe').write_bytes(b'magick')
            return ''

        installer._command = command
        self.assertEqual(self.results(installer.run(['Magick'])), dict(Magick='installed'))
        self.assertEqual((self.root / 'Magick/app/magick.exe').read_bytes(), b'magick')

    def test_core_and_run_steps_in_order(self):
        wheel_a, wheel_b = b'roda a', b'roda b'
        lock_root = Path(self.tmp.name) / 'app'
        (lock_root / 'installer/lsp').mkdir(parents=True)
        (lock_root / 'installer/lsp/package.json').write_text('{}')
        (lock_root / 'installer/lsp/package-lock.json').write_text('{"lock": 1}')
        source = make_zip({'repo-1/package.json': b'{}', 'repo-1/plugin.py': b'plugin'})
        data = self.manifest(
            tool('Core7Zip', [self.serve('Core7Zip', b'7zr', action='copy', name='7zr.exe', to='7zr.exe'), self.serve('Core7Zip', b'setup', action='copy', name='7z-setup.exe', to='7z-setup.exe'),
                              dict(action='run', kind='sevenzip-setup', what='desempacotar', archive='7z-setup.exe', to='full', check='full/7z.exe')], folder='_Runtime/7zip', group='N', present='_Runtime/7zip/full/7z.exe'),
            tool('CorePackages', [self.serve('CorePackages', wheel_a, action='copy', name='a-1.0-py3-none-any.whl', to='wheels/a-1.0-py3-none-any.whl', transient=True),
                                  self.serve('CorePackages', wheel_b, action='copy', name='b-2.0-py3-none-any.whl', to='wheels/b-2.0-py3-none-any.whl', transient=True),
                                  dict(action='run', kind='pip-wheels', what='instalar', **{'from': 'wheels'}, check='pacotes-instalados.json', packages=[dict(name='a', version='1.0'), dict(name='b', version='2.0')])],
                 folder='_Runtime/pacotes', group='N', present='_Runtime/site-packages/serial', cleanup=['wheels']),
            tool('CoreLSP', [dict(action='run', kind='npm-ci', what='lsp', dir='.', lock_from='installer/lsp', check='node_modules/pacote/index.js')], folder='_Runtime/lsp', group='N'),
            tool('Serial', [], requires=['CorePackages'], present='_Runtime/site-packages/serial'),
            tool('Fantasma', [], requires=['CorePackages'], present='_Runtime/site-packages/nao_existe'),
            tool('Servidor', [self.serve('Servidor', source, action='source', to='source', check='source/repo-1/package.json', repository='x/y', commit='1'),
                              dict(action='run', kind='npm-ci', what='dependências', dir='source/repo-1', check='source/repo-1/node_modules'),
                              dict(action='run', kind='npm-run', script='build', what='construir', dir='source/repo-1', check='source/repo-1/dist/index.js'),
                              dict(action='run', kind='copy-file', what='plugin', **{'from': 'source/*/plugin.py'}, to='profile/plug-ins/p/plugin.py', check='profile/plug-ins/p/plugin.py')]),
            tool('Pacote', [self.serve('Pacote', make_zip({'x.msi': b'msi'}), to='app/instalador', check='app/instalador/x.msi'),
                            dict(action='run', kind='msi-extract', what='msi', archive='app/instalador/x.msi', to='app/portable', check='app/portable/bin')]))
        installer = Installer(self.root, data)
        calls = self.fake_command(installer)
        with patch.object(tool_installer, 'app_dir', return_value=lock_root):
            job = installer.run(['Serial', 'Fantasma', 'CoreLSP', 'Servidor', 'Pacote', 'Core7Zip'])
        self.assertEqual([row['key'] for row in job['results']], ['CorePackages', 'Serial', 'Fantasma', 'CoreLSP', 'Servidor', 'Pacote', 'Core7Zip'])
        self.assertEqual(self.results(job), dict(CorePackages='installed', Serial='already', Fantasma='failed', CoreLSP='installed', Servidor='installed', Pacote='installed', Core7Zip='installed'))
        self.assertIn('falta _Runtime/site-packages/nao_existe', job['results'][2]['message'])
        # pacotes Python: instalados dos ficheiros conferidos, sem rede; as rodas são apagadas no fim
        pip = next(call for call in calls if 'pip' in call)
        for flag in ('--no-index', '--no-deps', '--target'):
            self.assertIn(flag, pip)
        self.assertEqual(sorted(Path(item).name for item in self.pip_listing), ['a-1.0-py3-none-any.whl', 'b-2.0-py3-none-any.whl'])
        self.assertFalse((self.root / '_Runtime/pacotes/wheels').exists())
        self.assertEqual(json.loads((self.root / '_Runtime/installed-packages.json').read_text()), [dict(name='a', version='1.0'), dict(name='b', version='2.0')])
        # npm: sempre «ci» com o bloqueio que vem com a app, sem scripts
        lsp = next(call for call in calls if 'ci' in call)
        self.assertIn('--ignore-scripts', lsp)
        self.assertEqual((self.root / '_Runtime/lsp/package-lock.json').read_text(), '{"lock": 1}')
        self.assertTrue(any('run' in call and 'build' in call for call in calls))
        self.assertEqual((self.root / 'Servidor/profile/plug-ins/p/plugin.py').read_bytes(), b'plugin')
        msi = next(call for call in calls if call[0].lower().startswith('msiexec'))
        self.assertTrue(msi[0].startswith('msiexec.exe /a "'), 'o MSI é só desempacotado, não instalado')
        # as aspas ficam depois do «=»: com a pasta em «C:\Program Files\…» o msiexec recusava a outra forma (código 1639)
        self.assertRegex(msi[0], r' TARGETDIR="[^"]+"$')
        self.assertNotIn('"TARGETDIR=', msi[0])
        self.assertTrue((self.root / 'Pacote/app/portable/bin/app.exe').is_file())
        self.assertFalse(any(self.root.rglob('.pip-*')) or any(self.root.rglob('.msi-*')))
        self.assertTrue((self.root / '_Runtime/7zip/full/7z.exe').is_file())
        # tudo o que ficou instalado é reconhecido; nada volta a ser descarregado nem executado
        calls.clear()
        before = len(self.requests)
        with patch.object(tool_installer, 'app_dir', return_value=lock_root):
            again = Installer(self.root, data)
            self.fake_command(again)
            job = again.run(['Serial', 'CoreLSP', 'Servidor', 'Pacote', 'Core7Zip'])
        self.assertEqual(set(self.results(job).values()), {'already'})
        self.assertEqual((calls, len(self.requests)), ([], before))

    def test_a_failing_program_fails_the_tool_and_keeps_the_record_of_finished_steps(self):
        source = make_zip({'repo-1/package.json': b'{}'})
        data = self.manifest(tool('Servidor', [self.serve('Servidor', source, action='source', to='source', check='source/repo-1/package.json', repository='x/y', commit='1'),
                                               dict(action='run', kind='npm-ci', what='dependências', dir='source/repo-1', check='source/repo-1/node_modules'),
                                               dict(action='run', kind='npm-run', script='build', what='construir', dir='source/repo-1', check='source/repo-1/dist/index.js')]))
        installer = Installer(self.root, data)
        self.fake_command(installer)
        self.fail_on = 'build'
        job = installer.run(['Servidor'])
        self.assertEqual(self.results(job), dict(Servidor='failed'))
        self.assertIn('npm «build» falhou', job['results'][0]['message'])
        self.assertEqual(state(self.root, data)[0]['status'], 'partial')
        # nova tentativa: retoma no passo que falhou, sem voltar a descarregar
        self.fail_on = ''
        before = len(self.requests)
        retry = Installer(self.root, data)
        calls = self.fake_command(retry)
        self.assertEqual(self.results(retry.run(['Servidor'])), dict(Servidor='installed'))
        self.assertEqual(len(self.requests), before)
        self.assertEqual(len(calls), 1, 'só o passo que faltava')

    def test_previous_installs_are_recognised_without_a_record(self):
        data = self.manifest(tool('Velha', [self.serve('Velha', b'x', check='app/x.exe')], present='Velha/app'),
                             tool('Registada', [self.serve('Registada', b'y', check='app/y.exe')]))
        self.assertEqual([row['status'] for row in state(self.root, data)], ['missing', 'missing'])
        (self.root / 'Velha/app').mkdir(parents=True)
        (self.root / 'Velha/app/qualquer.dll').write_bytes(b'')
        (self.root / 'Registada/app').mkdir(parents=True)
        (self.root / 'Registada/app/y.exe').write_bytes(b'')
        (self.root / 'Registada/provenance.json').write_text(json.dumps([dict(file='y', sha256=sha(b'y'))]))
        self.assertEqual([row['status'] for row in state(self.root, data)], ['installed', 'installed'])
        self.assertEqual(self.results(Installer(self.root, data).run(['Velha', 'Registada'])), dict(Velha='already', Registada='already'))
        self.assertEqual(self.requests, [])


class WindowsLockTests(Base):
    """O Windows pode recusar por instantes a troca de um ficheiro acabado de escrever (antivírus, indexador)."""

    def test_a_momentary_access_denied_does_not_fail_the_install(self):
        from pathlib import Path as RealPath
        data = self.manifest(tool('Alpha', [self.serve('Alpha', make_zip({'a.exe': b'a'}))]))
        original, failures = RealPath.replace, {'left': 3}

        def flaky(source, target):
            if str(target).endswith('instalado.json') and failures['left']:
                failures['left'] -= 1
                raise PermissionError(5, 'Acesso negado')
            return original(source, target)

        with patch.object(RealPath, 'replace', flaky), patch.object(tool_installer.time, 'sleep') as sleep:
            job = Installer(self.root, data).run(['Alpha'])
        self.assertEqual(self.results(job), dict(Alpha='installed'), job)
        self.assertEqual((failures['left'], sleep.call_count >= 3), (0, True))
        self.assertTrue((self.root / 'Alpha/instalado.json').is_file())

    def test_a_lasting_lock_is_still_reported(self):
        source = self.root / 'a.tmp'
        self.root.mkdir(parents=True)
        source.write_text('x', encoding='utf-8')
        with patch.object(type(source), 'replace', side_effect=PermissionError(5, 'Acesso negado')), patch.object(tool_installer.time, 'sleep') as sleep:
            with self.assertRaises(PermissionError):
                tool_installer._replace(source, self.root / 'a.json')
        self.assertEqual(sleep.call_count, 11)


class SupportFilesTests(Base):
    """Sem ``ferramenta.json`` a app não descobre a ferramenta: o instalador põe-no na pasta, a partir do que vem com a app."""

    def setUp(self):
        super().setUp()
        self.package = Path(self.tmp.name) / 'pacote'
        support = self.package / 'tool_support' / 'Alpha'
        support.mkdir(parents=True)
        (support / 'ferramenta.json').write_text('{"version": 1, "name": "Alpha"}', encoding='utf-8')
        (support / 'configuracao.json').write_text('{"executable": ""}', encoding='utf-8')
        (support / 'instalacao.json').write_text('{"sha256": "registo antigo, não se copia"}', encoding='utf-8')
        self.app_dir = patch.object(tool_installer, 'app_dir', return_value=self.package)
        self.app_dir.start()
        self.data = self.manifest(tool('Alpha', [self.serve('Alpha', make_zip({'a.exe': b'a'}))]), tool('Beta', [self.serve('Beta', make_zip({'b.exe': b'b'}))]),
                                  tool('Nucleo', [self.serve('Nucleo', make_zip({'n.exe': b'n'}))], group='N', folder='_Runtime/nucleo'))

    def tearDown(self):
        self.app_dir.stop()
        super().tearDown()

    def test_support_files_are_copied_after_install_and_never_overwritten(self):
        installer = Installer(self.root, self.data)
        self.assertEqual(self.results(installer.run(['Alpha', 'Beta', 'Nucleo'])), dict(Alpha='installed', Beta='installed', Nucleo='installed'))
        self.assertEqual(json.loads((self.root / 'Alpha/ferramenta.json').read_text(encoding='utf-8'))['name'], 'Alpha')
        self.assertTrue((self.root / 'Alpha/configuracao.json').is_file())
        self.assertNotIn('registo antigo', (self.root / 'Alpha/instalacao.json').read_text(encoding='utf-8'), 'os registos são escritos pelo instalador, não copiados')
        self.assertFalse((self.root / 'Beta/ferramenta.json').exists(), 'sem ficheiros de apoio na app, nada é inventado')
        self.assertFalse((self.root / '_Runtime/nucleo/ferramenta.json').exists())
        # o utilizador mudou a configuração; uma instalação antiga sem o manifesto ganha-o sem perder nada
        (self.root / 'Alpha/configuracao.json').write_text('{"executable": "C:/meu/caminho.exe"}', encoding='utf-8')
        (self.root / 'Alpha/ferramenta.json').unlink()
        self.assertEqual(self.results(installer.run(['Alpha'])), dict(Alpha='already'))
        self.assertTrue((self.root / 'Alpha/ferramenta.json').is_file())
        self.assertIn('meu/caminho', (self.root / 'Alpha/configuracao.json').read_text(encoding='utf-8'))

    def test_running_from_the_source_tree_uses_the_tracked_files_and_skips_its_own_folder(self):
        source = self.package / 'Ferramentas' / 'Beta'
        source.mkdir(parents=True)
        (source / 'ferramenta.json').write_text('{"version": 1, "name": "Beta"}', encoding='utf-8')
        self.assertEqual(tool_installer.support_dir('Beta'), source)
        self.assertEqual(tool_installer.copy_support(self.data['tools'][1], source), [], 'a pasta de destino é a própria origem')
        self.assertEqual(tool_installer.copy_support(self.data['tools'][1], self.root / 'Beta'), ['ferramenta.json'])
        self.assertIsNone(tool_installer.support_dir('NaoExiste'))


class BridgeTests(unittest.TestCase):
    """Os três métodos que o painel «Atualizar ferramentas» chama."""

    def setUp(self):
        import api
        import config
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        settings = self.root / 'settings'
        settings.mkdir()
        self.data = make_zip({'rtl_433.exe': b'binario'})
        self.patches = [patch('config.config_dir', return_value=settings), patch('config.application_root', return_value=self.root / 'app'),
                        patch.object(tool_installer, '_open_url', side_effect=self.open_url)]
        for item in self.patches:
            item.start()
        config.save_config(config.default_config())
        self.requests = []
        self.app = api.Api()

    def tearDown(self):
        installer = getattr(self.app, '_tool_installer', None)
        if installer:
            installer.close()
        self.app._lsp.close()
        self.app._mcp.close()
        self.app._folder_tools.close()
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()

    def open_url(self, url):
        self.requests.append(url)
        return FakeResponse(self.data)

    def test_listing_reads_only_and_install_goes_to_the_app_folder(self):
        listing = self.app.get_tool_updates()
        self.assertTrue(listing['ok'], listing)
        self.assertEqual(self.requests, [], 'listar não contacta a rede')
        self.assertEqual(len(listing["tools"]), 46)
        self.assertEqual(listing['root'], str(self.root / 'app' / 'Ferramentas'))
        self.assertEqual(listing['job']['state'], 'idle')
        self.assertGreater(listing['free_bytes'], 0)
        self.assertFalse((self.root / 'app' / 'Ferramentas').exists(), 'listar não cria pastas')
        rows = {row['key']: row for row in listing['tools']}
        self.assertEqual((rows['RTL433']['status'], rows['CorePython']['status'], rows['Hunyuan3D2']['status']), ('missing', 'missing', 'pending'))
        self.assertIs(rows['KicadHappy']['integrated'], False)
        self.assertEqual(rows['GIMP']['runs'], ['copy-file', 'setup-exe'])
        for bad in ([], 'RTL433', None, [1], ['RTL433'] * 101):
            self.assertFalse(self.app.start_tool_updates(bad)['ok'])
        self.assertIn('desconhecida', self.app.start_tool_updates(['NaoExiste'])['error'])
        # o ficheiro servido não é o do manifesto: é rejeitado pelo SHA-256 e nada fica instalado
        started = self.app.start_tool_updates(['RTL433', 'Hunyuan3D2'])
        self.assertTrue(started['ok'], started)
        self.app._tool_installer.thread.join(20)
        job = self.app.get_tool_updates()['job']
        self.assertEqual({row['key']: row['status'] for row in job['results']}, dict(RTL433='failed', Hunyuan3D2='pending'))
        self.assertIn('SHA-256 diferente', job['results'][0]['message'])
        self.assertFalse((self.root / 'app' / 'Ferramentas' / 'RTL433' / 'app').exists())
        self.assertEqual(self.requests, ['https://github.com/merbanan/rtl_433/releases/download/25.12/rtl_433-win-x64-25.12.zip'])
        self.assertTrue(self.app.cancel_tool_updates()['ok'])

    def test_installs_through_the_bridge_when_the_file_matches(self):
        manifest = load_manifest()
        step = next(item for item in manifest['tools'] if item['key'] == 'RTL433')['steps'][0]
        step['sha256'] = sha(self.data)
        with patch.object(tool_installer, 'load_manifest', return_value=manifest):
            self.assertTrue(self.app.start_tool_updates(['RTL433'])['ok'])
            self.app._tool_installer.thread.join(20)
            listing = self.app.get_tool_updates()
        self.assertEqual(listing['job']['results'][0]['status'], 'installed', listing['job'])
        self.assertEqual(next(row for row in listing['tools'] if row['key'] == 'RTL433')['status'], 'installed')
        self.assertEqual((self.root / 'app' / 'Ferramentas' / 'RTL433' / 'app' / 'rtl_433.exe').read_bytes(), b'binario')


class RealManifestTests(unittest.TestCase):
    """O manifesto que vai com a app."""

    def test_shipped_manifest_is_valid_and_complete(self):
        manifest = load_manifest()
        tools = {item['key']: item for item in manifest['tools']}
        self.assertEqual(len(tools), 46)
        self.assertEqual([key for key, item in tools.items() if item['group'] == 'N'], ['Core7Zip', 'CoreNode', 'CorePython', 'CorePackages', 'CoreLSP'])
        for key, item in tools.items():
            self.assertTrue(item['repo'].startswith('https://'), key)
            self.assertTrue(40 <= len(item.get('description', '')) <= 220 and item['description'].endswith('.'), key + ': falta a descrição (o que faz e para que serve)')
            self.assertIn(item['group'], manifest['groups'], key)
            self.assertTrue(item['automatic'] or item['pending'], key + ': o que não é automático diz porquê')
            self.assertTrue(item['steps'] or item.get('present'), key + ': sem passos, tem de haver um sinal de presença')
            if item['group'] == 'N':
                self.assertTrue(item['folder'].startswith('_Runtime/'), key)
        # a única que não se instala sozinha é a que o user mandou bloquear: a licença exclui a União Europeia
        self.assertEqual([key for key, item in tools.items() if not item['automatic']], ['Hunyuan3D2'])
        self.assertIn('União Europeia', tools['Hunyuan3D2']['pending'])
        # só uma ferramenta executa um instalador de terceiros, e isso está dito
        runs = {key: [step['kind'] for step in item['steps'] if step['action'] == 'run'] for key, item in tools.items()}
        self.assertEqual([key for key, kinds in runs.items() if 'setup-exe' in kinds], ['GIMP'])
        self.assertIn('EXECUTA', tools['GIMP']['note'])
        # tudo o que precisa do 7-Zip, do Node ou do Python do núcleo declara-o
        for key, item in tools.items():
            needs = set(expand(manifest, [key])) - {key}
            if any(step.get('format') in ('7zip', 'zst') for step in item['steps']):
                self.assertIn('Core7Zip', needs, key)
            if any(step.get('kind') in ('pip-wheels', 'pip-source') for step in item['steps']):
                self.assertIn('CorePython', needs, key)
            if any(step.get('kind') in ('npm-ci', 'npm-run') for step in item['steps']) and key != 'REA':
                self.assertIn('CoreNode', needs, key)
        # os bloqueios do npm vêm com a app
        base = Path(tool_installer.__file__).resolve().parent
        for item in tools.values():
            for step in item['steps']:
                if step.get('lock_from'):
                    self.assertTrue((base / step['lock_from'] / 'package-lock.json').is_file(), step['lock_from'])
        # as pastas do manifesto são as que a app conhece
        # conta o que está no git: uma pasta que ficou no disco de uma ferramenta retirada da lista não é da app
        listed = subprocess.run(['git', 'ls-files', 'Ferramentas/*/ferramenta.json'], cwd=base, capture_output=True, text=True, encoding='utf-8')
        tracked = {Path(line).parent.name for line in listed.stdout.splitlines() if line.strip()} if listed.returncode == 0 else set()
        if tracked:
            # «direct»: usada pela própria app (o ditado usa o Whisper), sem ferramenta.json
            self.assertEqual({key for key, item in tools.items() if item.get('integrated', True) and item['group'] != 'N' and not item.get('direct')}, tracked)
            self.assertEqual({key for key, item in tools.items() if not item.get('integrated', True)}, {key for key, item in tools.items() if item['group'] == 'E'})

    def test_every_integrated_tool_ships_its_manifest_in_the_package(self):
        base = Path(tool_installer.__file__).resolve().parent
        spec = (base / 'Studio de Media.spec').read_text(encoding='utf-8')
        self.assertIn("'tool_support/'", spec, 'o pacote leva os ficheiros de apoio')
        for name in tool_installer.SUPPORT_FILES:
            self.assertIn(repr(name), spec, name)
        for item in load_manifest()['tools']:
            if item.get('integrated', True) and item['group'] != 'N' and not item.get('direct') and (base / 'Ferramentas').is_dir():
                self.assertIsNotNone(tool_installer.support_dir(item['key']), item['key'] + ': sem ferramenta.json a app não a descobre depois de instalada')

    def test_tracked_tool_manifests_have_no_paths_of_this_computer(self):
        base = Path(tool_installer.__file__).resolve().parent
        for path in [item for name in tool_installer.SUPPORT_FILES for item in (base / 'Ferramentas').glob('*/' + name) if tool_installer.support_dir(item.parent.name)] + [base / 'tools_manifest.json']:
            text = path.read_text(encoding='utf-8')
            self.assertNotIn('Users\\\\', text, path.name + ' de ' + path.parent.name)
            self.assertNotIn('Users/', text, path.name + ' de ' + path.parent.name)

    def test_sources_document_matches_the_manifest(self):
        manifest = load_manifest()
        text = sources_markdown(manifest)
        for item in manifest['tools']:
            self.assertIn('<%s>' % item['repo'], text)
            for step in item['steps']:
                if step['action'] != 'run' and not step.get('transient'):
                    self.assertIn(step['url'], text)
                    self.assertIn(step['sha256'], text)
        document = Path(tool_installer.__file__).resolve().parent / 'Sources_ferramentas.md'
        self.assertEqual(document.read_text(encoding='utf-8').replace('\r\n', '\n'), text, 'Sources_ferramentas.md desatualizado: correr "python tool_installer.py fontes"')


if __name__ == '__main__':
    unittest.main()
