"""Custo das respostas e das conversas, em dólares (a moeda dos preços dos provedores).

Fontes, por ordem de confiança:
  1. ``provider``  — o valor que o próprio provedor devolveu com a resposta
     (campo ``cost`` do ``usage``, por exemplo no OpenRouter);
  2. ``catalog``   — tokens × preço por token do catálogo sincronizado do provedor;
  3. ``manual``    — tokens × preços por milhão definidos pelo utilizador nos
     limites de execução (``input_per_million`` / ``output_per_million``).

Quando não há nenhuma, o custo é DESCONHECIDO: conta-se à parte, não se inventa.
Tudo o que não vem de ``provider`` é uma estimativa — a fatura do provedor é que
manda (descontos, cache, taxas e imagens não entram aqui).
"""
from __future__ import annotations

import math

CURRENCY = 'USD'


def _number(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def prices(cfg: dict, provider_id: str, model_id: str) -> dict | None:
    """Preço por token ``{'input', 'output', 'source'}`` de um modelo, ou ``None``."""
    provider = next((p for p in cfg.get('providers', []) if p.get('id') == provider_id), None)
    if provider is not None:
        for row in provider.get('catalog') or []:
            if not isinstance(row, dict) or row.get('id') != model_id:
                continue
            pricing = row.get('pricing') or {}
            entrada, saida = _number(pricing.get('prompt')), _number(pricing.get('completion'))
            # valores negativos significam "preço variável" no catálogo: não servem para estimar
            if entrada is not None and saida is not None and entrada >= 0 and saida >= 0:
                return dict(input=entrada, output=saida, source='catalog')
            break
    limits = (cfg.get('preferences') or {}).get('execution_limits') or {}
    entrada, saida = _number(limits.get('input_per_million')), _number(limits.get('output_per_million'))
    if entrada is not None and saida is not None and (entrada > 0 or saida > 0) and entrada >= 0 and saida >= 0:
        return dict(input=entrada / 1_000_000, output=saida / 1_000_000, source='manual')
    return None


def _tokens(usage: dict) -> tuple[int, int]:
    def count(key):
        number = _number((usage or {}).get(key))
        return int(number) if number and number > 0 else 0
    entrada, saida = count('prompt_tokens'), count('completion_tokens')
    if not entrada and not saida:
        entrada = count('total_tokens')  # só o total: conta como entrada (o preço mais baixo)
    return entrada, saida


def estimate(usage: dict, price: dict | None) -> float | None:
    if not price:
        return None
    entrada, saida = _tokens(usage)
    return entrada * price['input'] + saida * price['output']


def reported(usage: dict) -> float | None:
    """Custo devolvido pelo provedor nesta chamada, se vier."""
    number = _number((usage or {}).get('cost'))
    return number if number is not None and number >= 0 else None


def turn_cost(cfg: dict, provider_id: str, model_id: str, usage: dict, reported_total: float | None = None) -> dict | None:
    """Registo de custo a guardar com uma resposta: ``{'usd', 'source'}`` ou ``None``."""
    if reported_total is not None:
        return dict(usd=round(reported_total, 8), source='provider')
    price = prices(cfg, provider_id, model_id)
    value = estimate(usage, price)
    if value is None:
        return None
    return dict(usd=round(value, 8), source=price['source'])


def summary(cfg: dict, conversation: list, tasks: list | None = None) -> dict:
    """Custo acumulado de uma conversa (respostas do assistente + subagentes)."""
    total = 0.0
    exact = True          # todos os valores vieram do provedor?
    counted = unknown = 0
    entrada_total = saida_total = 0
    by_model: dict[str, dict] = {}

    def add(model_id, usage, usd, source):
        nonlocal total, exact, counted, unknown, entrada_total, saida_total
        entrada, saida = _tokens(usage)
        if not entrada and not saida:
            return
        entrada_total += entrada
        saida_total += saida
        row = by_model.setdefault(model_id or '(modelo não registado)', dict(usd=0.0, tokens=0, unknown=0))
        row['tokens'] += entrada + saida
        if usd is None:
            unknown += 1
            row['unknown'] += 1
            return
        counted += 1
        total += usd
        row['usd'] += usd
        if source != 'provider':
            exact = False

    for message in conversation or []:
        if not isinstance(message, dict) or message.get('role') != 'assistant':
            continue
        usage = message.get('usage') or {}
        model = message.get('model') or {}
        stored = message.get('cost') or {}
        usd = _number(stored.get('usd'))
        source = stored.get('source') or ''
        if usd is None and model.get('model_id'):
            # resposta antiga sem custo guardado: estima com o preço de hoje
            price = prices(cfg, model.get('provider_id', ''), model['model_id'])
            usd, source = estimate(usage, price), 'estimate'
        add(model.get('model_id', ''), usage, usd, source)

    agents = dict(usd=0.0, tasks=0)
    for task in tasks or []:
        if not isinstance(task, dict):
            continue
        usage = task.get('usage') or {}
        before = total
        price = prices(cfg, task.get('provider_id', ''), task.get('model_id', ''))
        entrada, saida = _tokens(usage)
        if not entrada and not saida:
            continue
        add(task.get('model_id', ''), usage, estimate(usage, price), 'estimate')
        agents['tasks'] += 1
        agents['usd'] += total - before

    models = [dict(model_id=name, usd=round(row['usd'], 6), tokens=row['tokens'], unknown=row['unknown'])
              for name, row in sorted(by_model.items(), key=lambda item: -item[1]['usd'])]
    return dict(usd=round(total, 6), currency=CURRENCY, exact=bool(counted) and exact and not unknown,
                turns=counted, unknown_turns=unknown, prompt_tokens=entrada_total, completion_tokens=saida_total,
                models=models, subagents=dict(usd=round(agents['usd'], 6), tasks=agents['tasks']),
                note='Estimativa a partir dos tokens e dos preços conhecidos; a fatura do provedor prevalece. '
                     'Não inclui geração de imagem, vídeo e áudio nem embeddings.')
