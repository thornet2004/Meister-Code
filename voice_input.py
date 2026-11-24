"""Ditado por voz, local: transforma o áudio do microfone em texto com o whisper.cpp instalado em ``Ferramentas/Whisper``.

O áudio nunca sai do computador: é gravado para um ficheiro temporário, transcrito por um programa
local e o ficheiro é apagado logo a seguir. Não usa rede, provedores nem créditos.

A interface envia um WAV mono de 16 bits a 16 kHz (o formato que o Whisper usa por dentro); aqui
confere-se o formato, recusa-se o silêncio (o Whisper inventa texto quando não ouve nada) e corre-se
o ``whisper-cli.exe`` sem janela, com limite de tempo.
"""
from __future__ import annotations

import array
import contextlib
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path
from urllib.parse import urlsplit

TOOL_KEY = 'Whisper'
PREFERRED_MODEL = 'ggml-small-q5_1.bin'
LANGUAGES = {'pt': 'Português', 'en': 'Inglês', 'es': 'Espanhol', 'fr': 'Francês', 'de': 'Alemão', 'it': 'Italiano', 'auto': 'Detetar'}
SAMPLE_RATE = 16000
MAX_SECONDS = 300
MAX_BYTES = 44 + SAMPLE_RATE * 2 * MAX_SECONDS + 4096
SILENCE_PEAK = 250  # amplitude máxima (em 32767) abaixo da qual se considera que não houve fala
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
BUSY = threading.Lock()
_ENVIRONMENT = ('PATH', 'PATHEXT', 'SYSTEMROOT', 'SYSTEMDRIVE', 'WINDIR', 'COMSPEC', 'TEMP', 'TMP', 'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE')
# o Whisper escreve estas marcas quando só ouve ruído, música ou nada
_MARKS = re.compile(r'\[[^\]\n]{0,40}\]|\([^)\n]{0,40}\)|\*[^*\n]{0,40}\*')
MISSING = 'Falta o Whisper: instala «Whisper (voz para texto, local)» em Ferramentas → ⬇ Atualizar ferramentas (cerca de 200 MB).'

# O whisper-cli precisa das bibliotecas do Visual C++ (VCOMP140.DLL). Num PC que nunca as teve, o Windows mostra
# uma janela «Erro de sistema» e o programa sai com este código (visto a 23/11/2026 num PC acabado de instalar).
DLL_NOT_FOUND = (0xC0000135, 0xC0000135 - (1 << 32))
RUNTIME_MISSING = ('Falta neste PC o «Microsoft Visual C++ Redistributable 2015–2022 (x64)», de que o Whisper precisa '
                   '(ficheiro VCOMP140.DLL). Instala-o a partir de https://aka.ms/vs/17/release/vc_redist.x64.exe e tenta outra vez. '
                   'Com «voz na rig» ligada nas Configurações, a transcrição é feita pela rig e isto não é preciso.')


@contextlib.contextmanager
def quiet_errors():
    """Enquanto dura, um programa lançado que não consiga arrancar (biblioteca em falta) sai com um código de erro
    em vez de abrir uma janela «Erro de sistema» do Windows por cima da app. O programa herda este modo ao nascer."""
    kernel = None
    if os.name == 'nt':
        try:
            import ctypes
            kernel = ctypes.windll.kernel32
            previous = kernel.SetErrorMode(0x8003)  # sem janelas de erro crítico, de falha geral e de ficheiro não encontrado
        except (OSError, AttributeError):
            kernel = None
    try:
        yield
    finally:
        if kernel is not None:
            kernel.SetErrorMode(previous)


class VoiceError(Exception):
    """Falha do ditado com mensagem para o utilizador."""


class ServerDown(VoiceError):
    """O Whisper da rig não respondeu ou recusou o pedido: vale a pena tentar o Whisper deste PC."""


def engine(tools_root) -> dict:
    """Onde estão o programa e o modelo; ``ready`` só com os dois."""
    folder = Path(tools_root).resolve() / TOOL_KEY  # o Whisper corre noutra pasta: caminhos relativos não lhe servem
    programs = sorted((folder / 'app').rglob('whisper-cli.exe')) if (folder / 'app').is_dir() else []
    models = sorted((folder / 'models').glob('ggml-*.bin')) if (folder / 'models').is_dir() else []
    model = next((item for item in models if item.name == PREFERRED_MODEL), models[0] if models else None)
    ready = bool(programs and model)
    return dict(ready=ready, program=str(programs[0]) if programs else '', model=str(model) if model else '',
                model_name=model.name if model else '', reason='' if ready else MISSING)


def status(tools_root) -> dict:
    """O que a interface precisa de saber antes de ligar o microfone. Só lê."""
    found = engine(tools_root)
    return dict(ready=found['ready'], reason=found['reason'], model=found['model_name'], languages=LANGUAGES, max_seconds=MAX_SECONDS, sample_rate=SAMPLE_RATE)


def check_wav(data: bytes) -> float:
    """Confere que é um WAV mono, 16 bits, 16 kHz, com fala audível; devolve a duração em segundos."""
    if not isinstance(data, (bytes, bytearray)) or len(data) < 44:
        raise VoiceError('Não chegou áudio nenhum.')
    if len(data) > MAX_BYTES:
        raise VoiceError('A gravação é demasiado longa (máximo %d minutos).' % (MAX_SECONDS // 60))
    try:
        with wave.open(io.BytesIO(bytes(data))) as audio:
            shape = (audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getcomptype())
            frames = audio.readframes(audio.getnframes())
    except (wave.Error, EOFError, ValueError):
        raise VoiceError('O áudio recebido não é um WAV válido.') from None
    if shape != (1, 2, SAMPLE_RATE, 'NONE'):
        raise VoiceError('O áudio tem de ser WAV mono, 16 bits, 16 kHz.')
    samples = array.array('h')
    samples.frombytes(frames[:len(frames) // 2 * 2])
    if sys.byteorder == 'big':
        samples.byteswap()
    duration = len(samples) / SAMPLE_RATE
    if duration < 0.3:
        raise VoiceError('A gravação é demasiado curta.')
    if duration > MAX_SECONDS + 1:
        raise VoiceError('A gravação é demasiado longa (máximo %d minutos).' % (MAX_SECONDS // 60))
    if max(max(samples), -min(samples)) < SILENCE_PEAK:
        raise VoiceError('Não ouvi nada: confirma que o microfone está ligado e é o escolhido no Windows.')
    return duration


def clean(text: str) -> str:
    """O texto dito, numa linha, sem as marcas de ruído do Whisper."""
    return ' '.join(_MARKS.sub(' ', text or '').split())


# --- Whisper na rig (opcional) -------------------------------------------------------------------------------
# A transcrição numa placa gráfica da rig demora décimos de segundo em vez dos 2–3 s deste PC. O áudio vai pela
# rede local até à rig (servidor `whisper_server.py` do minerador) e não fica guardado em lado nenhum.
REMOTE_TIMEOUT = (3, 30)  # segundos para ligar / para responder


def server_address(value) -> str:
    """O endereço do Whisper da rig, normalizado; vazio = usar o Whisper deste PC."""
    value = (value or '').strip().rstrip('/') if isinstance(value, str) else ''
    if not value:
        return ''
    parsed = urlsplit(value)
    if (len(value) > 200 or parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment):
        raise VoiceError('Endereço do Whisper na rig inválido: usa só http://endereço:porta.')
    return value


def server_key(address: str, providers) -> str:
    """A chave de um provedor configurado que aponte para a mesma máquina (a rig usa uma só chave para tudo)."""
    host = urlsplit(address).hostname
    for provider in providers or []:
        if isinstance(provider, dict) and provider.get('api_key') and urlsplit(str(provider.get('base_url') or '')).hostname == host:
            return str(provider['api_key']).strip()
    return ''


def transcribe_remote(address: str, key: str, data: bytes, language='pt') -> dict:
    """Como ``transcribe``, mas feito pela rig. ``ServerDown`` se ela não responder ou recusar."""
    import requests
    if language not in LANGUAGES:
        raise VoiceError('Língua desconhecida: %r.' % (language,))
    duration = check_wav(data)
    headers = {'Content-Type': 'audio/wav'}
    if key:
        headers['Authorization'] = 'Bearer ' + key
    started = time.monotonic()
    try:
        response = requests.post(address + '/transcrever', params=dict(language=language), data=bytes(data), headers=headers, timeout=REMOTE_TIMEOUT)
    except requests.RequestException:
        raise ServerDown('O Whisper da rig não respondeu.') from None
    if response.status_code == 401:
        raise ServerDown('O Whisper da rig recusou a chave: confirma a chave do provedor da rig.')
    if response.status_code != 200:
        raise ServerDown('O Whisper da rig devolveu o erro %d.' % response.status_code)
    try:
        text = clean(str(response.json().get('text') or ''))
    except (ValueError, AttributeError):
        raise ServerDown('O Whisper da rig respondeu num formato que não conheço.') from None
    if not text:
        raise VoiceError('Não percebi fala nenhuma na gravação.')
    return dict(text=text, duration=round(duration, 1), seconds=round(time.monotonic() - started, 1), model='rig', language=language, remote=True)


def transcribe(tools_root, data: bytes, language='pt', cancel=None, fast=False) -> dict:
    """Transcreve o WAV e devolve ``text``, ``duration`` (do áudio) e ``seconds`` (que demorou).

    ``fast`` (conversa por voz): o Whisper analisa só o tempo que a frase dura em vez dos 30 s de sempre
    (medido a 21/11/2026: 4,3 s de fala em ~3 s em vez de ~9 s).
    """
    if language not in LANGUAGES:
        raise VoiceError('Língua desconhecida: %r.' % (language,))
    found = engine(tools_root)
    if not found['ready']:
        raise VoiceError(found['reason'])
    duration = check_wav(data)
    work = Path(tempfile.mkdtemp(prefix='meistercode-voz-'))
    started = time.monotonic()
    try:
        (work / 'fala.wav').write_bytes(bytes(data))
        threads = max(1, min(8, (os.cpu_count() or 4) - 1))
        command = [found['program'], '-m', found['model'], '-f', str(work / 'fala.wav'), '-l', language, '-nt', '-np', '-otxt', '-of', str(work / 'texto'), '-t', str(threads)]
        if fast and duration < 24:
            command += ['-ac', str(min(1500, int(duration * 50) + 200))]  # 1500 = 30 s de áudio
        environment = {key: value for key, value in os.environ.items() if key.upper() in _ENVIRONMENT}
        limit = time.monotonic() + max(90, duration * 20)
        with (work / 'saida.txt').open('wb') as log:
            with quiet_errors():
                process = subprocess.Popen(command, cwd=str(work), env=environment, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
            try:
                while process.poll() is None:
                    if cancel is not None and cancel.is_set():
                        raise VoiceError('Transcrição cancelada.')
                    if time.monotonic() > limit:
                        raise VoiceError('A transcrição demorou demasiado e foi interrompida.')
                    time.sleep(0.05)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(10)
        result = work / 'texto.txt'
        if process.returncode in DLL_NOT_FOUND:
            raise VoiceError(RUNTIME_MISSING)
        if process.returncode or not result.is_file():
            tail = (work / 'saida.txt').read_bytes()[-400:].decode('utf-8', errors='replace').strip()
            raise VoiceError('O Whisper não conseguiu transcrever (código %s). %s' % (process.returncode, tail))
        text = clean(result.read_text(encoding='utf-8', errors='replace'))
        if not text:
            raise VoiceError('Não percebi fala nenhuma na gravação.')
        return dict(text=text, duration=round(duration, 1), seconds=round(time.monotonic() - started, 1), model=found['model_name'], language=language)
    finally:
        shutil.rmtree(work, ignore_errors=True)  # o áudio não fica no disco
