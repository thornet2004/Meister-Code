"""Ferramenta ``excel_analisar``: análise de folhas de Excel com a SheetBrain (vendored).

A SheetBrain (microsoft/SheetBrain, MIT; incorporada em ``sheetbrain/``) é um agente de
três fases — Entender → Executar → Validar — que responde a perguntas sobre folhas de
cálculo com rigor. Fala por API compatível com OpenAI, por isso aponta-se ao mesmo
provedor/modelo de conversa que o utilizador já escolheu (a rig, OpenAI, OpenRouter, …).

Nada de credenciais vai para os registos: a chave fica no cliente; só a resposta volta.
"""
from __future__ import annotations

import contextlib
import io
import os

# Famílias de provedor que falam o formato de chat da OpenAI (chat.completions), que é o
# que a SheetBrain usa. Anthropic e Google (nativos) não servem para esta ferramenta.
OPENAI_COMPATIBLE = frozenset({
    "openrouter", "openai", "ollama", "lmstudio", "together",
    "fireworks", "deepinfra", "cometapi", "apimart", "openai-compatible",
})

READABLE_SUFFIXES = (".xlsx", ".xlsm")


def analyse(xlsx_path, question, provider, model, *, max_turns=3,
            validation=True, understanding=True, token_budget=8000):
    """Corre a SheetBrain sobre ``xlsx_path`` e devolve um resumo da resposta.

    ``provider``/``model`` são os dicts do provedor e modelo de conversa atuais da app.
    Devolve sempre um dict (nunca levanta): ``ok`` + ``resposta``/``erro``.
    """
    if not question or not str(question).strip():
        return {"ok": False, "erro": "Falta a pergunta sobre a folha."}
    xlsx_path = str(xlsx_path)
    if not os.path.isfile(xlsx_path):
        return {"ok": False, "erro": "Ficheiro não encontrado: " + xlsx_path}
    if os.path.splitext(xlsx_path)[1].lower() not in READABLE_SUFFIXES:
        return {"ok": False, "erro": "A ferramenta lê folhas .xlsx ou .xlsm."}

    from providers import multi
    from providers.base import ProviderError
    try:
        kind, base, key, _ = multi.settings(provider)
    except ProviderError as exc:
        return {"ok": False, "erro": str(exc)}
    if kind not in OPENAI_COMPATIBLE:
        return {"ok": False, "erro": (
            "A análise de Excel precisa de um modelo compatível com OpenAI "
            "(a tua rig, OpenRouter, OpenAI, Together, …). O modelo de conversa atual "
            "(" + str(kind) + ") não serve — escolhe outro em «💬 Conversa» para este pedido.")}

    deployment = (model or {}).get("id") or (model or {}).get("name") or ""
    buf = io.StringIO()
    try:
        # A SheetBrain escreve muito no stdout/stderr (registo com emojis); numa app sem
        # consola isso rebentaria. Redireciona-se tudo para um buffer durante a corrida —
        # e importa-se já aqui, para o logger da SheetBrain prender um stream válido.
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            import sheetbrain
            cfg = sheetbrain.Config(
                api_key=key or "sk-local", base_url=base, deployment=deployment,
                max_turns=int(max_turns), enable_validation=bool(validation),
                enable_understanding=bool(understanding), total_token_budget=int(token_budget),
            )
            agent = sheetbrain.SheetBrain(xlsx_path, config=cfg, total_token_budget=int(token_budget))
            result = agent.run(
                question, max_turns=int(max_turns),
                enable_validation=bool(validation), enable_understanding=bool(understanding),
            )
    except Exception as exc:  # noqa: BLE001 — devolve o erro ao agente, nunca rebenta o turno
        return {"ok": False, "erro": "Falha na análise: " + str(exc)}

    return {
        "ok": bool(result.get("success")),
        "resposta": result.get("answer", ""),
        "confianca": round(float(result.get("confidence_score", 0.0) or 0.0), 2),
        "validado": bool(result.get("validation_passed")),
        "iteracoes": int(result.get("total_iterations", 0) or 0),
        "segundos": round(float(result.get("total_duration", 0.0) or 0.0), 1),
        "modelo": deployment,
    }
