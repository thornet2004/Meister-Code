"""Adaptador `openrouter-image`.

Chama o endpoint de imagens da OpenRouter e devolve os PNG em bytes.

Detalhes (conforme o spec, confirmados pelo utilizador):
  - Endpoint: POST {base_url}/images
  - Headers:  Authorization: Bearer <api_key>, Content-Type: application/json
  - Body mínimo: { "model": "<id>", "prompt": "<texto>" }
  - Resposta:  { "data": [ { "b64_json": "<base64 PNG>" }, ... ] }
               (se vier "url" em vez de "b64_json", faz-se download)

⚠️ Os nomes exatos dos campos de resolução / aspect ratio / nº de imagens
NÃO estão confirmados. Por isso, por omissão enviamos só model + prompt.
Os parâmetros extra só entram no body quando `params["_experimental"]` é True
(a UI marca-os como experimentais). Assim é fácil ligá-los quando a doc
confirmar os nomes, sem refazer o resto.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import time
from urllib.parse import urlsplit

import requests

from .base import ProviderError

TIMEOUT = 180  # segundos; geração de imagens pode demorar
CHAT_TIMEOUT = 300  # chat pode gerar imagens via tool, logo pode demorar mais
AUDIO_TIMEOUT = 180
VIDEO_SUBMIT_TIMEOUT = 60
VIDEO_POLL_INTERVAL = 6     # segundos entre verificações do estado
VIDEO_MAX_WAIT = 480        # tempo máximo à espera de um vídeo


def _headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        # Recomendados pela OpenRouter para identificar a app (opcionais).
        "HTTP-Referer": "https://localhost/gerador-imagens",
        "X-Title": "MeisterCode",
    }

# Mapeia os nossos nomes de params -> nomes (prováveis) no body da OpenRouter.
# São palpites; ligados só em modo experimental.
_EXPERIMENTAL_FIELDS = {
    "n": "n",
    "resolution": "resolution",
    "aspect_ratio": "aspect_ratio",
}


def gerar(provider: dict, model: dict, prompt: str, params: dict):
    """Gera imagens. Devolve (lista de bytes PNG, metadados_extra)."""
    api_key = (provider.get("api_key") or "").strip()
    if not api_key:
        raise ProviderError(
            "Este provedor não tem chave de API definida. "
            "Edita o provedor e adiciona a chave."
        )

    base_url = (provider.get("base_url") or "https://openrouter.ai/api/v1").rstrip("/")
    url = f"{base_url}/images"

    headers = _headers(api_key)

    body = {"model": model.get("id", ""), "prompt": prompt}

    params = params or {}
    if params.get("_experimental"):
        for nosso_nome, nome_api in _EXPERIMENTAL_FIELDS.items():
            valor = params.get(nosso_nome)
            if valor not in (None, "", []):
                body[nome_api] = valor

    try:
        resp = requests.post(url, json=body, headers=headers, timeout=TIMEOUT)
    except requests.Timeout:
        raise ProviderError(f"Tempo esgotado ({TIMEOUT}s) ao contactar {url}.")
    except requests.RequestException as exc:
        raise ProviderError(f"Falha de ligação a {url}: {exc}")

    if not resp.ok:
        corpo = resp.text or "(sem corpo)"
        if len(corpo) > 2000:
            corpo = corpo[:2000] + "… (truncado)"
        raise ProviderError(
            f"Erro HTTP {resp.status_code} de {url}:\n{corpo}"
        )

    try:
        payload = resp.json()
    except ValueError:
        raise ProviderError(
            "A resposta não é JSON válido:\n" + (resp.text or "(vazio)")[:2000]
        )

    data = payload.get("data")
    if not isinstance(data, list) or not data:
        raise ProviderError(
            "Resposta sem imagens (campo 'data' vazio ou ausente):\n"
            + _resumo(payload)
        )

    imagens: list[bytes] = []
    for item in data:
        imagens.append(_extrair_imagem(item))

    meta_extra = {"ext": "png", "media": "image"}
    if payload.get("model"):
        meta_extra["response_model"] = payload["model"]
    return imagens, meta_extra


def _extrair_imagem(item: dict) -> bytes:
    """Extrai bytes PNG de um item de 'data' (b64_json ou url)."""
    if not isinstance(item, dict):
        raise ProviderError("Item de imagem inesperado na resposta.")

    b64 = item.get("b64_json")
    if b64:
        # Alguns provedores devolvem data URLs: data:image/png;base64,....
        if "," in b64 and b64.strip().startswith("data:"):
            b64 = b64.split(",", 1)[1]
        try:
            return base64.b64decode(b64)
        except (binascii.Error, ValueError) as exc:
            raise ProviderError(f"base64 inválido na resposta: {exc}")

    img_url = item.get("url")
    if img_url:
        try:
            r = requests.get(img_url, timeout=TIMEOUT)
            r.raise_for_status()
            return r.content
        except requests.RequestException as exc:
            raise ProviderError(f"Falha ao descarregar a imagem de {img_url}: {exc}")

    raise ProviderError(
        "Item de imagem sem 'b64_json' nem 'url':\n" + _resumo(item)
    )


def _resumo(obj, limite: int = 1500) -> str:
    try:
        texto = json.dumps(obj, ensure_ascii=False)[:limite]
    except (TypeError, ValueError):
        texto = str(obj)[:limite]
    return texto


# ====================================================================== #
# Chat de texto (modelos de texto/multimodais via /chat/completions)
# ====================================================================== #
def _chat_post(url,**kwargs):
    import time
    for attempt in range(3):
        try:response=requests.post(url,**kwargs)
        except requests.ConnectTimeout:
            if attempt==2:raise
            time.sleep(.4*(attempt+1));continue
        if response.status_code in (429,502,503,504) and attempt<2:
            response.close();time.sleep(.4*(attempt+1));continue
        return response

def chat(provider: dict, model: dict, messages: list, tools=None, params=None):
    """Chama o endpoint de chat da OpenRouter.

    `messages` segue o formato OpenAI (role/content; content pode ser string
    ou lista de partes text/image_url). `tools` é a lista de ferramentas no
    formato OpenAI (ou None). Devolve um dicionário normalizado:

        {
          "content": "<texto do assistente ou ''>",
          "tool_calls": [ {"id", "name", "arguments": dict} ],
          "raw_message": <mensagem crua do assistente, para reenviar no loop>
        }
    """
    params = params or {}
    api_key = (provider.get("api_key") or "").strip()
    if not api_key:
        raise ProviderError(
            "Este provedor não tem chave de API definida. "
            "Edita o provedor e adiciona a chave."
        )

    base_url = (provider.get("base_url") or "https://openrouter.ai/api/v1").rstrip("/")
    url = f"{base_url}/chat/completions"

    body = {"model": model.get("id", ""), "messages": messages}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    if "temperature" in params:
        body["temperature"] = params["temperature"]
    max_tokens=params.get('max_tokens',(model.get('defaults') or {}).get('max_tokens'))
    if max_tokens:body['max_tokens']=int(max_tokens)
    on_delta = params.get("_on_delta")
    if callable(on_delta):
        return _chat_stream(url, _headers(api_key), body, on_delta, params.get("_cancel"))

    try:
        resp = _chat_post(url, json=body, headers=_headers(api_key), timeout=CHAT_TIMEOUT)
    except requests.Timeout:
        raise ProviderError(f"Tempo esgotado ({CHAT_TIMEOUT}s) ao contactar {url}.")
    except requests.RequestException as exc:
        raise ProviderError(f"Falha de ligação a {url}: {exc}")

    if not resp.ok:
        corpo = resp.text or "(sem corpo)"
        if len(corpo) > 2000:
            corpo = corpo[:2000] + "… (truncado)"
        raise ProviderError(f"Erro HTTP {resp.status_code} de {url}:\n{corpo}")

    try:
        payload = resp.json()
    except ValueError:
        raise ProviderError(
            "A resposta não é JSON válido:\n" + (resp.text or "(vazio)")[:2000]
        )

    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ProviderError("Resposta de chat sem 'choices':\n" + _resumo(payload))

    msg = choices[0].get("message") or {}
    text = _content_to_text(msg.get("content"))
    if choices[0].get('finish_reason') in ('length','content_filter'):
        return {'content':text+'\n[Resposta incompleta.]','tool_calls':[],'raw_message':{'role':'assistant','content':text},'usage':payload.get('usage'),'finish_reason':choices[0].get('finish_reason')}

    tool_calls = []
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function", {})
        args = fn.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args) if args.strip() else {}
            except ValueError:
                raise ProviderError('Argumentos de ferramenta inválidos; nenhuma chamada executada.') from None
        elif not isinstance(args, dict):
            args = {}
        tool_calls.append(
            {"id": tc.get("id", ""), "name": fn.get("name", ""), "arguments": args}
        )

    return {"content": text, "tool_calls": tool_calls, "raw_message": msg, "usage": payload.get("usage"),'finish_reason':choices[0].get('finish_reason')}


def _chat_stream(url, headers, body, on_delta, cancel=None):
    """Chat com streaming SSE; acumula texto e tool_calls fragmentados."""
    body = dict(body)
    body["stream"] = True
    try:
        response = _chat_post(url, json=body, headers=headers, timeout=CHAT_TIMEOUT, stream=True)
    except requests.Timeout:
        raise ProviderError(f"Tempo esgotado ({CHAT_TIMEOUT}s) ao contactar {url}.")
    except requests.RequestException as exc:
        raise ProviderError(f"Falha de ligação a {url}: {exc}")
    with response:
        if not response.ok:
            corpo = response.text or "(sem corpo)"
            raise ProviderError(f"Erro HTTP {response.status_code} de {url}:\n{corpo[:2000]}")
        if "text/event-stream" not in response.headers.get("Content-Type", ""):
            payload = _json(response)
            choices = payload.get("choices") or []
            message = (choices[0].get("message") if choices else {}) or {}
            text = _content_to_text(message.get("content"))
            if choices and choices[0].get('finish_reason') in ('length','content_filter'):
                text+='\n[Resposta incompleta.]';on_delta(text)
                return {'content':text,'tool_calls':[],'raw_message':{'role':'assistant','content':text},'usage':payload.get('usage'),'finish_reason':choices[0].get('finish_reason')}
            if text:
                on_delta(text)
            tool_calls = []
            for tc in message.get("tool_calls") or []:
                fn = tc.get("function") or {}
                args = fn.get("arguments")
                if isinstance(args, str):
                    try:
                        args = json.loads(args) if args.strip() else {}
                    except ValueError:
                        raise ProviderError('Argumentos de ferramenta inválidos; nenhuma chamada executada.') from None
                tool_calls.append({"id": tc.get("id", ""), "name": fn.get("name", ""), "arguments": args if isinstance(args, dict) else {}})
            return {"content": text, "tool_calls": tool_calls, "raw_message": message, "usage": payload.get("usage"),'finish_reason':choices[0].get('finish_reason') if choices else None}
        parts = []
        tools = {}
        usage = None
        cancelled = False
        completed=False;finish_reason=None
        for raw_line in response.iter_lines(chunk_size=1, decode_unicode=False):
            if cancel is not None and cancel.is_set():
                cancelled = True
                break
            if raw_line is None:
                continue
            line = raw_line.decode("utf-8", errors="replace") if isinstance(raw_line, bytes) else raw_line
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                if data == "[DONE]":
                    completed=True
                    break
                continue
            try:
                payload = json.loads(data)
            except ValueError:
                continue
            if payload.get('error'):raise ProviderError('O provedor interrompeu a resposta: '+_resumo(payload['error']))
            if payload.get("usage"):
                usage = payload["usage"]
            choices = payload.get("choices") or []
            if not choices:
                continue
            choice = choices[0] or {}
            if choice.get('finish_reason'):finish_reason=choice['finish_reason']
            delta = choice.get("delta") or {}
            text = delta.get("content")
            if text:
                parts.append(text)
                on_delta(text)
            for tc in delta.get("tool_calls") or []:
                index = tc.get("index", 0)
                entry = tools.setdefault(index, {"id": "", "name": "", "arguments": ""})
                if tc.get("id"):
                    entry["id"] = tc["id"]
                function = tc.get("function") or {}
                if function.get("name"):
                    entry["name"] += function["name"]
                if function.get("arguments"):
                    entry["arguments"] += function["arguments"]
        content = "".join(parts)
        if cancelled:return {'content':content,'tool_calls':[],'raw_message':{'role':'assistant','content':content},'usage':usage,'cancelled':True}
        if not completed and not finish_reason:raise ProviderError('A ligação terminou antes de concluir a resposta; ferramentas não executadas.')
        if finish_reason in ('length','content_filter'):tools={};content+='\n[Resposta incompleta: '+finish_reason+']'
        normalized = []
        raw_calls = []
        for index in sorted(tools):
            entry = tools[index]
            arguments = entry["arguments"]
            try:
                parsed = json.loads(arguments) if arguments.strip() else {}
            except ValueError:
                raise ProviderError('Argumentos de ferramenta incompletos; nenhuma chamada executada.') from None
            if not isinstance(parsed,dict):raise ProviderError('Os argumentos de ferramentas têm de ser objetos JSON.')
            normalized.append({"id": entry["id"], "name": entry["name"], "arguments": parsed})
            raw_calls.append({
                "id": entry["id"],
                "type": "function",
                "function": {"name": entry["name"], "arguments": arguments},
            })
        raw_message = {"role": "assistant", "content": content or None}
        if raw_calls:
            raw_message["tool_calls"] = raw_calls
        return {
            "content": content,
            "tool_calls": normalized,
            "raw_message": raw_message,
            "usage": usage,
            "cancelled": cancelled,
            "finish_reason":finish_reason,
        }


def _content_to_text(content) -> str:
    """Normaliza `content` (string ou lista de partes) para texto simples."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        partes = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                partes.append(part.get("text", ""))
            elif isinstance(part, str):
                partes.append(part)
        return "".join(partes)
    return str(content)


# ====================================================================== #
# Geração de vídeo (assíncrona: submeter -> poll -> descarregar)
# ====================================================================== #
_VIDEO_FIELDS = ("duration", "resolution", "aspect_ratio", "size", "seed")
_TERMINAL = {"completed", "failed", "cancelled", "expired"}


def gerar_video(provider: dict, model: dict, prompt: str, params: dict):
    """Gera vídeo via OpenRouter. Devolve (lista de bytes MP4, metadados)."""
    params = params or {}
    api_key = (provider.get("api_key") or "").strip()
    if not api_key:
        raise ProviderError("Este provedor não tem chave de API definida.")

    base_url = (provider.get("base_url") or "https://openrouter.ai/api/v1").rstrip("/")
    headers = _headers(api_key)

    body = {"model": model.get("id", ""), "prompt": prompt}
    for campo in _VIDEO_FIELDS:
        valor = params.get(campo)
        if valor not in (None, "", 0):
            body[campo] = valor

    # 1) Submeter
    try:
        resp = requests.post(
            f"{base_url}/videos", json=body, headers=headers, timeout=VIDEO_SUBMIT_TIMEOUT
        )
    except requests.RequestException as exc:
        raise ProviderError(f"Falha ao submeter o vídeo: {exc}")
    if not resp.ok:
        raise ProviderError(_http_erro("POST /videos", resp))

    job = _json(resp)
    job_id = job.get("id")
    polling_url = job.get("polling_url") or (f"{base_url}/videos/{job_id}" if job_id else None)
    if polling_url and str(polling_url).startswith("/"):
        polling_url = base_url + str(polling_url)
    status = job.get("status", "pending")
    if not polling_url:
        raise ProviderError("Resposta de submissão sem 'id'/'polling_url':\n" + _resumo(job))
    # Só envia a chave para o próprio provedor, nunca para um host arbitrário.
    poll_headers = headers if urlsplit(polling_url).netloc == urlsplit(base_url).netloc else {}

    # 2) Poll
    waited = 0
    while status not in _TERMINAL:
        time.sleep(VIDEO_POLL_INTERVAL)
        waited += VIDEO_POLL_INTERVAL
        if waited > VIDEO_MAX_WAIT:
            raise ProviderError(
                f"Tempo esgotado ({VIDEO_MAX_WAIT}s) à espera do vídeo (job {job_id})."
            )
        try:
            pr = requests.get(polling_url, headers=poll_headers, timeout=VIDEO_SUBMIT_TIMEOUT)
        except requests.RequestException as exc:
            raise ProviderError(f"Falha ao consultar o estado do vídeo: {exc}")
        if not pr.ok:
            raise ProviderError(_http_erro("GET polling_url", pr))
        job = _json(pr)
        status = job.get("status", status)

    if status != "completed":
        raise ProviderError(
            f"Geração de vídeo terminou com estado '{status}': {job.get('error') or _resumo(job)}"
        )

    # 3) Descarregar o(s) conteúdo(s)
    unsigned = job.get("unsigned_urls") or []
    fallback = not unsigned
    if not unsigned and job_id:
        unsigned = [f"{base_url}/videos/{job_id}/content?index=0"]
    if not unsigned:
        raise ProviderError("Vídeo concluído mas sem URLs de conteúdo:\n" + _resumo(job))

    videos = []
    for u in unsigned:
        try:
            # As URLs assinadas são públicas; a chave só vai no URL de fallback do provedor.
            cr = requests.get(u, headers=headers if fallback else {}, timeout=TIMEOUT)
            cr.raise_for_status()
            videos.append(cr.content)
        except requests.RequestException as exc:
            raise ProviderError(f"Falha ao descarregar o vídeo: {exc}")

    return videos, {"ext": "mp4", "media": "video"}


# ====================================================================== #
# Geração de áudio / fala (TTS) — /audio/speech, bytes crus
# ====================================================================== #
def _openai_voice(model_id: str) -> bool:
    """Só os modelos de voz da OpenAI conhecem as vozes «alloy», «nova», etc."""
    name = (model_id or "").lower()
    return name.startswith("openai/") or ("/" not in name and name.startswith(("tts-", "gpt-")))


_NOT_VOICES = {"voice", "voices", "model", "input", "error", "message", "code", "type", "param", "mp3", "response_format",
               "metadata", "raw", "provider_name", "invalid_request_error", "speed", "instructions", "string", "null", "none", "detail", "details"}


def _vozes_no_erro(resp, rejected: str = "") -> list:
    """Nomes de vozes que o provedor cita ao recusar um pedido («… supported voices: 'Kore', 'Puck'»).
    Serve para tentar outra vez com uma voz que o modelo aceite e para dizer ao utilizador quais existem."""
    texts = []

    def leaves(value):
        if isinstance(value, str):
            if value.lstrip()[:1] in ("{", "["):  # uma mensagem pode trazer outro JSON lá dentro
                try:
                    return leaves(json.loads(value))
                except ValueError:
                    pass
            texts.append(value)
        elif isinstance(value, dict):
            for item in value.values():
                leaves(item)
        elif isinstance(value, list):
            for item in value:
                leaves(item)
    try:
        leaves(resp.json())
    except ValueError:
        leaves(resp.text or "")
    listed, quoted = [], []
    for text in texts:
        quoted += re.findall(r"[\"'`“”‘’]([A-Za-z][A-Za-z0-9_\-]{1,39})[\"'`“”‘’]", text)
        # «Supported voices: a, b» / «must be one of [a, b]»: a lista vai até ao fim da frase
        for match in re.finditer(r"(?i)\b(?:supported|valid|available|allowed|one of|must be)\b[^:\n\[.]{0,60}[:\[]\s*([^\n\]]+)", text):
            listed += [item.strip(" \"'`.[]()“”‘’") for item in re.split(r"[,;|]|\bor\b|\band\b", match.group(1))]
    found = []
    for name in listed or quoted:  # uma lista explícita vale mais do que palavras soltas entre aspas
        if (re.fullmatch(r"[A-Za-z][A-Za-z0-9_\-]{1,39}", name or "") and name.lower() not in _NOT_VOICES
                and name.lower() != (rejected or "").lower() and name not in found):
            found.append(name)
    return found[:40]


def _vozes_do_catalogo(base_url: str, model_id: str) -> list:
    """As vozes que o catálogo público do OpenRouter indica para o modelo (sem chave e sem custo). Lista vazia se
    não for o OpenRouter ou não responder. Rede de reserva para modelos guardados antes de a app conhecer as vozes."""
    if not (urlsplit(base_url).hostname or "").endswith("openrouter.ai"):
        return []
    try:
        resp = requests.get(f"{base_url}/models", params={"output_modalities": "speech"}, timeout=20)
        entries = resp.json().get("data") or [] if resp.ok else []
    except (requests.RequestException, ValueError, AttributeError):
        return []
    for entry in entries:
        if isinstance(entry, dict) and entry.get("id") == model_id:
            return [v for v in (entry.get("supported_voices") or []) if isinstance(v, str) and v.strip()]
    return []


def gerar_audio(provider: dict, model: dict, text: str, params: dict):
    """Gera fala a partir de texto. Devolve (lista de bytes MP3, metadados).

    Cada modelo de voz tem as suas vozes. Sem voz escolhida pelo utilizador usa-se a primeira que o catálogo indica
    para o modelo (``voices``); sem lista, só aos modelos da OpenAI se manda «alloy» e aos outros nenhuma. Se o
    provedor recusar por causa da voz, tenta-se outra vez sem voz ou com a primeira que ele indicar no erro ou que
    o catálogo público indicar (pedidos recusados não se pagam).
    """
    params = params or {}
    api_key = (provider.get("api_key") or "").strip()
    if not api_key:
        raise ProviderError("Este provedor não tem chave de API definida.")

    base_url = (provider.get("base_url") or "https://openrouter.ai/api/v1").rstrip("/")
    chosen = (params.get("voice") or "").strip()
    known = [v for v in (model.get("voices") or []) if isinstance(v, str) and v.strip()]
    voice = chosen or (known[0] if known else "alloy" if _openai_voice(model.get("id", "")) else "")

    def post(name):
        body = {"model": model.get("id", ""), "input": text, "response_format": "mp3"}
        if name:
            body["voice"] = name
        if params.get("instructions"):
            body["instructions"] = params["instructions"]
        if params.get("speed"):
            body["speed"] = params["speed"]
        try:
            return requests.post(f"{base_url}/audio/speech", json=body, headers=_headers(api_key), timeout=AUDIO_TIMEOUT)
        except requests.RequestException as exc:
            raise ProviderError(f"Falha ao gerar áudio: {exc}")

    resp = post(voice)
    used = voice
    if resp.status_code in (400, 404, 422) and "voice" in (resp.text or "").lower():
        first = resp
        options = _vozes_no_erro(first, voice) or [v for v in known if v.lower() != voice.lower()] \
            or [v for v in _vozes_do_catalogo(base_url, model.get("id", "")) if v.lower() != voice.lower()]
        if chosen:  # a voz foi escolhida pelo utilizador: não se troca às escondidas
            raise ProviderError("Este modelo não aceita a voz «%s».%s Muda-a em Configurações → modelo → «Voz (áudio)», ou deixa o campo vazio.\n\n%s" % (
                chosen, " Vozes que ele indica: %s." % ", ".join(options) if options else "", _http_erro("POST /audio/speech", first)))
        for candidate in ([""] if voice else []) + options[:1]:
            if candidate == used:
                continue
            resp, used = post(candidate), candidate
            if resp.ok:
                break
            options = options or _vozes_no_erro(resp, voice)
        else:
            if not resp.ok and options and used != options[0]:
                resp, used = post(options[0]), options[0]
        if not resp.ok:
            raise ProviderError("Este modelo de áudio precisa de uma voz que a app não conhece.%s Escreve o nome de uma em Configurações → modelo → «Voz (áudio)».\n\n%s" % (
                " Vozes que ele indica: %s." % ", ".join(options) if options else "", _http_erro("POST /audio/speech", first)))
    if not resp.ok:
        raise ProviderError(_http_erro("POST /audio/speech", resp))

    data = resp.content
    if not data:
        raise ProviderError("A resposta de áudio veio vazia.")
    return [data], {"ext": "mp3", "media": "audio", "voice": used}


def _http_erro(contexto: str, resp) -> str:
    corpo = resp.text or "(sem corpo)"
    if len(corpo) > 2000:
        corpo = corpo[:2000] + "… (truncado)"
    return f"Erro HTTP {resp.status_code} em {contexto}:\n{corpo}"


def _json(resp):
    try:
        return resp.json()
    except ValueError:
        raise ProviderError("Resposta não é JSON válido:\n" + (resp.text or "(vazio)")[:2000])
