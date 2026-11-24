"""Instalador das ferramentas a partir de ``tools_manifest.json``.

O pacote de distribuição não leva as ferramentas (são vários GB): leva o manifesto, com o endereço,
a versão e o SHA-256 de cada ficheiro, e este módulo instala-as uma a uma — primeiro o núcleo
partilhado (7-Zip, Node, Python, pacotes Python, servidores LSP), depois as ferramentas.

Regras:
- só HTTPS, e só os endereços do manifesto; nada de «última versão»;
- um ficheiro só é usado depois de o SHA-256 bater certo com o do manifesto;
- extrai-se para uma pasta temporária e só então se põe no sítio: uma instalação que falha a
  meio não estraga a que estava a funcionar;
- uma ferramenta que falha não impede as seguintes (exceto as que dependem dela);
- os passos que executam programas (``run``) são de tipos fixos definidos aqui; o manifesto
  escolhe o tipo e os parâmetros, nunca uma linha de comandos;
- o que o motor não instala sozinho fica dito («pending»), não é ignorado em silêncio.

Linha de comandos (para ensaios; a pasta de destino é sempre indicada):
    python tool_installer.py --root <pasta> listar
    python tool_installer.py --root <pasta> instalar RTL433 OpenOCD
    python tool_installer.py --root <pasta> instalar --tudo
    python tool_installer.py fontes            (reescreve Sources_ferramentas.md a partir do manifesto)
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

MANIFEST_NAME = 'tools_manifest.json'
RECORD_NAME = 'instalado.json'
# lista extra, na pasta Ferramentas de cada instalação: o que o utilizador mandou o agente acrescentar
EXTRA_NAME = 'ferramentas-extra.json'
EXTRA_GROUP = 'U'
EXTRA_TITLE = 'Acrescentadas por ti nesta instalação (a pedido, pelo agente): descarregadas do GitHub, com commit ou release e SHA-256 fixos'
EXTRA_HOSTS = ('github.com', 'codeload.github.com')
EXTRA_REQUIRES = {'Core7Zip'}
MAX_EXTRA = 200
MAX_DESCRIPTION = 400
# o que liga uma ferramenta instalada à app (a app só descobre pastas com ferramenta.json); vem com a app, não é descarregado
SUPPORT_FILES = ('ferramenta.json', 'configuracao.json', 'adapter.json', 'LEIA-ME.md')
ACTIONS = ('extract', 'copy', 'source', 'run')
FORMATS = ('zip', 'tar', '7zip', 'zst')
RUN_KINDS = ('sevenzip-setup', 'npm-ci', 'npm-run', 'pip-wheels', 'pip-source', 'msi-extract', 'setup-exe', 'copy-file')
CHUNK = 1024 * 1024
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


class InstallError(Exception):
    """Falha de instalação com mensagem para o utilizador."""


class Cancelled(InstallError):
    pass


def app_dir() -> Path:
    return Path(__file__).resolve().parent


def support_dir(key: str):
    """Pasta, dentro da app, com os ficheiros de apoio de uma ferramenta: ``tool_support`` no pacote, ``Ferramentas`` a correr do código."""
    for base in (app_dir() / 'tool_support' / key, app_dir() / 'Ferramentas' / key):
        if (base / SUPPORT_FILES[0]).is_file():
            return base
    return None


def copy_support(tool: dict, folder: Path) -> list:
    """Põe na pasta da ferramenta os ficheiros de apoio que faltarem. Nunca substitui os que lá estão (o utilizador pode tê-los mudado)."""
    source = support_dir(tool['key'])
    if source is None or tool.get('folder') or source.resolve() == Path(folder).resolve():
        return []
    copied = []
    for name in SUPPORT_FILES:
        if (source / name).is_file() and not (Path(folder) / name).exists():
            Path(folder).mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / name, Path(folder) / name)
            copied.append(name)
    return copied


def load_manifest(path=None) -> dict:
    path = Path(path) if path else app_dir() / MANIFEST_NAME
    manifest = json.loads(path.read_text(encoding='utf-8'))
    validate(manifest)
    return manifest


def _present_paths(tool) -> list:
    """Caminhos (relativos à pasta Ferramentas) cuja existência mostra que a ferramenta está utilizável; basta um."""
    value = tool.get('present') or []
    return [value] if isinstance(value, str) else list(value)


def _safe_relative(value, single=False) -> bool:
    if not isinstance(value, str) or not value:
        return False
    parts = Path(value).parts
    return not (Path(value).is_absolute() or '..' in parts or ':' in value or value.startswith(('/', '\\')) or (single and len(parts) != 1))


def validate(manifest: dict) -> None:
    """Recusa um manifesto com que não seria seguro instalar."""
    if manifest.get('version') != 1 or not isinstance(manifest.get('tools'), list):
        raise InstallError('Manifesto de ferramentas inválido.')
    keys = set()
    for tool in manifest['tools']:
        if not isinstance(tool, dict):
            raise InstallError('Entrada de ferramenta inválida.')
        key = tool.get('key', '')
        if not isinstance(key, str) or not key or not key.isascii() or not key.replace('_', '').isalnum() or key in keys:
            raise InstallError('Chave de ferramenta inválida ou repetida: %r' % (key,))
        keys.add(key)
        if not isinstance(tool.get('name'), str) or not tool['name'].strip() or not isinstance(tool.get('group'), str):
            raise InstallError('Ferramenta sem nome ou sem grupo: ' + key)
        if not isinstance(tool.get('description', ''), str) or len(tool.get('description', '')) > MAX_DESCRIPTION:
            raise InstallError('Descrição inválida ou demasiado longa: ' + key)
        if not isinstance(tool.get('steps', []), list) or not all(isinstance(step, dict) for step in tool.get('steps', [])):
            raise InstallError('Passos inválidos: ' + key)
        if 'folder' in tool and not _safe_relative(tool['folder']):
            raise InstallError('Caminho inválido em "folder": ' + key)
        if not all(_safe_relative(item) for item in _present_paths(tool)):
            raise InstallError('Caminho inválido em "present": ' + key)
        for item in tool.get('cleanup', []):
            if not _safe_relative(item):
                raise InstallError('Caminho inválido em "cleanup": ' + key)
        for step in tool.get('steps', []):
            where = '%s / %s' % (key, step.get('what', '?'))
            action = step.get('action')
            if action not in ACTIONS:
                raise InstallError('Ação desconhecida: ' + where)
            if action == 'run':
                if step.get('kind') not in RUN_KINDS:
                    raise InstallError('Tipo de passo desconhecido: ' + where)
                if not _safe_relative(step.get('check', '')):
                    raise InstallError('Passo de execução sem "check" válido: ' + where)
                if not all(c.isalnum() or c in '.+-' for c in step.get('scm_version', '')):
                    raise InstallError('Versão inválida: ' + where)
                for field in ('dir', 'from', 'to', 'lock_from', 'installer', 'archive', 'path', 'inner'):
                    if field in step and not _safe_relative(step[field]):
                        raise InstallError('Caminho inválido em "%s": %s' % (field, where))
                continue
            if urlsplit(step.get('url', '')).scheme != 'https':
                raise InstallError('Endereço sem HTTPS: ' + where)
            digest = step.get('sha256', '')
            if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
                raise InstallError('SHA-256 em falta ou inválido: ' + where)
            if action == 'extract' and step.get('format', 'zip') not in FORMATS:
                raise InstallError('Formato desconhecido: ' + where)
            if not _safe_relative(step.get('file', ''), single=True) or not _safe_relative(step.get('to', '')):
                raise InstallError('Caminho inválido em "file" ou "to": ' + where)
            if 'check' in step and not _safe_relative(step['check']):
                raise InstallError('Caminho inválido em "check": ' + where)
    for tool in manifest['tools']:
        for needed in tool.get('requires', []):
            if needed not in keys:
                raise InstallError('%s depende de uma ferramenta que não existe: %s' % (tool['key'], needed))


# ---------------------------------------------------------------------- lista extra (acrescentada pelo utilizador)
def extra_path(root) -> Path:
    return Path(root) / EXTRA_NAME


def validate_extra(tool: dict, base_keys) -> None:
    """Uma entrada da lista extra pode muito menos do que uma do manifesto da app.

    Só descarrega do GitHub e extrai ou copia para a sua própria pasta: nunca executa programas,
    nunca escreve no núcleo e nunca substitui uma entrada que venha com a app.
    """
    validate(dict(version=1, tools=[dict(tool, requires=[])]))
    key = tool['key']
    if key in base_keys:
        raise InstallError('A lista extra não pode substituir uma ferramenta da app: ' + key)
    if tool.get('group') != EXTRA_GROUP or 'folder' in tool or tool.get('cleanup') or not tool.get('automatic'):
        raise InstallError('Entrada extra com campos não permitidos: ' + key)
    if not 10 <= len(tool.get('description', '').strip()):
        raise InstallError('Entrada extra sem descrição: ' + key)
    if not set(tool.get('requires', [])) <= EXTRA_REQUIRES:
        raise InstallError('Entrada extra com dependências não permitidas: ' + key)
    if not tool.get('steps') or any(step.get('action') not in ('source', 'extract', 'copy') for step in tool['steps']):
        raise InstallError('Uma entrada extra só pode descarregar e extrair ficheiros: ' + key)
    if any(urlsplit(step['url']).netloc.lower() not in EXTRA_HOSTS for step in tool['steps']):
        raise InstallError('Uma entrada extra só pode descarregar do GitHub: ' + key)
    if not _present_paths(tool) or any(Path(item).parts[0] != key for item in _present_paths(tool)):
        raise InstallError('Entrada extra com sinal de presença fora da sua pasta: ' + key)


def load_extra(root, base_keys) -> tuple:
    """(entradas válidas da lista extra, mensagens sobre as que foram ignoradas). Um ficheiro estragado não parte a lista da app."""
    path = extra_path(root)
    if not path.is_file():
        return [], []
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        rows = data['tools'] if isinstance(data, dict) and data.get('version') == 1 and isinstance(data.get('tools'), list) else None
    except (OSError, ValueError):
        rows = None
    if rows is None:
        return [], ['A lista extra (%s) não se consegue ler; foi ignorada.' % EXTRA_NAME]
    tools, errors, taken = [], [], set(base_keys)
    for tool in rows[:MAX_EXTRA]:
        try:
            validate_extra(tool, taken)
        except (InstallError, TypeError, ValueError, KeyError, AttributeError) as exc:
            errors.append('Entrada extra ignorada: %s' % exc)
            continue
        taken.add(tool['key'])
        tools.append(tool)
    return tools, errors


def with_extra(base: dict, root) -> dict:
    """O manifesto da app mais as entradas válidas da lista extra de ``root`` (num grupo à parte)."""
    extras, errors = load_extra(root, {tool['key'] for tool in base['tools']})
    manifest = dict(base, tools=list(base['tools']) + extras, extra_errors=errors)
    if extras:
        manifest['groups'] = {**base.get('groups', {}), EXTRA_GROUP: EXTRA_TITLE}
    return manifest


def save_extra_tool(root, tool: dict, base: dict) -> None:
    """Acrescenta (ou substitui pela mesma chave) uma entrada na lista extra de ``root``."""
    base_keys = {item['key'] for item in base['tools']}
    validate_extra(tool, base_keys)
    current, _errors = load_extra(root, base_keys)
    rows = [item for item in current if item['key'] != tool['key']] + [tool]
    if len(rows) > MAX_EXTRA:
        raise InstallError('A lista extra já tem %d ferramentas; remove alguma do ficheiro %s.' % (MAX_EXTRA, EXTRA_NAME))
    path = extra_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(dict(version=1, tools=rows), ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    _replace(temporary, path)


def _open_url(url, timeout=(30, 60)):
    """Abre o endereço em modo de leitura por blocos. Substituído nos testes."""
    import requests
    response = requests.get(url, stream=True, timeout=timeout, headers={'User-Agent': 'MeisterCode-tool-installer'})
    response.raise_for_status()
    if urlsplit(response.url).scheme != 'https':
        response.close()
        raise InstallError('O servidor redirecionou para um endereço sem HTTPS.')
    return response


# ---------------------------------------------------------------------- estado
def tool_folder(root: Path, tool: dict) -> Path:
    return Path(root) / tool.get('folder', tool['key'])


def step_id(tool: dict, index: int) -> str:
    step = tool['steps'][index]
    return step['sha256'] if step['action'] != 'run' else 'run:%d:%s' % (index, step['kind'])


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def _collect_hashes(value, found):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in ('sha256', 'node_sha256') and isinstance(item, str):
                found.add(item)
            else:
                _collect_hashes(item, found)
    elif isinstance(value, list):
        for item in value:
            _collect_hashes(item, found)


def recorded(folder: Path) -> tuple:
    """(passos registados por este instalador, hashes registados por instaladores anteriores)."""
    record = _read_json(folder / RECORD_NAME) or {}
    legacy = set()
    for name in ('instalacao.json', 'fonte.json', 'provenance.json', 'dependencies.json'):
        _collect_hashes(_read_json(folder / name), legacy)
    return set(record.get('steps', [])), legacy


def _exists(path: Path) -> bool:
    try:
        return path.is_file() or (path.is_dir() and any(path.iterdir()))
    except OSError:
        return False


def step_done(folder: Path, tool: dict, index: int, done_ids=None, legacy=None) -> bool:
    if done_ids is None:
        done_ids, legacy = recorded(folder)
    step = tool['steps'][index]
    identity = step_id(tool, index)
    if step.get('transient'):
        return identity in done_ids  # o ficheiro é consumido por um passo seguinte e apagado
    if not _exists(folder / (step.get('check') or step['to'])):
        return False
    return identity in done_ids or (step['action'] != 'run' and identity in legacy)


def tool_status(root: Path, tool: dict) -> str:
    folder = tool_folder(root, tool)
    steps = tool.get('steps', [])
    done_ids, legacy = recorded(folder)
    done = [step_done(folder, tool, index, done_ids, legacy) for index in range(len(steps))]
    if steps and all(done):
        return 'installed'
    # instalada por uma via anterior a este instalador (sem registo dele): basta o sinal de presença
    if not done_ids and any(_exists(Path(root) / item) for item in _present_paths(tool)):
        return 'installed'
    if tool.get('automatic'):
        return 'partial' if any(done) else 'missing'
    return 'pending'


def state(root, manifest) -> list:
    """O que está instalado em ``root``, ferramenta a ferramenta."""
    root = Path(root)
    rows = []
    for tool in manifest['tools']:
        steps = tool.get('steps', [])
        rows.append(dict(key=tool['key'], name=tool['name'], description=tool.get('description', ''), extra=tool['group'] == EXTRA_GROUP,
                         folder=tool.get('folder', tool['key']), group=tool['group'], version=tool.get('version', ''), repo=tool.get('repo', ''),
                         automatic=bool(tool.get('automatic')), pending=tool.get('pending', ''), status=tool_status(root, tool), integrated=tool.get('integrated', True),
                         license=tool.get('license', ''), requires=tool.get('requires', []), runs=sorted({step['kind'] for step in steps if step['action'] == 'run'}),
                         download_bytes=sum(step.get('bytes', 0) for step in steps), installed_mb=tool.get('installed_mb', 0), note=tool.get('note', '')))
    return rows


def expand(manifest: dict, keys) -> list:
    """As ferramentas pedidas e, antes delas, tudo de que dependem."""
    tools = {tool['key']: tool for tool in manifest['tools']}
    ordered = []

    def visit(key, trail=()):
        if key in trail:
            raise InstallError('Dependência circular no manifesto: ' + ' → '.join(trail + (key,)))
        if key not in tools:
            raise InstallError('Ferramenta desconhecida: ' + key)
        for needed in tools[key].get('requires', []):
            visit(needed, trail + (key,))
        if key not in ordered:
            ordered.append(key)

    for key in keys:
        visit(key)
    return ordered


# ---------------------------------------------------------------------- ficheiros
def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)
    else:
        try:
            path.unlink()
        except OSError:
            pass


def _replace(source: Path, target: Path, attempts: int = 12) -> None:
    """Troca ``target`` por ``source``. No Windows, um antivírus ou o indexador podem ter o ficheiro aberto por instantes
    logo depois de ele ser escrito, e a troca falha com «Acesso negado»: tenta-se outra vez durante uns segundos."""
    for attempt in range(attempts):
        try:
            source.replace(target)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.25)


def _inside(base: Path, name: str) -> Path:
    if name.startswith(('/', '\\')) or ':' in name.split('/')[0]:
        raise InstallError('O arquivo tem um caminho absoluto: ' + name[:120])
    destination = (base / name).resolve()
    if destination != base and base not in destination.parents:
        raise InstallError('O arquivo tenta escrever fora da pasta de destino: ' + name[:120])
    return destination


def _stripped(name: str, strip: int):
    parts = name.replace('\\', '/').split('/')
    return '/'.join(parts[strip:]) if len(parts) > strip else ''


def _move_into(source: Path, target: Path) -> None:
    """Junta o conteúdo de ``source`` a ``target`` (substitui ficheiros com o mesmo nome)."""
    target.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        destination = target / item.name
        if item.is_dir():
            _move_into(item, destination)
        else:
            if destination.exists():
                _remove(destination)
            _replace(item, destination)


class Installer:
    """Instala ferramentas em ``root`` (a pasta ``Ferramentas``), uma de cada vez, numa thread."""

    def __init__(self, root, manifest=None, keep_downloads=False):
        self.root = Path(root)
        self.base = manifest or load_manifest()
        self.keep_downloads = keep_downloads
        self.lock = threading.RLock()
        self.job = dict(state='idle')
        self.reload()
        self.stop = threading.Event()
        self.thread = None
        self.process = None
        self.job = dict(state='idle', current='', message='', done_bytes=0, total_bytes=0, results=[])

    def reload(self) -> None:
        """Volta a ler a lista extra de ``root`` (o agente pode ter acrescentado uma ferramenta). Nunca a meio de uma instalação."""
        with self.lock:
            if self.job.get('state') == 'running':
                return
            self.manifest = with_extra(self.base, self.root)
            self.tools = {tool['key']: tool for tool in self.manifest['tools']}

    # ------------------------------------------------------------------ estado
    def status(self) -> dict:
        with self.lock:
            return json.loads(json.dumps(self.job))

    def _update(self, **changes):
        with self.lock:
            self.job.update(changes)

    def cancel(self):
        self.stop.set()
        self._update(message='A cancelar…')
        self._kill()
        return self.status()

    def close(self):
        self.stop.set()
        self._kill()
        thread = self.thread
        if thread and thread.is_alive():
            thread.join(timeout=10)

    def _kill(self):
        with self.lock:
            process = self.process
        if process and process.poll() is None:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True, creationflags=NO_WINDOW, timeout=15)
            else:
                process.terminate()

    # ------------------------------------------------------------------ arranque
    def plan(self, keys) -> list:
        return expand(self.manifest, list(dict.fromkeys(keys)))

    def start(self, keys) -> dict:
        order = self.plan(keys)
        with self.lock:
            if self.job['state'] == 'running':
                raise InstallError('Já há uma instalação em curso.')
            self.stop.clear()
            total = sum(step.get('bytes', 0) for key in order if tool_status(self.root, self.tools[key]) != 'installed' for step in self.tools[key].get('steps', []))
            self.job = dict(state='running', current='', message='A preparar…', done_bytes=0, total_bytes=total, results=[])
            self.thread = threading.Thread(target=self._run, args=(order, set(keys)), daemon=True)
            self.thread.start()
        return self.status()

    def run(self, keys) -> dict:
        """Instala e espera pelo fim (linha de comandos e testes)."""
        self.start(keys)
        self.thread.join()
        return self.status()

    def _run(self, order, asked):
        results = []
        broken = set()
        try:
            for key in order:
                tool = self.tools[key]
                if self.stop.is_set():
                    results.append(dict(key=key, status='cancelled', message='Cancelado antes de começar.'))
                    continue
                blocked = [needed for needed in tool.get('requires', []) if needed in broken]
                if blocked:
                    broken.add(key)
                    results.append(dict(key=key, status='failed', message='Não instalada: depende de %s, que não ficou instalada.' % ', '.join(blocked)))
                    self._update(results=list(results))
                    continue
                self._update(current=key, message='A instalar ' + tool['name'] + '…')
                try:
                    row = self._install(tool)
                except Cancelled:
                    row = dict(key=key, status='cancelled', message='Cancelado; o que estava instalado antes ficou como estava.')
                except InstallError as exc:
                    row = dict(key=key, status='failed', message=str(exc))
                except Exception as exc:  # noqa: BLE001  (uma falha inesperada não trava as seguintes)
                    row = dict(key=key, status='failed', message='%s: %s' % (type(exc).__name__, exc))
                if row['status'] not in ('installed', 'already'):
                    broken.add(key)
                if key not in asked:
                    row['dependency'] = True
                results.append(row)
                self._update(results=list(results))
        finally:
            failed = sum(row['status'] == 'failed' for row in results)
            cancelled = self.stop.is_set()
            self._update(state='cancelled' if cancelled else 'failed' if failed and failed == len(results) else 'done', current='', results=results,
                         message='Cancelado.' if cancelled else '%d instalada(s), %d já estava(m), %d por fazer à mão, %d com erro.' % (
                             sum(r['status'] == 'installed' for r in results), sum(r['status'] == 'already' for r in results),
                             sum(r['status'] == 'pending' for r in results), failed))

    # ------------------------------------------------------------------ uma ferramenta
    def _install(self, tool) -> dict:
        key = tool['key']
        if tool_status(self.root, tool) == 'installed':
            copy_support(tool, tool_folder(self.root, tool))  # instalada por um pacote que ainda não os trazia
            return dict(key=key, status='already', message='Já instalada%s.' % (' (versão %s)' % tool['version'] if tool.get('version') else ''))
        if not tool.get('automatic'):
            return dict(key=key, status='pending', message='Não se instala sozinha: ' + (tool.get('pending') or 'método por implementar') + '.')
        folder = tool_folder(self.root, tool)
        steps = tool['steps']
        needed_bytes = sum(step.get('bytes', 0) for step in steps)
        self.root.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(self.root).free
        if needed_bytes and free < needed_bytes * 4:
            raise InstallError('Espaço insuficiente no disco: livres %d MB, precisos cerca de %d MB.' % (free // 1048576, needed_bytes * 4 // 1048576))
        folder.mkdir(parents=True, exist_ok=True)
        # restos de uma instalação interrompida (por exemplo, a app fechada a meio)
        for pattern in ('.instalar-*', '.pip-*', '.msi-*', '*.anterior-*', 'downloads/*.parte-*'):
            for stale in folder.glob(pattern):
                _remove(stale)
        done_ids, legacy = recorded(folder)
        try:
            for index, step in enumerate(steps):
                if self.stop.is_set():
                    raise Cancelled()
                if step_done(folder, tool, index, done_ids, legacy):
                    continue
                if step['action'] == 'run':
                    self._update(message='%s: %s…' % (tool['name'], step.get('what', step['kind'])))
                    self._run_step(tool, folder, step)
                    if not _exists(folder / step['check']):
                        raise InstallError('O passo «%s» terminou sem produzir %s.' % (step.get('what', step['kind']), step['check']))
                else:
                    self._file_step(tool, folder, step)
                done_ids.add(step_id(tool, index))
                self._write_record(tool, folder, done_ids)
        finally:
            if not self.keep_downloads:
                _remove(folder / 'downloads')
        for item in tool.get('cleanup', []):
            _remove(folder / item)
        expected = _present_paths(tool)
        if expected and not any(_exists(self.root / item) for item in expected):
            raise InstallError('Os passos terminaram mas falta %s: a ferramenta não ficou utilizável.' % expected[0])
        self._write_legacy_records(tool, folder)
        copy_support(tool, folder)
        return dict(key=key, status='installed', message='Instalada%s.' % (' (versão %s)' % tool['version'] if tool.get('version') else ''))

    def _write_record(self, tool, folder: Path, done_ids):
        data = dict(installer=1, key=tool['key'], version=tool.get('version', ''), steps=sorted(done_ids), updated_at=time.strftime('%Y-%m-%dT%H:%M:%S'))
        temporary = folder / (RECORD_NAME + '.tmp')
        temporary.write_text(json.dumps(data, indent=2), encoding='utf-8')
        _replace(temporary, folder / RECORD_NAME)

    def _write_legacy_records(self, tool, folder: Path):
        """Os registos que o resto da app já lê (``bench_catalog`` tira a versão de ``instalacao.json``)."""
        files = [step for step in tool['steps'] if step['action'] in ('extract', 'copy')]
        sources = [step for step in tool['steps'] if step['action'] == 'source']
        if tool.get('folder', '').startswith('_Runtime'):
            return
        if files:
            first = files[0]
            record = dict(version=tool.get('version', ''), url=first['url'], sha256=first['sha256'], verified_publisher_digest=bool(first.get('publisher_digest')))
            if len(files) > 1:
                record['packages'] = [dict(package=step.get('what', ''), url=step['url'], sha256=step['sha256']) for step in files]
            (folder / 'instalacao.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
        if sources:
            first = sources[0]
            (folder / 'fonte.json').write_text(json.dumps(dict(repository=first.get('repository', ''), commit=first.get('commit', ''), sha256=first['sha256']), indent=2), encoding='utf-8')

    # ------------------------------------------------------------------ passos com ficheiro
    def _file_step(self, tool, folder: Path, step: dict):
        archive = self._download(tool, folder, step)
        target = folder / step['to']
        staging = folder / ('.instalar-%d' % os.getpid())
        _remove(staging)
        try:
            self._update(message='%s: a extrair %s…' % (tool['name'], step.get('what', step['file'])))
            if step['action'] == 'copy':
                staging.mkdir(parents=True)
                shutil.copy2(archive, staging / target.name)
                new = staging / target.name
            else:
                new = staging / 'conteudo'
                new.mkdir(parents=True)
                self._extract(archive, new, step, staging)
                keep = step.get('only_top')
                if keep:
                    for item in list(new.iterdir()):
                        if item.name not in keep:
                            _remove(item)
                if not any(new.iterdir()):
                    raise InstallError('O arquivo ficou vazio depois de extraído: ' + step['file'])
            if step.get('merge') and new.is_dir():
                _move_into(new, target)
            else:
                # troca: a instalação anterior só desaparece depois de a nova estar completa
                previous = target.with_name(target.name + '.anterior-%d' % os.getpid())
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    _replace(target, previous)
                try:
                    _replace(new, target)
                except OSError:
                    if previous.exists():
                        _replace(previous, target)
                    raise
                _remove(previous)
        except zipfile.BadZipFile:
            raise InstallError('O ficheiro descarregado não é um zip válido: ' + step['file']) from None
        except tarfile.TarError as exc:
            raise InstallError('O ficheiro descarregado não é um arquivo tar válido: %s (%s)' % (step['file'], exc)) from None
        finally:
            _remove(staging)
            if not self.keep_downloads:
                _remove(archive)

    def _extract(self, archive: Path, new: Path, step: dict, staging: Path):
        kind = step.get('format', 'zip') if step['action'] == 'extract' else 'zip'
        strip = int(step.get('strip', 0))
        base = new.resolve()
        if kind == 'zip':
            with zipfile.ZipFile(archive) as bundle:
                for info in bundle.infolist():
                    if self.stop.is_set():
                        raise Cancelled()
                    _inside(base, info.filename)
                    if (info.external_attr >> 16) & 0o170000 == 0o120000:
                        continue  # ligação simbólica: não se cria (podia apontar para fora da pasta)
                    name = _stripped(info.filename, strip)
                    if not name or name.endswith('/'):
                        if name:
                            _inside(base, name).mkdir(parents=True, exist_ok=True)
                        continue
                    destination = _inside(base, name)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with bundle.open(info) as source, destination.open('wb') as handle:
                        shutil.copyfileobj(source, handle, CHUNK)
            return
        if kind == 'tar':
            self._untar(archive, base, strip)
            return
        seven = self.root / '_Runtime' / '7zip' / 'full' / '7z.exe'
        if not seven.is_file():
            raise InstallError('Falta o 7-Zip do núcleo para extrair ' + step['file'] + '.')
        if kind == 'zst':
            unpacked = staging / 'tar'
            self._command([str(seven), 'x', str(archive), '-o' + str(unpacked), '-y', '-bso0', '-bsp0'], staging, 600, 'O 7-Zip não conseguiu descomprimir ' + step['file'])
            inner = next(unpacked.glob('*.tar'), None)
            if inner is None:
                raise InstallError('O arquivo .zst não contém um tar: ' + step['file'])
            self._untar(inner, base, strip)
            return
        self._command([str(seven), 'x', str(archive), '-o' + str(base), '-y', '-bso0', '-bsp0'], staging, 1800, 'O 7-Zip não conseguiu extrair ' + step['file'])
        for item in base.rglob('*'):
            if item.is_symlink() or base not in item.resolve().parents:
                raise InstallError('O arquivo tenta escrever fora da pasta de destino: ' + item.name[:120])
        for _ in range(strip):
            entries = list(base.iterdir())
            if len(entries) != 1 or not entries[0].is_dir():
                raise InstallError('O arquivo não tem uma única pasta de topo: ' + step['file'])
            holder = base.with_name(base.name + '-interior')
            _replace(entries[0], holder)
            base.rmdir()
            _replace(holder, base)

    def _untar(self, archive: Path, base: Path, strip: int):
        with tarfile.open(archive) as bundle:
            for member in bundle:
                if self.stop.is_set():
                    raise Cancelled()
                name = _stripped(member.name, strip)
                if not name:
                    continue
                _inside(base, name)
                if not (member.isfile() or member.isdir()):
                    continue  # ligações e dispositivos não são criados
                member.name = name
                bundle.extract(member, base, filter='data')

    def _download(self, tool, folder: Path, step: dict) -> Path:
        destination = folder / 'downloads' / step['file']
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_file():
            with destination.open('rb') as handle:
                if hashlib.file_digest(handle, 'sha256').hexdigest() == step['sha256']:
                    return destination  # cópia já conferida (por exemplo, guardada de uma instalação anterior)
        partial = destination.with_name(destination.name + '.parte-%d' % os.getpid())
        limit = max(step.get('bytes', 0) * 2, 64 * 1024 * 1024)
        digest = hashlib.sha256()
        received = 0
        base = self.status()['done_bytes']
        try:
            response = _open_url(step['url'])
            try:
                with partial.open('wb') as handle:
                    for chunk in response.iter_content(CHUNK):
                        if self.stop.is_set():
                            raise Cancelled()
                        received += len(chunk)
                        if received > limit:
                            raise InstallError('O ficheiro é muito maior do que o esperado; descarga interrompida: ' + step['file'])
                        digest.update(chunk)
                        handle.write(chunk)
                        self._update(done_bytes=base + received, message='%s: a descarregar %s (%d MB)…' % (tool['name'], step.get('what', step['file']), received // 1048576))
            finally:
                response.close()
            if digest.hexdigest() != step['sha256']:
                raise InstallError('SHA-256 diferente do registado para %s: o ficheiro foi rejeitado e nada foi alterado. (recebido %s…)' % (step['file'], digest.hexdigest()[:16]))
            _replace(partial, destination)
            return destination
        except InstallError:
            raise
        except Exception as exc:  # noqa: BLE001  (rede, disco)
            raise InstallError('Falha ao descarregar %s: %s' % (step['file'], str(exc)[:300])) from None
        finally:
            _remove(partial)
            if not destination.exists():
                try:
                    destination.parent.rmdir()  # não deixar uma pasta downloads/ vazia
                except OSError:
                    pass

    # ------------------------------------------------------------------ passos que executam programas
    def _command(self, command, cwd: Path, timeout: int, failure: str, env=None):
        """Corre um programa do núcleo sem janela, com limite de tempo e possibilidade de cancelar."""
        environment = {key: value for key, value in os.environ.items() if key.upper() in _ENVIRONMENT}
        environment.update(env or {})
        log = Path(cwd) / ('.saida-%d.txt' % os.getpid())
        with log.open('wb') as output:
            process = subprocess.Popen(command, cwd=str(cwd), env=environment, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
            with self.lock:
                self.process = process
            deadline = time.monotonic() + timeout
            try:
                while process.poll() is None:
                    if self.stop.is_set():
                        self._kill()
                        raise Cancelled()
                    if time.monotonic() > deadline:
                        self._kill()
                        raise InstallError(failure + ': excedeu %d minutos.' % (timeout // 60))
                    time.sleep(0.2)
            finally:
                with self.lock:
                    self.process = None
        tail = log.read_bytes()[-1500:].decode('utf-8', errors='replace').strip()
        _remove(log)
        if process.returncode:
            raise InstallError('%s (código %s). %s' % (failure, process.returncode, tail[-700:]))
        return tail

    def _node(self) -> Path:
        for base in (self.root / '_Runtime' / 'node', self.root / 'REA' / 'runtime'):
            found = sorted(base.glob('*/node.exe')) if base.is_dir() else []
            if found:
                return found[0]
        raise InstallError('Falta o Node do núcleo.')

    def _python(self) -> Path:
        base = self.root / '_Runtime' / 'python'
        found = sorted(base.glob('*/python.exe')) if base.is_dir() else []
        if not found:
            raise InstallError('Falta o Python do núcleo.')
        return found[0]

    def _npm(self, arguments, cwd: Path, timeout: int, failure: str):
        node = self._node()
        cli = node.parent / 'node_modules' / 'npm' / 'bin' / 'npm-cli.js'
        if not cli.is_file():
            raise InstallError('O Node instalado não traz o npm.')
        cache = self.root / '_Runtime' / 'npm-cache'
        return self._command([str(node), str(cli), *arguments, '--no-audit', '--no-fund', '--cache', str(cache)], cwd, timeout, failure,
                             env={'PATH': str(node.parent) + os.pathsep + os.environ.get('PATH', '')})

    def _pip(self, arguments, folder: Path, timeout: int, failure: str, env=None):
        """pip para uma pasta temporária, depois junta: «pip --target» por cima do que já existe substituía pastas inteiras (por exemplo ``bin``)."""
        staging = folder / ('.pip-%d' % os.getpid())
        _remove(staging)
        try:
            self._command([str(self._python()), '-m', 'pip', 'install', '--no-deps', '--disable-pip-version-check', '--no-warn-script-location',
                           '--target', str(staging), *arguments], folder, timeout, failure, env=env)
            _move_into(staging, self.root / '_Runtime' / 'site-packages')
        finally:
            _remove(staging)

    def _run_step(self, tool, folder: Path, step: dict):
        kind = step['kind']
        if kind == 'sevenzip-setup':
            # o instalador do 7-Zip é um arquivo: extrai-se com o 7zr.exe, não se executa
            target = folder / step['to']
            _remove(target)
            self._command([str(folder / '7zr.exe'), 'x', str(folder / step['archive']), '-o' + str(target), '-y', '-bso0', '-bsp0'], folder, 120, 'Não foi possível extrair o 7-Zip')
        elif kind == 'npm-ci':
            where = folder / step.get('dir', '.')
            where.mkdir(parents=True, exist_ok=True)
            if step.get('lock_from'):
                # o bloqueio vem sempre da app; o package.json só se o projeto descarregado não trouxer o seu
                for name in ('package-lock.json', 'package.json'):
                    source = app_dir() / step['lock_from'] / name
                    if name == 'package.json' and (where / name).is_file() and not source.is_file():
                        continue
                    if not source.is_file():
                        raise InstallError('Falta %s na app (%s).' % (name, step['lock_from']))
                    shutil.copy2(source, where / name)
            arguments = ['ci'] + ([] if step.get('scripts') else ['--ignore-scripts']) + (['--omit=optional'] if step.get('omit_optional') else [])
            self._npm(arguments, where, 1200, 'A instalação npm falhou')
        elif kind == 'npm-run':
            self._npm(['run', step['script']], folder / step.get('dir', '.'), 900, 'O passo npm «%s» falhou' % step['script'])
        elif kind == 'pip-wheels':
            wheels = sorted((folder / step['from']).glob('*.whl'))
            if not wheels:
                raise InstallError('Não há pacotes Python descarregados para instalar.')
            listing = folder / 'pacotes.txt'
            listing.write_text('\n'.join(str(path) for path in wheels) + '\n', encoding='utf-8')
            self._pip(['--no-index', '-r', str(listing)], folder, 1800, 'A instalação dos pacotes Python falhou')
            _remove(listing)
            names = [dict(name=item['name'], version=item['version']) for item in step.get('packages', [])]
            if names:
                (self.root / '_Runtime' / 'installed-packages.json').write_text(json.dumps(names, indent=1), encoding='utf-8')
            (folder / step['check']).write_text(json.dumps(dict(installed=len(wheels)), indent=1), encoding='utf-8')
        elif kind == 'pip-source':
            source = next(iter(sorted(folder.glob(step['path']))), None)
            if source is None:
                raise InstallError('Falta o código-fonte para instalar: ' + step['path'])
            self._pip([str(source)], folder, 1200, 'A instalação a partir do código-fonte falhou',
                      env={'PDM_BUILD_SCM_VERSION': step['scm_version']} if step.get('scm_version') else None)
        elif kind == 'msi-extract':
            # «instalação administrativa»: só desempacota o MSI para a pasta, sem registar nada no sistema
            target = folder / step['to']
            unpacked = folder / ('.msi-%d' % os.getpid())
            _remove(unpacked)
            unpacked.mkdir(parents=True)
            try:
                # linha de comando escrita à mão: o msiexec só aceita TARGETDIR="pasta com espaços" (as aspas depois do «=»);
                # passada como lista, o Python punha as aspas à volta do argumento inteiro e o msiexec recusava (código 1639)
                self._command('msiexec.exe /a "%s" /qn /norestart TARGETDIR="%s"' % (folder / step['archive'], unpacked.resolve()), folder, 900, 'Não foi possível desempacotar o MSI')
                inner = unpacked / step['inner'] if step.get('inner') else unpacked
                if not inner.is_dir():
                    raise InstallError('O MSI não tem a pasta esperada: ' + step.get('inner', ''))
                _remove(target)
                _move_into(inner, target)
            finally:
                _remove(unpacked)
        elif kind == 'setup-exe':
            # único caso em que se executa o instalador de terceiros (já conferido pelo SHA-256), em modo silencioso e por utilizador
            target = folder / step['to']
            self._command([str(folder / step['installer']), '/CURRENTUSER', '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/DIR=' + str(target.resolve())], folder, 1800,
                          'O instalador não terminou bem', env={'__COMPAT_LAYER': 'RunAsInvoker'})
        elif kind == 'copy-file':
            matches = sorted(folder.glob(step['from']))
            if not matches:
                raise InstallError('Não encontrei %s para copiar.' % step['from'])
            destination = folder / step['to']
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(matches[0], destination)


_ENVIRONMENT = {'PATH', 'PATHEXT', 'SYSTEMROOT', 'SYSTEMDRIVE', 'WINDIR', 'COMSPEC', 'TEMP', 'TMP', 'APPDATA', 'LOCALAPPDATA', 'USERPROFILE', 'HOMEDRIVE', 'HOMEPATH',
                'PROGRAMFILES', 'PROGRAMFILES(X86)', 'PROGRAMDATA', 'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE', 'HTTP_PROXY', 'HTTPS_PROXY', 'NO_PROXY'}


# ---------------------------------------------------------------------- Sources_ferramentas.md
def sources_markdown(manifest: dict) -> str:
    """O documento para pessoas, gerado do manifesto (para os dois nunca divergirem)."""
    def mb(value):
        return '%d MB' % round(value / 1048576) if value >= 1048576 else '< 1 MB' if value else '—'

    tools = manifest['tools']
    automatic = sum(bool(t.get('automatic')) for t in tools)
    lines = ['# Fontes das ferramentas do MeisterCode', '',
             '**Ficheiro gerado** a partir de `tools_manifest.json` (`python tool_installer.py fontes`). Não editar à mão: corrige-se o manifesto e gera-se de novo.', '',
             'O pacote de distribuição não leva as ferramentas; a app instala-as a partir destas origens, com versões e SHA-256 fixos. Manifesto revisto a %s.' % manifest.get('reviewed', '?'), '',
             '## Resumo', '',
             '- %d entradas (núcleo incluído), cerca de %d MB depois de instaladas e %d MB de downloads.' % (len(tools), sum(t.get('installed_mb', 0) for t in tools), sum(s.get('bytes', 0) for t in tools for s in t.get('steps', [])) // 1048576),
             '- **%d instalam-se sozinhas** pelo instalador da app; %d têm o motivo indicado («Por fazer»).' % (automatic, len(tools) - automatic),
             '- Todas têm o repositório ou a origem indicados. Nem todos os downloads vêm do GitHub: cada endereço está escrito por extenso.', '',
             '| Grupo | O que é | Entradas | Instaladas ocupam |', '|---|---|---|---|']
    for letter, title in manifest.get('groups', {}).items():
        rows = [t for t in tools if t['group'] == letter]
        lines.append('| %s | %s | %d | %d MB |' % (letter, title, len(rows), sum(t.get('installed_mb', 0) for t in rows)))
    lines.append('')
    for letter, title in manifest.get('groups', {}).items():
        lines += ['## Grupo %s — %s' % (letter, title), '']
        for tool in (t for t in tools if t['group'] == letter):
            lines += ['### ' + tool['name'], '']
            if tool.get('description'):
                lines += [tool['description'], '']
            lines += ['- Pasta: `Ferramentas/%s` · instalada ocupa: %d MB%s' % (tool.get('folder', tool['key']), tool.get('installed_mb', 0), ' · versão: ' + tool['version'] if tool.get('version') else ''),
                      '- Origem: <%s>' % tool['repo'],
                      '- Instalação pela app: ' + ('**automática**' if tool.get('automatic') else '**por fazer** — ' + tool.get('pending', ''))]
            if tool.get('license'):
                lines.append('- Licença: ' + tool['license'])
            if tool.get('integrated') is False:
                lines.append('- Integração na app: **nenhuma ainda** — o instalador só descarrega e confere; o agente ainda não a usa.')
            if tool.get('requires'):
                lines.append('- Depende de: ' + ', '.join(tool['requires']))
            packages = [step for step in tool.get('steps', []) if step.get('transient') and step['action'] != 'run']
            for step in tool.get('steps', []):
                if step['action'] == 'run':
                    lines.append('- Passo local — %s (`%s`)' % (step.get('what', ''), step['kind']))
                elif step not in packages:
                    lines += ['- Download — %s (%s): <%s>  ' % (step['what'], mb(step.get('bytes', 0)), step['url']),
                              '  SHA-256 `%s`%s' % (step['sha256'], ' (confirmado pelo editor)' if step.get('publisher_digest') else ' (do ficheiro descarregado; sem confirmação do editor)')]
            if len(packages) > 3:
                lines += ['- Downloads — %d ficheiros (%s no total), cada um com SHA-256 no manifesto:' % (len(packages), mb(sum(s.get('bytes', 0) for s in packages))), '',
                          '  ' + ', '.join('`%s`' % step['file'] for step in packages), '']
            else:
                for step in packages:
                    lines += ['- Download — %s (%s): <%s>  ' % (step['what'], mb(step.get('bytes', 0)), step['url']), '  SHA-256 `%s`' % step['sha256']]
            if tool.get('note'):
                lines.append('- Nota: ' + tool['note'])
            lines.append('')
    lines += ['## O que nenhum instalador faz sozinho', '',
              '- Drivers USB que pedem permissões de administrador: USBPcap, WinUSB, CH341A, com0com, Cynthion, Glasgow, SDR.',
              '- O driver de kernel do Lemon (assinatura de teste).',
              '- Os pesos dos modelos de IA (Wonder3D, Hunyuan3D): vários GB, fora desta lista.', '']
    return '\n'.join(lines)


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description='Instalador das ferramentas do MeisterCode.')
    parser.add_argument('--root', help='pasta Ferramentas de destino (obrigatória para listar/instalar)')
    parser.add_argument('--manifest', help='manifesto alternativo')
    parser.add_argument('--keep-downloads', action='store_true', help='guardar os ficheiros descarregados')
    parser.add_argument('--tudo', action='store_true', help='instalar tudo o que é automático')
    parser.add_argument('command', choices=('listar', 'instalar', 'fontes'))
    parser.add_argument('keys', nargs='*')
    args = parser.parse_args(argv)
    manifest = load_manifest(args.manifest)
    if args.command == 'fontes':
        target = app_dir() / 'Sources_ferramentas.md'
        target.write_text(sources_markdown(manifest), encoding='utf-8', newline='\r\n')
        print('escrito', target)
        return 0
    if not args.root:
        parser.error('--root é obrigatório para ' + args.command)
    if args.command == 'listar':
        for row in state(args.root, manifest):
            print('%-26s %-10s %6s MB  %s' % (row['key'], row['status'], row['download_bytes'] // 1048576, row['pending']))
        return 0
    installer = Installer(args.root, manifest, keep_downloads=args.keep_downloads)
    keys = [tool['key'] for tool in manifest['tools'] if tool.get('automatic')] if args.tudo else args.keys
    installer.start(keys)
    last = ''
    while installer.thread.is_alive():
        message = installer.status()['message']
        if message.split(' (')[0] != last:
            print(message, flush=True)
            last = message.split(' (')[0]
        time.sleep(0.5)
    final = installer.status()
    for row in final['results']:
        print('%-26s %-10s %s' % (row['key'], row['status'], row['message']))
    print(final['message'])
    return 0 if final['state'] == 'done' and not any(row['status'] == 'failed' for row in final['results']) else 1


if __name__ == '__main__':
    sys.exit(main())
