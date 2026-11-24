"""Imagem e vídeo por provedores que trabalham por tarefa: Replicate, fal.ai e Kie.ai.

Os três seguem o mesmo desenho — cria-se a tarefa, espera-se pelo estado final e descarrega-se o
ficheiro do endereço que o provedor devolve — mas cada um com os seus endereços, cabeçalhos e nomes:

- Replicate: ``POST /models/{dono}/{modelo}/predictions`` (ou ``/predictions`` com ``version``), consulta em ``urls.get``;
- fal.ai:    ``POST https://queue.fal.run/{modelo}``, consulta em ``status_url``, resultado em ``response_url``;
- Kie.ai:    ``POST /jobs/createTask``, consulta em ``/jobs/recordInfo?taskId=…`` (o erro vem no campo ``code``, com HTTP 200).

Regras:
- a chave só é enviada para o próprio provedor; os ficheiros gerados são descarregados sem ela;
- só se seguem endereços HTTPS, e os endereços de consulta têm de ser do provedor;
- as respostas são dados: nada do que vem nelas é executado.

Cada função devolve ``(lista de bytes, metadados)``, como as do OpenRouter.
"""
from __future__ import annotations

import json
import re
import time
from urllib.parse import quote, urlsplit

import requests

from .base import ProviderError

KINDS = ('replicate', 'fal', 'kie')
PRESETS = {
    'replicate': dict(label='Replicate · imagem e vídeo', base_url='https://api.replicate.com/v1', requires_key=True),
    'fal': dict(label='fal.ai · imagem e vídeo', base_url='https://queue.fal.run', requires_key=True),
    'kie': dict(label='Kie.ai · imagem e vídeo', base_url='https://api.kie.ai/api/v1', requires_key=True),
}
SUBMIT_TIMEOUT = 90
POLL_INTERVAL = 3
MAX_WAIT = {'image': 300, 'video': 900}
MAX_BYTES = {'image': 60 * 1024 * 1024, 'video': 600 * 1024 * 1024}
MAX_FILES = 8
# campos que a app sabe preencher (predefinições do modelo); o resto vai em ``input``, por modelo
_FIELDS = {'image': ('aspect_ratio', 'resolution', 'seed'), 'video': ('duration', 'aspect_ratio', 'resolution', 'seed')}
_EXTENSIONS = {'image': ('png', 'jpg', 'jpeg', 'webp', 'gif'), 'video': ('mp4', 'webm', 'mov')}
_TYPES = {'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp', 'image/gif': 'gif', 'video/mp4': 'mp4', 'video/webm': 'webm', 'video/quicktime': 'mov'}
_SEGMENT = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,99}')
_VERSION = re.compile(r'[0-9a-f]{64}')


def _sleep(seconds):  # substituído nos testes
    time.sleep(seconds)


def _settings(provider):
    kind = provider.get('kind')
    base = (provider.get('base_url') or PRESETS[kind]['base_url']).strip().rstrip('/')
    key = (provider.get('api_key') or '').strip()
    parsed = urlsplit(base)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ProviderError('URL do provedor inválido; usa uma base HTTPS sem credenciais nem parâmetros.')
    if not key:
        raise ProviderError('Adiciona a chave de API deste provedor nas Configurações.')
    headers = {'Content-Type': 'application/json', 'Authorization': ('Key ' if kind == 'fal' else 'Bearer ') + key}
    return base, key, headers


def _hide(text, key):
    return str(text).replace(key, '[chave oculta]') if key else str(text)


def _call(method, url, key, headers, body=None, extra=None):
    """Um pedido ao provedor; devolve o JSON. Erros de rede e HTTP viram ``ProviderError`` sem a chave."""
    try:
        response = requests.request(method, url, headers={**headers, **(extra or {})}, json=body, timeout=SUBMIT_TIMEOUT)
    except requests.RequestException as exc:
        raise ProviderError('Falha de ligação ao provedor: ' + _hide(exc, key)) from None
    text = response.text or ''
    if not response.ok:
        raise ProviderError('Erro HTTP %d do provedor: %s' % (response.status_code, _hide(text[:1500], key)))
    try:
        data = response.json()
    except ValueError:
        raise ProviderError('O provedor não respondeu em JSON: ' + _hide(text[:500], key)) from None
    if not isinstance(data, dict):
        raise ProviderError('O provedor devolveu uma resposta num formato inesperado.')
    return data


def _same_host(url, base):
    """Um endereço de consulta só é aceite se for HTTPS e do próprio provedor: é para lá que vai a chave."""
    parts = urlsplit(url if isinstance(url, str) else '')
    return parts.scheme == 'https' and parts.hostname == urlsplit(base).hostname


def _model_path(model_id):
    parts = model_id.split('/')
    if len(parts) < 2 or not all(_SEGMENT.fullmatch(part) for part in parts) or '..' in model_id:
        raise ProviderError('Identificador de modelo inválido: «%s». Usa o formato dono/modelo.' % model_id[:120])
    return '/'.join(quote(part, safe='') for part in parts)


def _inputs(capability, prompt, params):
    """O que se envia ao modelo: o prompt, os campos que a app conhece e, por cima, o ``input`` próprio do modelo."""
    params = params or {}
    values = {'prompt': prompt}
    for field in _FIELDS[capability]:
        value = params.get(field)
        if value not in (None, '', 0, []):
            values[field] = value
    extra = params.get('input')
    if isinstance(extra, dict):
        values.update({key: value for key, value in extra.items() if isinstance(key, str) and not key.startswith('_')})
    return values


def _urls(value, found=None, depth=0):
    """Endereços de ficheiros numa resposta: textos soltos ou em listas, e campos ``url`` de objetos."""
    found = [] if found is None else found
    if depth > 6 or len(found) >= MAX_FILES:
        return found
    if isinstance(value, str):
        if value.startswith('https://') and value not in found:
            found.append(value)
    elif isinstance(value, list):
        for item in value:
            _urls(item, found, depth + 1)
    elif isinstance(value, dict):
        if isinstance(value.get('url'), str):
            _urls(value['url'], found, depth + 1)
        else:
            for key, item in value.items():
                if isinstance(item, (list, dict)):
                    _urls(item, found, depth + 1)
    return found[:MAX_FILES]


def _download(url, capability):
    """Descarrega um ficheiro gerado. Sem a chave: estes endereços são públicos e temporários."""
    if urlsplit(url).scheme != 'https':
        raise ProviderError('O provedor devolveu um endereço sem HTTPS para o ficheiro.')
    limit = MAX_BYTES[capability]
    try:
        with requests.get(url, stream=True, timeout=(30, 300)) as response:
            if not response.ok:
                raise ProviderError('Erro HTTP %d ao descarregar o ficheiro gerado.' % response.status_code)
            chunks, size = [], 0
            for chunk in response.iter_content(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise ProviderError('O ficheiro gerado passa do limite de %d MB.' % (limit // 1048576))
                chunks.append(chunk)
            kind = (response.headers.get('Content-Type') or '').split(';')[0].strip().lower()
    except requests.RequestException as exc:
        raise ProviderError('Falha ao descarregar o ficheiro gerado: %s' % exc) from None
    data = b''.join(chunks)
    if not data:
        raise ProviderError('O provedor devolveu um ficheiro vazio.')
    suffix = urlsplit(url).path.rsplit('.', 1)[-1].lower() if '.' in urlsplit(url).path.rsplit('/', 1)[-1] else ''
    ext = _TYPES.get(kind) or (suffix if suffix in _EXTENSIONS[capability] else '')
    return data, 'jpg' if ext == 'jpeg' else ext


def _collect(urls, capability, source):
    if not urls:
        raise ProviderError('O provedor terminou sem devolver nenhum ficheiro: ' + json.dumps(source, ensure_ascii=False)[:800])
    files, ext = [], ''
    for url in urls:
        data, found = _download(url, capability)
        files.append(data)
        ext = ext or found
    return files, dict(ext=ext or ('png' if capability == 'image' else 'mp4'), media=capability)


def _wait(capability, poll, job):
    """Consulta de ``POLL_INTERVAL`` em ``POLL_INTERVAL`` segundos até ``poll`` devolver um resultado (não ``None``)."""
    waited = 0
    while True:
        done = poll()
        if done is not None:
            return done
        if waited >= MAX_WAIT[capability]:
            raise ProviderError('Tempo esgotado (%d s) à espera do provedor (tarefa %s). A tarefa pode ainda acabar do lado dele.' % (MAX_WAIT[capability], job))
        _sleep(POLL_INTERVAL)
        waited += POLL_INTERVAL


# ---------------------------------------------------------------------- Replicate
def _replicate(capability, provider, model, prompt, params):
    base, key, headers = _settings(provider)
    model_id = (model.get('id') or '').strip()
    body = {'input': _inputs(capability, prompt, params)}
    name, _, version = model_id.partition(':')
    if _VERSION.fullmatch(model_id) or version:
        if version and not _VERSION.fullmatch(version):
            raise ProviderError('Versão de modelo inválida: usa dono/modelo ou dono/modelo:<64 caracteres hexadecimais>.')
        if version:
            _model_path(name)
        body['version'] = model_id
        url = base + '/predictions'
    else:
        url = base + '/models/' + _model_path(model_id) + '/predictions'
    job = _call('POST', url, key, headers, body, {'Prefer': 'wait=30'})
    job_id = job.get('id') if isinstance(job.get('id'), str) else ''
    follow = (job.get('urls') or {}).get('get') if isinstance(job.get('urls'), dict) else None
    if not _same_host(follow, base):
        if not job_id or not _SEGMENT.fullmatch(job_id):
            raise ProviderError('O Replicate não devolveu o identificador da tarefa: ' + _hide(json.dumps(job, ensure_ascii=False)[:600], key))
        follow = base + '/predictions/' + job_id
    state = {'job': job}

    def poll():
        current = state.pop('job', None) or _call('GET', follow, key, headers)
        status = current.get('status')
        if status == 'succeeded':
            return current
        if status in ('failed', 'canceled'):
            raise ProviderError('O Replicate terminou a tarefa com o estado «%s»: %s' % (status, _hide(str(current.get('error') or 'sem detalhe')[:800], key)))
        return None

    done = _wait(capability, poll, job_id or '?')
    return _collect(_urls(done.get('output')), capability, done.get('output'))


# ---------------------------------------------------------------------- fal.ai
def _fal(capability, provider, model, prompt, params):
    base, key, headers = _settings(provider)
    job = _call('POST', base + '/' + _model_path((model.get('id') or '').strip()), key, headers, _inputs(capability, prompt, params))
    status_url, response_url, job_id = job.get('status_url'), job.get('response_url'), job.get('request_id') or '?'
    if not _same_host(status_url, base) or not _same_host(response_url, base):
        raise ProviderError('O fal.ai não devolveu os endereços de consulta esperados: ' + _hide(json.dumps(job, ensure_ascii=False)[:600], key))

    def poll():
        current = _call('GET', status_url, key, headers)
        if current.get('status') != 'COMPLETED':
            return None
        if current.get('error'):
            raise ProviderError('O fal.ai terminou a tarefa com erro: %s' % _hide(str(current.get('error'))[:800], key))
        return current

    _wait(capability, poll, job_id)
    result = _call('GET', response_url, key, headers)
    return _collect(_urls(result), capability, result)


# ---------------------------------------------------------------------- Kie.ai
def _kie_data(reply, key):
    """O Kie.ai responde com HTTP 200 mesmo quando falha: o resultado verdadeiro está em ``code``."""
    if reply.get('code') != 200 or not isinstance(reply.get('data'), dict):
        raise ProviderError('O Kie.ai recusou o pedido (código %s): %s' % (reply.get('code'), _hide(str(reply.get('msg') or 'sem detalhe')[:800], key)))
    return reply['data']


def _kie(capability, provider, model, prompt, params):
    base, key, headers = _settings(provider)
    model_id = (model.get('id') or '').strip()
    if not model_id or len(model_id) > 200:
        raise ProviderError('Identificador de modelo inválido.')
    task = _kie_data(_call('POST', base + '/jobs/createTask', key, headers, {'model': model_id, 'input': _inputs(capability, prompt, params)}), key).get('taskId')
    if not isinstance(task, str) or not task or len(task) > 200:
        raise ProviderError('O Kie.ai não devolveu o identificador da tarefa.')

    def poll():
        data = _kie_data(_call('GET', base + '/jobs/recordInfo?taskId=' + quote(task, safe=''), key, headers), key)
        if data.get('state') == 'success':
            return data
        if data.get('state') == 'fail':
            raise ProviderError('O Kie.ai falhou a tarefa (código %s): %s' % (data.get('failCode') or '?', _hide(str(data.get('failMsg') or 'sem detalhe')[:800], key)))
        return None

    done = _wait(capability, poll, task)
    try:
        result = json.loads(done.get('resultJson') or '{}')
    except (TypeError, ValueError):
        result = {}
    return _collect(_urls(result.get('resultUrls') if isinstance(result, dict) else None), capability, done.get('resultJson'))


def _bind(function, capability):
    def run(provider, model, prompt, params):
        return function(capability, provider, model, prompt, params)
    return run


FAMILIES = {
    'replicate': {'label': 'Replicate', 'image': _bind(_replicate, 'image'), 'video': _bind(_replicate, 'video')},
    'fal': {'label': 'fal.ai', 'image': _bind(_fal, 'image'), 'video': _bind(_fal, 'video')},
    'kie': {'label': 'Kie.ai', 'image': _bind(_kie, 'image'), 'video': _bind(_kie, 'video')},
}


# ---------------------------------------------------------------------- lista de modelos
def models(provider) -> dict:
    """Modelos para o catálogo. Só o Replicate tem uma lista por tipo; nos outros o modelo acrescenta-se pelo identificador."""
    kind = provider.get('kind')
    base, key, headers = _settings(provider)
    if kind != 'replicate':
        return dict(models=[], truncated=False, note='Este provedor não tem uma lista de modelos por tipo: acrescenta o modelo pelo identificador que aparece na página dele (botão «+ Modelo»).')
    rows, seen = [], set()
    for slug, capability in (('text-to-image', 'image'), ('text-to-video', 'video')):
        data = _call('GET', base + '/collections/' + slug, key, headers)
        for item in (data.get('models') or [])[:300]:
            if not isinstance(item, dict) or not isinstance(item.get('owner'), str) or not isinstance(item.get('name'), str):
                continue
            model_id = item['owner'] + '/' + item['name']
            if (model_id, capability) in seen or not all(_SEGMENT.fullmatch(part) for part in model_id.split('/')):
                continue
            seen.add((model_id, capability))
            rows.append(dict(id=model_id, name=model_id, description=str(item.get('description') or '')[:1600], categories=[capability], types=[capability], type=capability,
                             input_modalities=['text'], output_modalities=[capability], endpoints=[], supported_parameters=[], defaults={}, pricing={}, code_tag_inferred=False))
    return dict(models=rows, truncated=False, note='Modelos das coleções «text-to-image» e «text-to-video» do Replicate. Outros modelos acrescentam-se pelo identificador dono/modelo.')
