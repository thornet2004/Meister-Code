"""Ensaio REAL do ditado por voz (fora da suite): o Whisper verdadeiro a transcrever áudio verdadeiro.

Precisa de uma pasta ``Ferramentas`` com o Whisper instalado (``python tool_installer.py --root <pasta> instalar Whisper``).
O áudio é fala sintetizada pelo Windows (System.Speech), na voz que estiver instalada; não usa o microfone.

    python tests/voice_real_smoke.py <pasta Ferramentas>
"""
import base64
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PHRASES = {'pt': ('Cria um ficheiro novo chamado teste e corre a suite de testes do projeto.', ('ficheiro', 'teste', 'projeto')),
           'en': ('Create a new file called test and run the project test suite.', ('file', 'test', 'project'))}
SCRIPT = r'''
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$voice = $s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -like '%s*' } | Select-Object -First 1
if (-not $voice) { exit 3 }
$s.SelectVoice($voice.VoiceInfo.Name)
$format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000,[System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,[System.Speech.AudioFormat.AudioChannel]::Mono)
$s.SetOutputToWaveFile('%s', $format)
$s.Speak('%s')
$s.Dispose()
'''


def speak(language, text, target):
    done = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', SCRIPT % (language, target, text)], capture_output=True, timeout=120)
    return done.returncode == 0 and target.is_file()


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    tools = Path(sys.argv[1]).resolve()
    import api
    import config
    import folder_tools
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp).resolve()
        (home / 'settings').mkdir()
        with patch('config.config_dir', return_value=home / 'settings'), patch('config.application_root', return_value=home / 'app'), patch.object(folder_tools, 'root', return_value=tools):
            config.save_config(config.default_config())
            app = api.Api()
            try:
                status = app.get_voice_input()
                assert status['ok'] and status['ready'], status
                print('motor pronto, modelo', status['model'])
                tested = 0
                for language, (text, expected) in PHRASES.items():
                    target = home / ('fala-%s.wav' % language)
                    if not speak(language, text, target):
                        print('sem voz do Windows para «%s»: não ensaiado' % language)
                        continue
                    result = app.transcribe_voice(base64.b64encode(target.read_bytes()).decode(), language)
                    assert result['ok'], result
                    heard = result['text'].lower()
                    print('%s: «%s» -> «%s» (%s s de áudio em %s s)' % (language, text, result['text'], result['duration'], result['seconds']))
                    assert all(word in heard for word in expected), (expected, heard)
                    tested += 1
                assert tested, 'nenhuma voz do Windows disponível para sintetizar o áudio'
                silent = app.transcribe_voice(base64.b64encode(_silence()).decode(), 'pt')
                assert not silent['ok'] and 'Não ouvi nada' in silent['error'], silent
                print('silêncio: recusado sem chamar o Whisper')
                assert not list(Path(tempfile.gettempdir()).glob('meistercode-voz-*')), 'ficou áudio temporário no disco'
            finally:
                app._lsp.close()
                app._mcp.close()
                app._folder_tools.close()
    print('PASS: ditado local com o Whisper verdadeiro (%d língua(s))' % tested)
    return 0


def _silence():
    import io
    import wave
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b'\x00\x00' * 16000)
    return buffer.getvalue()


if __name__ == '__main__':
    sys.exit(main())
