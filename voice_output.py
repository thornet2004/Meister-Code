"""Voz da app, local: transforma texto em fala com o Piper instalado em ``Ferramentas/Piper``.

É a metade que fala da conversa por voz (a que ouve é ``voice_input.py``). O texto não sai do
computador. O Piper é um pacote Python (``piper-tts``): corre num processo à parte, com o Python
próprio das ferramentas, que fica aberto enquanto a conversa por voz está ligada para não carregar
a voz a cada frase. Cada frase vira um WAV numa pasta temporária, que é lido e apagado. Não usa
rede, provedores nem créditos.

A interface manda uma frase de cada vez (para a fala começar antes de a resposta acabar); aqui
limpa-se o que não se diz em voz alta (código, endereços, marcas de Markdown, emojis).
"""
from __future__ import annotations

import base64
import io
import json
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
import unicodedata
import wave
from pathlib import Path

TOOL_KEY = 'Piper'
MAX_CHARS = 700          # por pedido: uma ou duas frases
START_SECONDS = 90       # carregar o Python, o onnxruntime e a voz
SPEAK_SECONDS = 60
# Tom da voz: quantos meios-tons abaixo do natural. Só há uma voz de Portugal no Piper; para a tornar
# mais grave gera-se a fala mais rápida e toca-se mais devagar (a duração fica igual, o tom desce).
TONES = {'normal': 0, 'grave': 3, 'muito_grave': 5, 'profunda': 7}
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
BUSY = threading.Lock()  # uma síntese de cada vez
_ENVIRONMENT = ('PATH', 'PATHEXT', 'SYSTEMROOT', 'SYSTEMDRIVE', 'WINDIR', 'COMSPEC', 'TEMP', 'TMP', 'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE')
MISSING = 'Falta a voz: instala «Piper (texto para voz, local)» em Ferramentas → ⬇ Atualizar ferramentas (cerca de 175 MB).'
PREFERRED = ('pt_PT-miro', 'pt_PT', 'pt')  # sem escolha do utilizador: a voz que ele preferiu (22/11/2026), depois outra de Portugal
MISSING_CORE = 'A voz precisa do núcleo das ferramentas (Python e pacotes partilhados): instala-o em Ferramentas → ⬇ Atualizar ferramentas.'
_FENCE = re.compile(r'```.*?(```|$)', re.S)
_LINK = re.compile(r'!?\[([^\]\n]*)\]\([^)\n]*\)')
_URL = re.compile(r'\b(?:https?://|www\.)\S+')
_TABLE_RULE = re.compile(r'^[\s|:\-]+$', re.M)
# Corre no Python das ferramentas (não no da app): carrega a voz uma vez e atende um pedido JSON por linha.
WORKER = r'''
import json, sys, wave
sys.path[:0] = [sys.argv[2], sys.argv[3]]
def say(reply):
    sys.stdout.write(json.dumps(reply) + "\n"); sys.stdout.flush()
try:
    from piper import PiperVoice, SynthesisConfig
    voice = PiperVoice.load(sys.argv[1])
except Exception as error:
    say({"ready": False, "error": (type(error).__name__ + ": " + str(error))[:400]}); raise SystemExit(1)
say({"ready": True})
for line in sys.stdin.buffer:
    try:
        job = json.loads(line.decode("utf-8"))
        with wave.open(job["out"], "wb") as target:
            voice.synthesize_wav(job["text"], target, syn_config=SynthesisConfig(length_scale=job.get("scale") or None))
        say({"ok": True})
    except Exception as error:
        say({"ok": False, "error": (type(error).__name__ + ": " + str(error))[:400]})
'''
_worker = None  # dict(process, lines, key) do processo aberto


class SpeechError(Exception):
    """Falha da voz com mensagem para o utilizador."""


def engine(tools_root, wanted='') -> dict:
    """Onde estão o pacote, a voz e o Python das ferramentas; ``ready`` só com tudo.

    ``wanted`` é a voz escolhida nas definições (nome do ficheiro sem ``.onnx``); se não existir, vale a ordem de ``PREFERRED``.
    """
    root = Path(tools_root).resolve()  # o processo da voz corre noutra pasta: caminhos relativos não lhe servem
    folder = root / TOOL_KEY
    package = folder / 'pacote'
    voices = [item for item in sorted((folder / 'voices').glob('*.onnx')) if Path(str(item) + '.json').is_file()] if (folder / 'voices').is_dir() else []
    voice = next((item for item in voices if wanted and item.stem == wanted), None)
    for prefix in PREFERRED:
        voice = voice or next((item for item in voices if item.name.startswith(prefix)), None)
    voice = voice or (voices[0] if voices else None)
    pythons = sorted((root / '_Runtime' / 'python').glob('*/python.exe')) if (root / '_Runtime' / 'python').is_dir() else []
    shared = root / '_Runtime' / 'site-packages'
    installed = (package / 'piper' / '__init__.py').is_file() and voice is not None
    core = bool(pythons) and (shared / 'onnxruntime').is_dir()
    ready = installed and core
    return dict(ready=ready, python=str(pythons[0]) if pythons else '', package=str(package), shared=str(shared), voice=str(voice) if voice else '',
                voice_name=voice.stem if voice else '', voices=[item.stem for item in voices], reason='' if ready else MISSING if not installed else MISSING_CORE)


def status(tools_root, wanted='') -> dict:
    found = engine(tools_root, wanted)
    return dict(ready=found['ready'], reason=found['reason'], voice=found['voice_name'], voices=found['voices'])


def speakable(text: str) -> str:
    """O que se diz em voz alta: sem blocos de código, endereços, marcas de Markdown nem emojis."""
    text = _FENCE.sub(' ', text or '')
    text = _LINK.sub(r'\1', text)
    text = _URL.sub(' ', text)
    text = _TABLE_RULE.sub(' ', text)
    text = re.sub(r'[`*_~]+', '', text)
    text = re.sub(r'[#>|]+', ' ', text)
    text = ''.join(char for char in text if unicodedata.category(char) not in ('So', 'Sk', 'Cs', 'Co', 'Cn', 'Cf', 'Mn') or char in '̧̃́̀̂')
    return ' '.join(unicodedata.normalize('NFC', text).split())


def close() -> None:
    """Fecha o processo da voz (ao desligar a conversa por voz ou ao sair)."""
    global _worker
    current, _worker = _worker, None
    if current is None:
        return
    process = current['process']
    try:
        process.stdin.close()
    except OSError:
        pass
    if process.poll() is None:
        process.kill()
        try:
            process.wait(10)
        except Exception:  # noqa: BLE001
            pass


def _answer(current, seconds, cancel=None) -> dict:
    """A próxima linha JSON do processo; falha se ele morrer, demorar ou o pedido for cancelado."""
    limit = time.monotonic() + seconds
    while True:
        try:
            line = current['lines'].get(timeout=0.05)
        except queue.Empty:
            if cancel is not None and cancel.is_set():
                raise SpeechError('Fala cancelada.') from None
            if time.monotonic() > limit:
                raise SpeechError('A voz demorou demasiado e foi interrompida.') from None
            continue
        if line is None:
            raise SpeechError('O Piper fechou sem responder (código %s).' % (current['process'].poll(),))
        try:
            reply = json.loads(line)
        except ValueError:
            continue  # avisos das bibliotecas na saída
        if isinstance(reply, dict):
            return reply


def _start(found) -> dict:
    global _worker
    key = (found['python'], found['package'], found['voice'])
    if _worker is not None and _worker['key'] == key and _worker['process'].poll() is None:
        return _worker
    close()
    environment = {name: value for name, value in os.environ.items() if name.upper() in _ENVIRONMENT}
    environment['PYTHONUTF8'] = '1'
    command = [found['python'], '-I', '-c', WORKER, found['voice'], found['package'], found['shared']]
    process = subprocess.Popen(command, cwd=found['package'], env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
    lines = queue.Queue()

    def read():
        try:
            for raw in iter(process.stdout.readline, b''):
                lines.put(raw.decode('utf-8', errors='replace'))
        finally:
            lines.put(None)

    threading.Thread(target=read, name='voz-piper', daemon=True).start()
    _worker = dict(process=process, lines=lines, key=key)
    try:
        ready = _answer(_worker, START_SECONDS)
    except SpeechError:
        close()
        raise
    if not ready.get('ready'):
        close()
        raise SpeechError('O Piper não conseguiu carregar a voz. %s' % ready.get('error', ''))
    return _worker


def _lower(data: bytes, factor: float) -> bytes:
    """O mesmo som declarado a uma frequência mais baixa: toca mais devagar e mais grave."""
    with wave.open(io.BytesIO(data)) as source:
        shape, frames = source.getparams(), source.readframes(source.getnframes())
    target = io.BytesIO()
    with wave.open(target, 'wb') as audio:
        audio.setnchannels(shape.nchannels)
        audio.setsampwidth(shape.sampwidth)
        audio.setframerate(max(8000, int(shape.framerate * factor)))
        audio.writeframes(frames)
    return target.getvalue()


def warm(tools_root, wanted='') -> bool:
    """Abre já o processo e carrega a voz (uns 4 s), para a primeira resposta não esperar por isso."""
    found = engine(tools_root, wanted)
    if not found['ready']:
        return False
    with BUSY:
        try:
            _start(found)
            return True
        except SpeechError:
            return False


def speak(tools_root, text, cancel=None, tone='normal', wanted='') -> dict:
    """Sintetiza ``text`` e devolve ``audio`` (WAV em base64; vazio se não houver nada para dizer)."""
    if not isinstance(text, str):
        raise SpeechError('Texto em falta.')
    if len(text) > MAX_CHARS * 4:
        raise SpeechError('Texto demasiado longo para dizer de uma vez.')
    factor = 2 ** (-TONES.get(tone, 0) / 12)
    found = engine(tools_root, wanted)
    if not found['ready']:
        raise SpeechError(found['reason'])
    said = speakable(text)[:MAX_CHARS]
    if not re.search(r'\w', said):
        return dict(audio='', text='', seconds=0.0, voice=found['voice_name'])
    work = Path(tempfile.mkdtemp(prefix='meistercode-fala-'))
    started = time.monotonic()
    try:
        target = work / 'fala.wav'
        current = _start(found)
        try:
            current['process'].stdin.write((json.dumps(dict(text=said, out=str(target), scale=round(factor, 4) if factor < 1 else None)) + '\n').encode('utf-8'))
            current['process'].stdin.flush()
            reply = _answer(current, SPEAK_SECONDS, cancel)
        except (OSError, SpeechError) as error:
            close()  # o processo ficou num estado desconhecido: o próximo pedido abre outro
            raise SpeechError(str(error)) from None
        if not reply.get('ok') or not target.is_file() or target.stat().st_size <= 44:
            raise SpeechError('O Piper não conseguiu gerar a fala. %s' % reply.get('error', ''))
        data = target.read_bytes()
        if factor < 1:
            data = _lower(data, factor)
        return dict(audio=base64.b64encode(data).decode('ascii'), text=said, seconds=round(time.monotonic() - started, 2), voice=found['voice_name'])
    finally:
        shutil.rmtree(work, ignore_errors=True)
