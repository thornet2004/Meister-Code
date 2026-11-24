"""Ditado por voz (``voice_input.py`` e os dois métodos da ponte), sem o Whisper verdadeiro.

O programa é substituído por um que escreve o ficheiro de texto que o ``whisper-cli`` escreveria.
O ensaio com o Whisper verdadeiro e áudio verdadeiro é ``tests/voice_real_smoke.py`` (fora da suite).
"""
import base64
import io
import math
import struct
import tempfile
import threading
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import voice_input
from voice_input import VoiceError


def wav(seconds=1.0, rate=16000, channels=1, width=2, amplitude=9000):
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as audio:
        audio.setnchannels(channels)
        audio.setsampwidth(width)
        audio.setframerate(rate)
        count = int(seconds * rate)
        if width == 2:
            audio.writeframes(b''.join(struct.pack('<h', int(amplitude * math.sin(i / 8))) * channels for i in range(count)))
        else:
            audio.writeframes(bytes([128]) * count * channels)
    return buffer.getvalue()


class FakeWhisper:
    """Faz de ``subprocess.Popen``: escreve o texto no ficheiro pedido com ``-of`` e termina."""

    def __init__(self, text=' Cria um ficheiro novo.\n [BLANK_AUDIO]\n e corre os testes. (música)\n', code=0, hang=False):
        self.text, self.code, self.hang, self.commands, self.seen_audio, self.killed = text, code, hang, [], [], False

    def __call__(self, command, **kwargs):
        self.commands.append(command)
        self.kwargs = kwargs
        self.seen_audio.append(Path(command[command.index('-f') + 1]).read_bytes())
        if self.code == 0 and not self.hang:
            Path(command[command.index('-of') + 1] + '.txt').write_text(self.text, encoding='utf-8')
        kwargs['stdout'].write(b'whisper: erro de exemplo')
        return self

    def poll(self):
        return None if self.hang and not self.killed else self.code

    @property
    def returncode(self):
        return self.code

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        return self.code


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'Ferramentas'

    def tearDown(self):
        self.tmp.cleanup()

    def install(self, models=('ggml-base.bin', voice_input.PREFERRED_MODEL)):
        (self.root / 'Whisper/app/Release').mkdir(parents=True)
        (self.root / 'Whisper/app/Release/whisper-cli.exe').write_bytes(b'MZ')
        (self.root / 'Whisper/models').mkdir(parents=True)
        for name in models:
            (self.root / 'Whisper/models' / name).write_bytes(b'ggml')


class VoiceInputTests(Base):
    def test_status_says_what_is_missing_and_prefers_the_shipped_model(self):
        self.assertEqual((voice_input.status(self.root)['ready'], voice_input.status(self.root)['reason']), (False, voice_input.MISSING))
        self.assertIn('Atualizar ferramentas', voice_input.MISSING)
        (self.root / 'Whisper/app/Release').mkdir(parents=True)
        (self.root / 'Whisper/app/Release/whisper-cli.exe').write_bytes(b'MZ')
        self.assertFalse(voice_input.status(self.root)['ready'], 'programa sem modelo não chega')
        (self.root / 'Whisper/models').mkdir()
        (self.root / 'Whisper/models/ggml-base.bin').write_bytes(b'x')
        self.assertEqual((voice_input.status(self.root)['ready'], voice_input.status(self.root)['model']), (True, 'ggml-base.bin'), 'serve qualquer modelo que o utilizador lá ponha')
        (self.root / 'Whisper/models' / voice_input.PREFERRED_MODEL).write_bytes(b'x')
        info = voice_input.status(self.root)
        self.assertEqual((info['model'], info['sample_rate'], info['max_seconds']), (voice_input.PREFERRED_MODEL, 16000, 300))
        self.assertIn('pt', info['languages'])
        self.assertFalse(self.root.joinpath('Whisper/downloads').exists())

    def test_only_audible_mono_16_bit_16_khz_wav_is_accepted(self):
        self.assertAlmostEqual(voice_input.check_wav(wav(1.5)), 1.5, places=2)
        bad = dict(vazio=b'', lixo=b'isto nao e um wav' * 10, estereo=wav(channels=2), oito_bits=wav(width=1), outra_frequencia=wav(rate=44100),
                   curto=wav(0.1), silencio=wav(amplitude=0), quase_silencio=wav(amplitude=100), texto='abc', nada=None)
        for label, data in bad.items():
            with self.assertRaises(VoiceError, msg=label):
                voice_input.check_wav(data)
        with patch.object(voice_input, 'MAX_SECONDS', 1), patch.object(voice_input, 'MAX_BYTES', 10 ** 9):
            with self.assertRaises(VoiceError):
                voice_input.check_wav(wav(2.5))
        with patch.object(voice_input, 'MAX_BYTES', 1000):
            with self.assertRaises(VoiceError):
                voice_input.check_wav(wav(1))

    def test_transcribes_locally_cleans_the_text_and_leaves_no_audio_on_disk(self):
        self.install()
        fake, audio = FakeWhisper(), wav(2)
        before = set(Path(tempfile.gettempdir()).glob('meistercode-voz-*'))
        with patch.object(voice_input.subprocess, 'Popen', side_effect=fake):
            result = voice_input.transcribe(self.root, audio, 'pt')
        self.assertEqual(result['text'], 'Cria um ficheiro novo. e corre os testes.', 'sem as marcas de ruído do Whisper')
        self.assertEqual((result['duration'], result['model'], result['language']), (2.0, voice_input.PREFERRED_MODEL, 'pt'))
        command = fake.commands[0]
        self.assertEqual(command[0], str(self.root / 'Whisper/app/Release/whisper-cli.exe'))
        self.assertEqual(command[command.index('-m') + 1], str(self.root / 'Whisper/models' / voice_input.PREFERRED_MODEL))
        self.assertEqual(command[command.index('-l') + 1], 'pt')
        self.assertEqual(fake.seen_audio, [audio])
        self.assertNotIn('APPDATA', fake.kwargs['env'], 'o programa não recebe o ambiente todo')
        self.assertEqual(set(Path(tempfile.gettempdir()).glob('meistercode-voz-*')), before, 'a pasta temporária com o áudio é apagada')

    def test_failures_are_reported_and_still_clean_up(self):
        audio = wav(1)
        with self.assertRaises(VoiceError) as missing:
            voice_input.transcribe(self.root, audio)
        self.assertEqual(str(missing.exception), voice_input.MISSING)
        self.install()
        before = set(Path(tempfile.gettempdir()).glob('meistercode-voz-*'))
        cases = dict(programa_falhou=(FakeWhisper(code=3), 'erro de exemplo'), so_ruido=(FakeWhisper(text=' [BLANK_AUDIO]\n (music)\n'), 'Não percebi'),
                     sem_visual_cpp=(FakeWhisper(code=0xC0000135), 'Visual C++ Redistributable'),  # VCOMP140.DLL em falta
                     sem_visual_cpp_negativo=(FakeWhisper(code=-1073741515), 'vc_redist.x64.exe'))
        for label, (fake, expected) in cases.items():
            with patch.object(voice_input.subprocess, 'Popen', side_effect=fake):
                with self.assertRaises(VoiceError, msg=label) as raised:
                    voice_input.transcribe(self.root, audio)
            self.assertIn(expected, str(raised.exception), label)
        cancel = threading.Event()
        cancel.set()
        hanging = FakeWhisper(hang=True)
        with patch.object(voice_input.subprocess, 'Popen', side_effect=hanging):
            with self.assertRaises(VoiceError):
                voice_input.transcribe(self.root, audio, cancel=cancel)
        self.assertTrue(hanging.killed, 'o programa é morto quando se cancela')
        with patch.object(voice_input.subprocess, 'Popen') as never:
            for label, call in dict(lingua=lambda: voice_input.transcribe(self.root, audio, 'xx; rm'), silencio=lambda: voice_input.transcribe(self.root, wav(amplitude=0))).items():
                with self.assertRaises(VoiceError, msg=label):
                    call()
            never.assert_not_called()
        self.assertEqual(set(Path(tempfile.gettempdir()).glob('meistercode-voz-*')), before)


class FakeReply:
    def __init__(self, status=200, data=None):
        self.status_code, self.data = status, data

    def json(self):
        if self.data is None:
            raise ValueError('sem JSON')
        return self.data


class RemoteTests(unittest.TestCase):
    def test_address_is_normalised_and_anything_odd_is_refused(self):
        self.assertEqual(voice_input.server_address(' http://192.168.0.10:8089/ '), 'http://192.168.0.10:8089')
        self.assertEqual((voice_input.server_address(''), voice_input.server_address(None)), ('', ''))
        for bad in ('192.168.0.10:8089', 'ftp://rig', 'http://user:pass@rig:1', 'http://rig:1/v1', 'http://rig:1?x=1', 'http://' + 'a' * 300):
            with self.assertRaises(VoiceError, msg=bad):
                voice_input.server_address(bad)

    def test_key_comes_from_the_provider_on_the_same_machine(self):
        providers = [dict(base_url='https://openrouter.ai/api/v1', api_key='sk-nuvem'), dict(base_url='http://192.168.0.10:8081/v1', api_key=' chave-rig '), 'lixo']
        self.assertEqual(voice_input.server_key('http://192.168.0.10:8089', providers), 'chave-rig')
        self.assertEqual(voice_input.server_key('http://192.168.1.50:8089', providers), '')

    def test_remote_transcription_sends_the_wav_and_tells_down_from_silence(self):
        import requests
        calls = []

        def post(url, **kwargs):
            calls.append((url, kwargs))
            return replies.pop(0)
        replies = [FakeReply(data=dict(text=' [Música] Olá, rig. ')), FakeReply(401), FakeReply(500), FakeReply(200), FakeReply(data=dict(text='  '))]
        with patch.object(requests, 'post', side_effect=post):
            result = voice_input.transcribe_remote('http://rig:8089', 'segredo', wav(1), 'pt')
            self.assertEqual((result['text'], result['remote'], result['duration']), ('Olá, rig.', True, 1.0))
            for _ in range(3):
                with self.assertRaises(voice_input.ServerDown):
                    voice_input.transcribe_remote('http://rig:8089', 'segredo', wav(1))
            with self.assertRaises(VoiceError) as silence:
                voice_input.transcribe_remote('http://rig:8089', '', wav(1))
            self.assertNotIsInstance(silence.exception, voice_input.ServerDown, 'silêncio não é avaria: não se repete no PC')
        url, sent = calls[0]
        self.assertEqual((url, sent['params'], sent['headers']['Authorization'], sent['data'][:4]), ('http://rig:8089/transcrever', dict(language='pt'), 'Bearer segredo', b'RIFF'))
        self.assertNotIn('Authorization', calls[-1][1]['headers'], 'sem chave não se manda cabeçalho')
        with patch.object(requests, 'post', side_effect=requests.ConnectionError('fora')):
            with self.assertRaises(voice_input.ServerDown):
                voice_input.transcribe_remote('http://rig:8089', '', wav(1))
        with self.assertRaises(VoiceError):
            voice_input.transcribe_remote('http://rig:8089', '', wav(0.1))  # nem chega a sair do PC


class BridgeTests(Base):
    def setUp(self):
        super().setUp()
        import api
        import config
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

    def test_bridge_reports_the_missing_engine_and_transcribes_when_installed(self):
        status = self.app.get_voice_input()
        self.assertEqual((status['ok'], status['ready'], status['reason']), (True, False, voice_input.MISSING))
        audio = base64.b64encode(wav(1)).decode()
        self.assertEqual(self.app.transcribe_voice(audio)['error'], voice_input.MISSING)
        self.install()
        self.assertTrue(self.app.get_voice_input()['ready'])
        fake = FakeWhisper(text=' Olá, mundo.\n')
        with patch.object(voice_input.subprocess, 'Popen', side_effect=fake):
            result = self.app.transcribe_voice(audio, 'auto')
            self.assertEqual((result['ok'], result['text'], result['language']), (True, 'Olá, mundo.', 'auto'))
            for bad in ('', None, 5, 'não é base64!!', 'A' * (voice_input.MAX_BYTES * 2)):
                self.assertFalse(self.app.transcribe_voice(bad)['ok'], repr(bad)[:30])
            self.assertFalse(self.app.transcribe_voice(audio, 'klingon')['ok'])
            self.assertTrue(voice_input.BUSY.acquire(blocking=False))
            try:
                self.assertIn('em curso', self.app.transcribe_voice(audio)['error'])
            finally:
                voice_input.BUSY.release()
        self.assertEqual(len(fake.commands), 1, 'os pedidos inválidos nem chegam ao programa')

    def test_bridge_uses_the_rig_and_falls_back_to_this_pc(self):
        import config
        import requests
        audio = base64.b64encode(wav(1)).decode()
        self.assertFalse(self.app.set_preference('voice_server', 'http://rig:8089/v1')['ok'])
        self.assertEqual(self.app.set_preference('voice_server', 'http://192.168.0.10:8089/')['preferences']['voice_server'], 'http://192.168.0.10:8089')
        cfg = config.load_config()
        cfg['providers'].append(dict(id='rig', kind='openai-compatible', base_url='http://192.168.0.10:8081/v1', api_key='chave-rig', models=[]))
        config.save_config(cfg)
        status = self.app.get_voice_input()
        self.assertEqual((status['ready'], status['server']), (True, 'http://192.168.0.10:8089'), 'a rig basta, mesmo sem Whisper neste PC')
        seen = []

        def post(url, **kwargs):
            seen.append(kwargs['headers'].get('Authorization'))
            return FakeReply(data=dict(text='Olá da rig.'))
        with patch.object(requests, 'post', side_effect=post):
            result = self.app.transcribe_voice(audio)
        self.assertEqual((result['ok'], result['text'], result['remote'], seen), (True, 'Olá da rig.', True, ['Bearer chave-rig']))
        self.assertNotIn('chave-rig', repr(result) + repr(status), 'a chave não vai para a interface')
        with patch.object(requests, 'post', side_effect=requests.ConnectionError('fora')):
            self.assertIn('não respondeu', self.app.transcribe_voice(audio)['error'], 'sem Whisper local não há recurso')
            self.install()
            with patch.object(voice_input.subprocess, 'Popen', side_effect=FakeWhisper(text='Olá do PC.')):
                result = self.app.transcribe_voice(audio)
        self.assertEqual((result['ok'], result['text']), (True, 'Olá do PC.'))
        self.assertIn('não respondeu', result['fallback'])
        self.assertEqual(self.app.set_preference('voice_server', '')['preferences']['voice_server'], '')
        self.assertEqual(self.app.get_voice_input()['server'], '')


if __name__ == '__main__':
    unittest.main()
