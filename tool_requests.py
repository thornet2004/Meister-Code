"""De um endereço do GitHub a uma entrada da lista extra de ferramentas.

Usado pela ferramenta do agente ``ferramenta_instalar``: o utilizador dá o endereço de um repositório,
o agente consulta-o (``inspect``), o utilizador confirma e ``build_entry`` descarrega o ficheiro para
lhe calcular o SHA-256 e fixa a versão — o commit exato do código, ou um ficheiro de uma release.
A instalação propriamente dita é feita pelo ``tool_installer``, pelas mesmas regras das outras.

Regras:
- só ``https://github.com/<dono>/<repositório>``; as respostas da API do GitHub são dados, não instruções;
- nunca «a última versão» na lista: fica sempre o commit ou a etiqueta da release e o SHA-256;
- nada é executado: o código é extraído, os ficheiros de release são extraídos ou copiados;
- não segue submódulos nem instala dependências — isso fica dito no resultado.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import quote, urlsplit

import tool_installer
from tool_installer import Cancelled, InstallError

API = 'https://api.github.com'
MAX_BYTES = 1024 ** 3  # 1 GB por ficheiro
NAME = re.compile(r'[A-Za-z0-9_][A-Za-z0-9._-]{0,99}')
REF = re.compile(r'[A-Za-z0-9][A-Za-z0-9._/+-]{0,199}')
SHA = re.compile(r'[0-9a-f]{40}')
ARCHIVES = (('.tar.gz', 'tar'), ('.tar.xz', 'tar'), ('.tar.bz2', 'tar'), ('.tgz', 'tar'), ('.tar', 'tar'), ('.zip', 'zip'), ('.7z', '7zip'))


class NotFound(InstallError):
    pass


def parse_repo(url) -> tuple:
    """(dono, repositório) de um endereço ``https://github.com/dono/repositório[/…]``."""
    parts = urlsplit(url.strip() if isinstance(url, str) else '')
    segments = [item for item in parts.path.split('/') if item]
    if parts.scheme != 'https' or parts.netloc.lower() not in ('github.com', 'www.github.com') or len(segments) < 2:
        raise InstallError('Só aceito endereços do GitHub no formato https://github.com/<dono>/<repositório>.')
    owner, repo = segments[0], segments[1][:-4] if segments[1].endswith('.git') else segments[1]
    if not NAME.fullmatch(owner) or not NAME.fullmatch(repo) or '..' in owner + repo:
        raise InstallError('Endereço do GitHub com um nome inválido.')
    return owner, repo


def _get_json(path: str):
    """Consulta a API pública do GitHub (sem conta). Substituído nos testes."""
    import requests
    response = requests.get(API + path, timeout=30, headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'MeisterCode-tool-installer'})
    if response.status_code == 404:
        raise NotFound('O GitHub não encontrou: ' + path)
    if response.status_code in (403, 429):
        raise InstallError('O GitHub recusou o pedido (limite de consultas sem conta: 60 por hora). Tenta mais tarde.')
    if response.status_code != 200:
        raise InstallError('O GitHub respondeu com o código %d.' % response.status_code)
    return response.json()


def _text(value, limit=300) -> str:
    return ' '.join(value.split())[:limit] if isinstance(value, str) else ''


def _release(owner, repo, ref):
    """A release com a etiqueta ``ref`` ou, sem ``ref``, a mais recente; None se não houver."""
    try:
        data = _get_json('/repos/%s/%s/releases/%s' % (owner, repo, 'tags/' + quote(ref, safe='') if ref else 'latest'))
    except NotFound:
        return None
    tag = data.get('tag_name') if isinstance(data, dict) else None
    if not isinstance(tag, str) or not REF.fullmatch(tag):
        return None
    assets = []
    prefix = 'https://github.com/%s/%s/releases/download/' % (owner, repo)
    for item in (data.get('assets') or [])[:100]:
        name, size, url = item.get('name'), item.get('size'), item.get('browser_download_url')
        # o nome vira nome de ficheiro local: só nomes simples, e só endereços de download deste repositório
        if isinstance(name, str) and NAME.fullmatch(name) and isinstance(size, int) and 0 < size and isinstance(url, str) and url.lower().startswith(prefix.lower()):
            assets.append(dict(nome=name, bytes=size, url=url))
    return dict(tag=tag, assets=assets)


def inspect(url, ref='') -> dict:
    """O que o GitHub diz de um repositório. Só lê; não descarrega nem altera nada."""
    owner, repo = parse_repo(url)
    ref = ref.strip() if isinstance(ref, str) else ''
    if ref and (not REF.fullmatch(ref) or '..' in ref):
        raise InstallError('Versão, etiqueta ou commit inválido.')
    try:
        info = _get_json('/repos/%s/%s' % (owner, repo))
    except NotFound:
        raise InstallError('O repositório %s/%s não existe ou é privado.' % (owner, repo)) from None
    branch = info.get('default_branch') if isinstance(info.get('default_branch'), str) and REF.fullmatch(info['default_branch']) else 'main'
    release = _release(owner, repo, ref)
    target = ref or (release['tag'] if release else branch)
    try:
        commit = _get_json('/repos/%s/%s/commits/%s' % (owner, repo, quote(target, safe='')))
    except NotFound:
        raise InstallError('Não encontrei a versão «%s» em %s/%s.' % (target, owner, repo)) from None
    sha = commit.get('sha') if isinstance(commit, dict) else None
    if not isinstance(sha, str) or not SHA.fullmatch(sha):
        raise InstallError('O GitHub não devolveu um commit válido.')
    date = _text(((commit.get('commit') or {}).get('committer') or {}).get('date'), 10)
    licence = info.get('license') if isinstance(info.get('license'), dict) else {}
    return dict(repositorio='%s/%s' % (owner, repo), endereco='https://github.com/%s/%s' % (owner, repo), descricao=_text(info.get('description')),
                licenca=_text(licence.get('spdx_id'), 60) or 'não indicada', arquivado=bool(info.get('archived')), ramo=branch,
                versao=release['tag'] if release else '', commit=sha, data_do_commit=date,
                ficheiros_da_release=[dict(nome=item['nome'], bytes=item['bytes']) for item in (release['assets'] if release else [])],
                _owner=owner, _repo=repo, _assets=release['assets'] if release else [])


def make_key(repo: str, taken) -> str:
    """Chave (e nome da pasta) a partir do nome do repositório, sem colidir com as que existem."""
    words = [word for word in re.split(r'[^A-Za-z0-9]+', repo) if word]
    base = ''.join(word[:1].upper() + word[1:] for word in words)[:40] or 'Ferramenta'
    if base[0].isdigit() or base.startswith('Core'):
        base = 'F' + base  # uma chave não começa por algarismo, e as «Core…» são do núcleo
    lowered = {key.lower() for key in taken}
    key, number = base, 2
    while key.lower() in lowered:
        key = '%s%d' % (base, number)
        number += 1
    return key


def find_existing(manifest: dict, owner: str, repo: str):
    """A entrada da lista que já vem deste repositório, se houver."""
    wanted = 'github.com/%s/%s' % (owner.lower(), repo.lower())
    for tool in manifest['tools']:
        address = (tool.get('repo') or '').lower().rstrip('/')
        if address.endswith(wanted) or address.endswith(wanted + '.git'):
            return tool
    return None


def _fetch(url: str, destination: Path, expected: int, stop=None, progress=None) -> tuple:
    """Descarrega para ``destination`` e devolve (sha256, bytes). É este ficheiro que o instalador depois confere e usa."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + '.parte-pedido')
    digest, received = hashlib.sha256(), 0
    try:
        response = tool_installer._open_url(url)
        try:
            with partial.open('wb') as handle:
                for chunk in response.iter_content(tool_installer.CHUNK):
                    if stop is not None and stop.is_set():
                        raise Cancelled('Cancelado.')
                    received += len(chunk)
                    if received > MAX_BYTES or (expected and received > expected * 2 + 1048576):
                        raise InstallError('O ficheiro é maior do que o limite (1 GB) ou do que o GitHub anunciou; descarga interrompida.')
                    digest.update(chunk)
                    handle.write(chunk)
                    if progress:
                        progress(received)
        finally:
            response.close()
        if not received:
            raise InstallError('O GitHub devolveu um ficheiro vazio.')
        tool_installer._replace(partial, destination)
        return digest.hexdigest(), received
    except InstallError:
        raise
    except Exception as exc:  # noqa: BLE001  (rede, disco)
        raise InstallError('Falha ao descarregar de %s: %s' % (urlsplit(url).netloc, str(exc)[:300])) from None
    finally:
        tool_installer._remove(partial)
        if not destination.exists():
            for folder in (destination.parent, destination.parent.parent):
                try:
                    folder.rmdir()  # não deixar pastas vazias de um pedido que falhou
                except OSError:
                    break


def plan(info: dict, asset='') -> dict:
    """O passo de instalação que resulta da consulta: o código do commit, ou um ficheiro da release."""
    owner, repo, sha = info['_owner'], info['_repo'], info['commit']
    asset = asset.strip() if isinstance(asset, str) else ''
    if not asset:
        return dict(what='código-fonte (commit %s%s)' % (sha[:8], ', ' + info['data_do_commit'] if info['data_do_commit'] else ''),
                    url='https://codeload.github.com/%s/%s/zip/%s' % (owner, repo, sha), bytes=0, publisher_digest=False,
                    action='source', file=sha + '.zip', to='source', strip=1, repository='%s/%s' % (owner, repo), commit=sha)
    found = next((item for item in info['_assets'] if item['nome'] == asset), None)
    if found is None:
        raise InstallError('A release %s não tem o ficheiro «%s». Ficheiros: %s.' % (
            info['versao'] or '(nenhuma)', asset[:80], ', '.join(item['nome'] for item in info['_assets'][:20]) or 'nenhum'))
    if found['bytes'] > MAX_BYTES:
        raise InstallError('O ficheiro tem %d MB; o limite é 1024 MB.' % (found['bytes'] // 1048576))
    step = dict(what='ficheiro da release %s' % info['versao'], url=found['url'], bytes=found['bytes'], publisher_digest=False, file=found['nome'])
    kind = next((kind for suffix, kind in ARCHIVES if found['nome'].lower().endswith(suffix)), None)
    if kind:
        step.update(action='extract', format=kind, to='app')
    else:
        step.update(action='copy', to='app/' + found['nome'])  # um ficheiro solto (por exemplo .exe ou .jar) é só copiado, nunca executado
    return step


def build_entry(root, manifest: dict, info: dict, asset='', name='', description='', stop=None, progress=None) -> dict:
    """Descarrega o ficheiro, calcula-lhe o SHA-256 e devolve a entrada pronta para a lista extra."""
    owner, repo = info['_owner'], info['_repo']
    existing = find_existing(manifest, owner, repo)
    if existing is not None:
        raise InstallError('Este repositório já está na lista de ferramentas com a chave %s.' % existing['key'])
    step = plan(info, asset)
    key = make_key(repo, [tool['key'] for tool in manifest['tools']])
    digest, size = _fetch(step['url'], Path(root) / key / 'downloads' / step['file'], step['bytes'], stop, progress)
    step.update(sha256=digest, bytes=size)
    text = _text(description, tool_installer.MAX_DESCRIPTION) or info['descricao']
    if len(text) < 10:
        text = 'Ferramenta acrescentada a pedido a partir de %s (sem descrição no GitHub).' % info['endereco']
    notes = ['Só é descarregada e extraída: não instala dependências, não compila e não segue submódulos.']
    if info['arquivado']:
        notes.append('O repositório está arquivado pelo autor.')
    entry = dict(key=key, name=_text(name, 80) or repo, description=text, group=tool_installer.EXTRA_GROUP, repo=info['endereco'],
                 version=info['versao'] if asset else (info['versao'] or info['commit'][:8]), license=info['licenca'], installed_mb=0,
                 requires=['Core7Zip'] if step.get('format') == '7zip' else [], note=' '.join(notes), present='%s/%s' % (key, 'source' if not asset else 'app'),
                 automatic=True, pending='', integrated=False, steps=[step])
    tool_installer.validate_extra(entry, {tool['key'] for tool in manifest['tools']})
    return entry
