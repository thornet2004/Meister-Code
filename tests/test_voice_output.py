"""Voz local (``voice_output.py``, ``speak_text`` e o modo voz do prompt), sem o Piper verdadeiro.

O processo do Piper é substituído por um que responde como o verdadeiro (uma linha JSON por pedido)
e escreve o WAV pedido. O Piper verdadeiro com a voz portuguesa é ``tests/voice_chat_real_smoke.py``
(fora da suite).
"""
import base64
import io
import json
import queue
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import api
import config
import voice_input
import voice_output
from test_voice_input import FakeWhisper, wav
from voice_output import SpeechError


class FakePiper:
    """Faz de ``subprocess.Popen`` para o processo que fica aberto: lê pedidos da entrada, responde na saída."""

    def __init__(self, ready=True, fail=False, silent=False):
        self.ready, self.fail, self.silent, self.commands, self.texts, self.started, self.killed = ready, fail, silent, [], [], 0, 0
        self.scales = []
        self.stdin, self.stdout = self, self

    def __call__(self, command, **kwargs):
        self.commands.append(command)
        self.kwargs = kwargs
        self.started += 1
        self.alive = True
        self.lines = queue.Queue()
        self.lines.put(json.dumps({'ready': True} if self.ready else {'ready': False, 'error': 'voz estragada'}) + '\n')
        if not self.ready:
            self.lines.put('')
        return self

    # stdin
    def write(self, data):
        job = json.loads(data.decode('utf-8'))
        self.texts.append(job['text'])
        self.scales.append(job.get('scale'))
        if self.silent:
            return
        if self.fail:
            self.lines.put(json.dumps({'ok': False, 'error': 'erro de exemplo'}) + '\n')
            return
        Path(job['out']).write_bytes(wav(0.5, rate=22050))
        self.lines.put('aviso de uma biblioteca, não é JSON\n')
        self.lines.put(json.dumps({'ok': True}) + '\n')

    def flush(self):
        pass

    def close(self):
        pass

    # stdout
    def readline(self):
        return self.lines.get().encode('utf-8')

    def poll(self):
        return None if self.alive else 1

    def kill(self):
        self.killed += 1
        self.alive = False
        self.lines.put('')

    def wait(self, timeout=None):
        return 1


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'Ferramentas'
        self.addCleanup(voice_output.close)

    def tearDown(self):
        voice_output.close()
        self.tmp.cleanup()

    def install(self, voices=('en_US-amy-medium', 'pt_PT-tugao-medium'), core=True):
        (self.root / 'Piper/pacote/piper').mkdir(parents=True, exist_ok=True)
        (self.root / 'Piper/pacote/piper/__init__.py').write_text('', encoding='utf-8')
        (self.root / 'Piper/voices').mkdir(parents=True, exist_ok=True)
        for name in voices:
            (self.root / 'Piper/voices' / (name + '.onnx')).write_bytes(b'onnx')
            (self.root / 'Piper/voices' / (name + '.onnx.json')).write_text('{}', encoding='utf-8')
        if core:
            (self.root / '_Runtime/python/cpython-3.13').mkdir(parents=True, exist_ok=True)
            (self.root / '_Runtime/python/cpython-3.13/python.exe').write_bytes(b'MZ')
            (self.root / '_Runtime/site-packages/onnxruntime').mkdir(parents=True, exist_ok=True)


class VoiceOutputTests(Base):
    def test_status_says_what_is_missing_and_prefers_the_portuguese_voice(self):
        self.assertEqual((voice_output.status(self.root)['ready'], voice_output.status(self.root)['reason']), (False, voice_output.MISSING))
        self.assertIn('Atualizar ferramentas', voice_output.MISSING)
        self.install(voices=(), core=False)
        self.assertEqual(voice_output.status(self.root)['reason'], voice_output.MISSING, 'pacote sem voz não chega')
        (self.root / 'Piper/voices/solta.onnx').write_bytes(b'x')
        self.assertFalse(voice_output.status(self.root)['ready'], 'uma voz sem o seu .onnx.json não serve')
        self.install(core=False)
        names = ['en_US-amy-medium', 'pt_PT-tugao-medium', 'solta']
        self.assertEqual(voice_output.status(self.root), dict(ready=False, reason=voice_output.MISSING_CORE, voice='pt_PT-tugao-medium', voices=names[:2]), 'falta o Python das ferramentas')
        self.install()
        self.assertEqual(voice_output.status(self.root), dict(ready=True, reason='', voice='pt_PT-tugao-medium', voices=names[:2]))
        self.install(voices=('pt_PT-miro-medium',))
        self.assertEqual(voice_output.status(self.root)['voice'], 'pt_PT-miro-medium', 'sem escolha, a voz preferida do utilizador')
        self.assertEqual(voice_output.status(self.root, 'en_US-amy-medium')['voice'], 'en_US-amy-medium', 'a escolha das definições manda')
        self.assertEqual(voice_output.status(self.root, 'apagada')['voice'], 'pt_PT-miro-medium', 'uma voz que já não existe não parte nada')

    def test_only_what_can_be_said_aloud_is_spoken(self):
        said = voice_output.speakable('## Título\n**Olá**, vê [o guia](https://exemplo.pt/guia) ou https://exemplo.pt 😀.\n```python\nprint(1)\n```\n| a | b |\n|---|---|\nFim: `x` é ação.')
        self.assertEqual(said, 'Título Olá, vê o guia ou . a b Fim: x é ação.')
        self.assertEqual(voice_output.speakable('```\nsó código\n```'), '')
        self.assertEqual(voice_output.speakable(None), '')

    def test_speaks_locally_with_one_open_process_and_leaves_nothing_on_disk(self):
        self.install()
        fake = FakePiper()
        before = set(Path(tempfile.gettempdir()).glob('meistercode-fala-*'))
        with patch.object(voice_output.subprocess, 'Popen', side_effect=fake):
            result = voice_output.speak(self.root, 'Olá, **amigo**! Está tudo bem?')
            nothing = voice_output.speak(self.root, '```\ncodigo\n``` 😀')
            again = voice_output.speak(self.root, 'Segunda frase.')
        self.assertEqual(result['text'], 'Olá, amigo! Está tudo bem?')
        self.assertEqual(fake.texts, ['Olá, amigo! Está tudo bem?', 'Segunda frase.'], 'só o texto limpo chega ao programa; o que não tem palavras nem o chama')
        self.assertEqual(fake.started, 1, 'a voz carrega uma vez e o processo fica aberto para as frases seguintes')
        self.assertEqual(base64.b64decode(result['audio'])[:4], b'RIFF')
        self.assertEqual((nothing['audio'], result['voice'], again['text']), ('', 'pt_PT-tugao-medium', 'Segunda frase.'))
        command = fake.commands[0]
        self.assertEqual(command[0], str(self.root / '_Runtime/python/cpython-3.13/python.exe'), 'corre no Python das ferramentas')
        self.assertEqual(command[1:3], ['-I', '-c'], 'isolado do Python e das variáveis do utilizador')
        self.assertEqual(command[4:], [str(self.root / 'Piper/voices/pt_PT-tugao-medium.onnx'), str(self.root / 'Piper/pacote'), str(self.root / '_Runtime/site-packages')])
        compile(command[3], 'worker', 'exec')
        self.assertNotIn('APPDATA', fake.kwargs['env'], 'o programa não recebe o ambiente todo')
        self.assertEqual(set(Path(tempfile.gettempdir()).glob('meistercode-fala-*')), before, 'a pasta temporária é apagada')
        voice_output.close()
        self.assertEqual(fake.killed, 1, 'desligar a conversa fecha o processo')

    def test_deeper_tones_speak_faster_and_play_slower(self):
        self.install()
        fake = FakePiper()
        with patch.object(voice_output.subprocess, 'Popen', side_effect=fake):
            rates = {}
            for tone in ('normal', 'grave', 'profunda', 'inventado'):
                data = base64.b64decode(voice_output.speak(self.root, 'Olá.', tone=tone)['audio'])
                with wave.open(io.BytesIO(data)) as audio:
                    rates[tone] = (audio.getframerate(), audio.getnframes())
        self.assertEqual(rates['normal'], (22050, 11025))
        self.assertEqual(rates['inventado'], rates['normal'], 'um tom desconhecido é o natural')
        self.assertEqual(rates['grave'][1], 11025, 'as amostras são as mesmas; só muda a frequência a que tocam')
        self.assertEqual((rates['grave'][0], rates['profunda'][0]), (18541, 14716))
        self.assertEqual(fake.scales, [None, 0.8409, 0.6674, None], 'o Piper fala mais depressa para a duração ficar igual')

    def test_failures_are_reported_and_still_clean_up(self):
        with self.assertRaises(SpeechError) as missing:
            voice_output.speak(self.root, 'Olá')
        self.assertEqual(str(missing.exception), voice_output.MISSING)
        self.install()
        before = set(Path(tempfile.gettempdir()).glob('meistercode-fala-*'))
        with patch.object(voice_output.subprocess, 'Popen', side_effect=FakePiper(fail=True)):
            with self.assertRaises(SpeechError) as failed:
                voice_output.speak(self.root, 'Olá')
        self.assertIn('erro de exemplo', str(failed.exception))
        voice_output.close()
        with patch.object(voice_output.subprocess, 'Popen', side_effect=FakePiper(ready=False)):
            with self.assertRaises(SpeechError) as broken:
                voice_output.speak(self.root, 'Olá')
        self.assertIn('voz estragada', str(broken.exception))
        hung = FakePiper(silent=True)
        with patch.object(voice_output.subprocess, 'Popen', side_effect=hung), patch.object(voice_output, 'SPEAK_SECONDS', 0.2):
            with self.assertRaises(SpeechError) as slow:
                voice_output.speak(self.root, 'Olá')
        self.assertIn('demorou', str(slow.exception))
        self.assertEqual(hung.killed, 1, 'um processo que não responde é fechado; o pedido seguinte abre outro')
        for bad in (None, 5, 'x' * (voice_output.MAX_CHARS * 4 + 1)):
            with self.assertRaises(SpeechError):
                voice_output.speak(self.root, bad)
        self.assertEqual(set(Path(tempfile.gettempdir()).glob('meistercode-fala-*')), before)

    def test_fast_transcription_only_analyses_the_time_spoken(self):
        (self.root / 'Whisper/app/Release').mkdir(parents=True)
        (self.root / 'Whisper/app/Release/whisper-cli.exe').write_bytes(b'MZ')
        (self.root / 'Whisper/models').mkdir(parents=True)
        (self.root / 'Whisper/models' / voice_input.PREFERRED_MODEL).write_bytes(b'ggml')
        fake = FakeWhisper()
        with patch.object(voice_input.subprocess, 'Popen', side_effect=fake):
            voice_input.transcribe(self.root, wav(2), 'pt')
            voice_input.transcribe(self.root, wav(2), 'pt', fast=True)
            voice_input.transcribe(self.root, wav(26), 'pt', fast=True)
        self.assertNotIn('-ac', fake.commands[0])
        self.assertEqual(fake.commands[1][fake.commands[1].index('-ac') + 1], '300')
        self.assertNotIn('-ac', fake.commands[2], 'numa fala longa não se corta o contexto')


class BridgeTests(Base):
    def setUp(self):
        super().setUp()
        home = Path(self.tmp.name).resolve()
        (home / 'settings').mkdir()
        self.root = home / 'app' / 'Ferramentas'
        self.patches = [patch('config.config_dir', return_value=home / 'settings'), patch('config.application_root', return_value=home / 'app')]
        for item in self.patches:
            item.start()
        config.save_config(config.default_config())
        self.app = api.Api()

    def tearDown(self):
        self.app._lsp.close()
        self.app._mcp.close()
        self.app._folder_tools.close()
        for item in reversed(self.patches):
            item.stop()
        super().tearDown()

    def test_bridge_reports_speech_speaks_and_closes_the_voice_when_the_chat_ends(self):
        status = self.app.get_voice_input()
        self.assertTrue(status['ok'])
        self.assertEqual((status['ready'], status['speech']['ready'], status['speech']['reason']), (False, False, voice_output.MISSING))
        self.assertEqual(self.app.speak_text('Olá'), dict(ok=False, error=voice_output.MISSING))
        self.install()
        fake = FakePiper()
        with patch.object(voice_output.subprocess, 'Popen', side_effect=fake):
            result = self.app.speak_text('Olá, amigo.')
            self.assertTrue(result['ok'], result)
            self.assertEqual(base64.b64decode(result['audio'])[:4], b'RIFF')
            self.assertTrue(self.app.get_voice_input()['speech']['ready'])
            self.assertEqual(fake.killed, 0)
            self.assertFalse(self.app.set_preference('voice_tone', 'esganiçada')['ok'])
            self.assertFalse(self.app.set_preference('voice_name', '..\\fora')['ok'])
            self.assertEqual(self.app.get_voice_input()['speech']['voices'], ['en_US-amy-medium', 'pt_PT-tugao-medium'])
            self.assertTrue(self.app.set_preference('voice_name', 'en_US-amy-medium')['ok'])
            self.assertEqual((self.app.get_voice_input()['speech']['voice'], self.app.speak_text('Olá.')['voice']), ('en_US-amy-medium', 'en_US-amy-medium'))
            self.assertEqual(fake.started, 2, 'mudar de voz abre outro processo com a voz nova')
            self.app.set_preference('voice_name', 'pt_PT-tugao-medium');self.app.speak_text('Olá.')
            self.assertEqual(self.app.set_preference('voice_tone', 'profunda')['preferences']['voice_tone'], 'profunda')
            with wave.open(io.BytesIO(base64.b64decode(self.app.speak_text('Olá.')['audio']))) as audio:
                self.assertEqual(audio.getframerate(), 14716, 'a ponte usa o tom guardado nas definições')
            self.app.set_preference('voice_reply', False)
            self.assertEqual((fake.started, fake.killed), (3, 3), 'terminar a conversa por voz fecha o processo da voz')
            self.assertTrue(voice_output.warm(self.root), 'ligar a conversa carrega logo a voz')
            self.assertEqual(fake.started, 4)
            self.app.set_preference('voice_reply', False)
            self.assertEqual(fake.killed, 4)

    def test_voice_mode_changes_the_prompt_and_is_not_saved(self):
        cfg = config.load_config()
        plain = api._build_model_messages([dict(role='user', text='olá')], self.app._agent_context(cfg), [])[0]['content']
        self.assertNotIn('lida em voz alta', plain)
        self.assertTrue(self.app.set_preference('voice_reply', True)['ok'])
        spoken = api._build_model_messages([dict(role='user', text='olá')], self.app._agent_context(cfg), [])[0]['content']
        self.assertIn('lida em voz alta', spoken)
        self.assertNotIn('voice_reply', config.load_config()['preferences'], 'o modo voz não fica guardado: ao reabrir a app começa desligado')
        self.app.set_preference('voice_reply', False)
        self.assertFalse(self.app._agent_context(cfg)['voice'])


if __name__ == '__main__':
    unittest.main()
