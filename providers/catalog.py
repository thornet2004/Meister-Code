"""Capability metadata for model discovery; never infer generation from input vision."""
from __future__ import annotations
import re

LABELS = {'chat': 'Chat', 'code': 'Código', 'image': 'Imagem', 'video': 'Vídeo',
          'audio': 'Áudio / voz', 'transcription': 'Transcrição', 'embeddings': 'Embeddings',
          'rerank': 'Reranking', 'decisions': 'Decisões', 'other': 'Outros'}
ROUTES = {'chat': '/api/v1/chat/completions', 'image': '/api/v1/images',
          'video': '/api/v1/videos', 'audio': '/api/v1/audio/speech'}


def normalize(item, kind):
    mid = (item.get('id') or item.get('name') or '').removeprefix('models/')
    if not mid:
        return None
    architecture = item.get('architecture') or {}
    outputs = architecture.get('output_modalities') or ([] if kind == 'openrouter' else ['text'])
    inputs = architecture.get('input_modalities') or []
    endpoints = item.get('endpoints') or []
    categories = []
    types = []
    for modality in outputs:
        category = {'text': 'chat', 'speech': 'audio'}.get(modality, modality)
        if category not in LABELS:
            category = 'other'
        if category not in categories:
            categories.append(category)
        if category in ROUTES and (kind != 'openrouter' or ROUTES[category] in endpoints):
            if category not in types:
                types.append(category)
    name = item.get('display_name') or item.get('displayName') or item.get('name') or mid
    description = item.get('description') or ''
    # This is a search tag, not a claim that other text models cannot code.
    if 'chat' in categories and re.search(r'\b(code|coding|coder|codex|programming|software engineering)\b',
                                         mid + ' ' + name + ' ' + description, re.I):
        categories.append('code')
    defaults = {}
    context = item.get('context_length') or item.get('inputTokenLimit')
    if isinstance(context, int) and context > 0:
        defaults['context_window'] = context
    voices = [v for v in (item.get('supported_voices') or []) if isinstance(v, str) and v.strip()][:300]  # cada modelo de voz tem as suas
    return dict(id=mid, name=name, description=description[:1600], categories=categories or ['other'], voices=voices,
                types=types, input_modalities=inputs, output_modalities=outputs,
                endpoints=endpoints, supported_parameters=item.get('supported_parameters') or [],
                defaults=defaults, pricing=item.get('pricing') or {}, code_tag_inferred='code' in categories)


def merge(provider, catalog):
    """Merge by (id, capability), preserving user defaults, names and selections."""
    models = provider.setdefault('models', [])
    existing = {(m['id'], m.get('type', 'image')): m for m in models}
    added = 0
    for entry in catalog:
        for capability in entry['types']:
            key = (entry['id'], capability)
            model = existing.get(key)
            if model is None:
                model = dict(id=entry['id'], name=entry['name'], type=capability,
                             defaults=dict(entry['defaults']), catalog_managed=True)
                models.append(model)
                existing[key] = model
                added += 1
            model['categories'] = entry['categories']
            model['supported_parameters'] = entry['supported_parameters']
            if capability == 'audio' and entry.get('voices'):
                model['voices'] = entry['voices']
            model['catalog_available'] = True
            for key, value in entry['defaults'].items():
                model.setdefault('defaults', {}).setdefault(key, value)
    available = {(entry['id'], typ) for entry in catalog for typ in entry['types']}
    for model in models:
        if model.get('catalog_managed'):
            model['catalog_available'] = (model['id'], model.get('type')) in available
    provider['catalog'] = catalog
    return added

