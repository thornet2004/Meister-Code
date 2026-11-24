"""A rig do utilizador: o seu modelo local, à parte dos provedores da nuvem.

A rig corre servidores compatíveis com a OpenAI (llama.cpp) na rede local. Na configuração é um provedor como os
outros, marcado com ``rig: True`` e gerido só pela secção «A minha rig» das Configurações: liga-se e desliga-se
sem perder o endereço nem a chave, e leva o esforço de raciocínio escolhido (leve, moderado, pesado).
Desligada, não aparece na barra de modelos. A chave nunca vai para a interface.
"""

from __future__ import annotations

from urllib.parse import urlsplit

NAME = 'Meister Chat'  # como a rig aparece na barra de modelos (nome pedido pelo user)
EFFORTS = {'leve': 'low', 'moderado': 'medium', 'pesado': 'high'}
WHISPER_PORT = 8089
TIMEOUT = (4, 15)  # segundos para ligar / para responder
SPAN = 6           # a rig serve um modelo por porta, em portas seguidas: procuram-se estas a partir da indicada


class RigError(Exception):
    """Falha ao falar com a rig, com mensagem para o utilizador."""


def origin(value) -> str:
    """Endereço da rig sem caminho (``http://192.168.0.10:8081``); aceita-se com ``/v1`` no fim. Vazio se não houver."""
    value = (value or '').strip().rstrip('/') if isinstance(value, str) else ''
    if value.endswith('/v1'):
        value = value[:-3].rstrip('/')
    if not value:
        return ''
    parsed = urlsplit(value)
    if (len(value) > 200 or parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment):
        raise RigError('Endereço da rig inválido: usa só http://endereço:porta.')
    return value


def find(cfg: dict):
    """O provedor que representa a rig, ou ``None``."""
    return next((p for p in cfg.get('providers', []) if isinstance(p, dict) and p.get('rig')), None)


def whisper_address(address: str, gateway: bool = False) -> str:
    """Onde o servidor de transcrição da rig escuta: a mesma máquina, porta fixa. Pelo porteiro é o próprio endereço."""
    if gateway:
        return address
    parsed = urlsplit(address)
    return '%s://%s:%d' % (parsed.scheme, parsed.hostname, WHISPER_PORT) if parsed.hostname else ''


def probe(address: str, key: str = '', timeout=TIMEOUT) -> dict:
    """Pergunta à rig que modelo tem carregado e com que contexto. ``RigError`` se não responder ou recusar."""
    import requests
    headers = {'Authorization': 'Bearer ' + key} if key else {}
    try:
        response = requests.get(address + '/props', headers=headers, timeout=timeout)
    except requests.RequestException:
        raise RigError('A rig não respondeu em %s. Confirma que está ligada e o endereço.' % address) from None
    if response.status_code == 401:
        raise RigError('A rig recusou a chave.')
    if response.status_code == 503:
        raise RigError('A rig ainda está a carregar o modelo; tenta daqui a um ou dois minutos.')
    if response.status_code != 200:
        raise RigError('A rig devolveu o erro %d.' % response.status_code)
    try:
        data = response.json()
        model = str(data.get('model_alias') or '').strip()
        context = int((data.get('default_generation_settings') or {}).get('n_ctx') or 0)
    except (ValueError, AttributeError, TypeError):
        raise RigError('A rig respondeu num formato que não conheço.') from None
    if not model:
        raise RigError('A rig respondeu sem dizer que modelo tem.')
    found = dict(model=model, context=context)
    if isinstance(data.get('modalities'), dict):  # o servidor diz se o modelo lê imagens (precisa do projetor carregado)
        found['vision'] = bool(data['modalities'].get('vision'))
    return found


def gateway(address: str, key: str = ''):
    """Os modelos ao alcance desta chave quando o endereço é o porteiro da rig (uma porta única para todos os
    modelos e a voz; é o que se usa de fora, por HTTPS). ``None`` se o endereço não for um porteiro."""
    import requests
    try:
        response = requests.get(address + '/v1/models', headers={'Authorization': 'Bearer ' + key} if key else {}, timeout=TIMEOUT)
        data = response.json() if response.status_code == 200 else None
    except (requests.RequestException, ValueError):
        return None
    if response.status_code == 401:
        raise RigError('A rig recusou a chave.')
    if not isinstance(data, dict) or not data.get('porteiro') or not isinstance(data.get('data'), list):
        return None
    models = []
    for item in data['data']:
        name = str(item.get('id') or '').strip() if isinstance(item, dict) else ''
        if name:
            context = item.get('context')
            entry = dict(model=name, context=context if isinstance(context, int) and context > 0 else 0, base=address, gateway=True)
            if isinstance(item.get('vision'), bool):
                entry['vision'] = item['vision']
            models.append(entry)
    return models


def probe_all(address: str, key: str = '') -> list:
    """Todos os modelos que a rig tem a correr: o da porta indicada (obrigatório) e os das portas seguintes.
    Cada um vem com ``model``, ``context`` e ``base`` (o endereço do servidor que o serve)."""
    import threading
    through = gateway(address, key)
    if through is not None:
        if not through:
            raise RigError('A rig respondeu, mas esta chave não tem nenhum modelo ao alcance.')
        return through
    found = {0: dict(probe(address, key), base=address)}
    parsed = urlsplit(address)
    port = parsed.port or (443 if parsed.scheme == 'https' else 80)

    def look(step):
        base = '%s://%s:%d' % (parsed.scheme, parsed.hostname, port + step)
        try:
            found[step] = dict(probe(base, key, timeout=(1.5, 6)), base=base)
        except RigError:
            pass  # porta sem servidor (ou ainda a carregar): simplesmente não entra na lista
    threads = [threading.Thread(target=look, args=(step,), daemon=True) for step in range(1, SPAN)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    models, seen = [], set()
    for step in sorted(found):
        if found[step]['model'] not in seen:
            seen.add(found[step]['model'])
            models.append(found[step])
    return models


def routed(provider: dict, model: dict) -> dict:
    """O provedor a usar para este modelo: na rig cada modelo tem o seu servidor (``base_url`` no modelo)."""
    if (provider or {}).get('rig') and (model or {}).get('base_url'):
        return {**provider, 'base_url': model['base_url']}
    return provider


def reasoning(provider: dict, voice: bool = False) -> dict:
    """Opções a juntar ao pedido de conversa: na conversa por voz não se raciocina (são segundos de silêncio);
    na rig usa-se o esforço escolhido pelo utilizador."""
    if voice:
        return {'reasoning_effort': 'none'}
    if (provider or {}).get('rig'):
        return {'reasoning_effort': EFFORTS.get(provider.get('effort'), 'low')}
    return {}


def state(cfg: dict) -> dict:
    """O que a interface mostra na secção «A minha rig» (sem a chave)."""
    provider = find(cfg) or {}
    models = provider.get('models') or []
    address = ''
    try:
        address = origin(provider.get('base_url', ''))
    except RigError:
        pass
    return dict(enabled=bool(provider.get('enabled')), address=address, has_key=bool((provider.get('api_key') or '').strip()),
                effort=provider.get('effort') if provider.get('effort') in EFFORTS else 'leve',
                whisper=bool(provider.get('enabled') and cfg.get('preferences', {}).get('voice_server')), gateway=bool(provider.get('gateway')),
                model=models[0].get('id', '') if models else '', models=[m.get('id', '') for m in models],
                context=int((models[0].get('defaults') or {}).get('context_window') or 0) if models else 0)
