"""Geração de áudio: cada modelo tem as suas vozes; a app não pode mandar «alloy» a todos."""

import json
import unittest
from unittest.mock import patch

import requests

from providers import openrouter
from providers.base import ProviderError


class Reply:
    def __init__(self, status=200, content=b'mp3', data=None, text=None):
        self.status_code, self.content, self.data = status, content, data
        self.text = text if text is not None else (json.dumps(data) if data is not None else '')
        self.ok = status < 400

    def json(self):
        if self.data is None:
            raise ValueError('sem JSON')
        return self.data


PROVIDER = dict(api_key='sk-teste', base_url='https://exemplo.invalid/api/v1')


def run(model_id, replies, params=None):
    sent = []

    def post(url, json=None, **kwargs):
        sent.append(json.get('voice'))
        return replies.pop(0)
    with patch.object(requests, 'post', side_effect=post):
        try:
            result = openrouter.gerar_audio(PROVIDER, dict(id=model_id), 'Olá.', params or {})
        except ProviderError as error:
            return sent, error
    return sent, result


class AudioVoiceTests(unittest.TestCase):
    def test_only_openai_models_get_alloy_by_default(self):
        sent, result = run('openai/gpt-4o-mini-tts', [Reply()])
        self.assertEqual((sent, result[1]['voice']), (['alloy'], 'alloy'))
        sent, result = run('tts-1', [Reply()])
        self.assertEqual(sent, ['alloy'])
        sent, result = run('elevenlabs/eleven-v3', [Reply()])
        self.assertEqual((sent, result[0], result[1]['voice']), ([None], [b'mp3'], ''), 'aos outros não se manda voz: usam a deles')
        sent, result = run('google/gemini-3.8-flash-tts', [Reply()], dict(voice=' Kore '))
        self.assertEqual(sent, ['Kore'], 'a voz escolhida pelo utilizador vai sempre')

    def test_a_model_that_demands_a_voice_gets_one_it_names(self):
        refused = Reply(400, data=dict(error=dict(message="voice is required. Supported voices: 'Kore', 'Puck', 'Zephyr'", code=400)))
        sent, result = run('google/gemini-3.8-flash-tts', [refused, Reply()])
        self.assertEqual((sent, result[1]['voice']), ([None, 'Kore'], 'Kore'))

    def test_alloy_refused_is_retried_without_voice_then_with_a_named_one(self):
        refused = Reply(400, data=dict(error=dict(message='Provider returned error', metadata=dict(raw='{"detail":"Invalid voice \\"alloy\\". Must be one of: aria, roger, sarah"}'))))
        sent, result = run('openai/gpt-audio-mini', [refused, Reply()])
        self.assertEqual((sent, result[1]['voice']), (['alloy', None], ''), 'primeiro sem voz')
        refused2 = Reply(400, data=dict(error=dict(message='voice is required')))
        sent, result = run('openai/gpt-audio-mini', [refused, refused2, Reply()])
        self.assertEqual((sent, result[1]['voice']), (['alloy', None, 'aria'], 'aria'), 'depois com a primeira que o provedor indicou')

    def test_failures_tell_the_user_what_to_do(self):
        refused = Reply(400, data=dict(error=dict(message="Unknown voice 'Maria'. Available voices: Kore, Puck")))
        sent, error = run('google/gemini-3.8-flash-tts', [refused], dict(voice='Maria'))
        self.assertEqual(sent, ['Maria'], 'a voz escolhida pelo utilizador não é trocada às escondidas')
        self.assertIn('não aceita a voz «Maria»', str(error))
        self.assertIn('Kore, Puck', str(error))
        vague = Reply(400, text='voice not supported')
        sent, error = run('fish-audio/s1', [Reply(400, text='voice missing'), ], None)
        self.assertEqual(sent, [None])
        self.assertIn('precisa de uma voz', str(error))
        sent, error = run('openai/tts-1', [vague, Reply(400, text='voice missing')])
        self.assertEqual(sent, ['alloy', None])
        self.assertIn('Voz (áudio)', str(error))
        sent, error = run('elevenlabs/eleven-v3', [Reply(402, text='Insufficient credits')])
        self.assertEqual(sent, [None], 'um erro que não é da voz não se repete')
        self.assertIn('402', str(error))

    def test_the_catalogue_voices_of_the_model_are_used(self):
        """O ElevenLabs pelo OpenRouter responde «An explicit voice is required for this TTS provider.» e não diz quais (visto a 23/11/2026)."""
        from providers import catalog
        entry = catalog.normalize(dict(id='elevenlabs/eleven-v4-turbo', name='Eleven v4 Turbo', architecture=dict(output_modalities=['speech']),
                                       endpoints=['/api/v1/audio/speech'], supported_voices=['george', 'sarah', '', 7]), 'openrouter')
        self.assertEqual(entry['voices'], ['george', 'sarah'])
        provider = dict(models=[dict(id='elevenlabs/eleven-v4-turbo', type='audio', name='x', defaults=dict(voice='sarah'), catalog_managed=True)])
        catalog.merge(provider, [entry])
        stored = provider['models'][0]
        self.assertEqual((stored['voices'], stored['defaults']), (['george', 'sarah'], dict(voice='sarah')), 'as vozes entram, a escolha do utilizador fica')

        sent = []
        with patch.object(requests, 'post', side_effect=lambda url, json=None, **kw: sent.append(json.get('voice')) or Reply()):
            result = openrouter.gerar_audio(PROVIDER, dict(id='elevenlabs/eleven-v4-turbo', voices=['george', 'sarah']), 'Ho, ho, ho!', {})
        self.assertEqual((sent, result[1]['voice']), (['george'], 'george'), 'sem voz escolhida vai a primeira do modelo')

        # modelo guardado antes de a app conhecer as vozes: pergunta-se ao catálogo público (só no OpenRouter)
        required = Reply(400, data=dict(error=dict(message='An explicit voice is required for this TTS provider.', code=400)))
        replies, sent, asked = [required, Reply()], [], []

        def get(url, **kwargs):
            asked.append((url, kwargs.get('headers')))
            return Reply(data=dict(data=[dict(id='outro', supported_voices=['x']), dict(id='elevenlabs/eleven-v4-turbo', supported_voices=['george', 'sarah'])]))
        with patch.object(requests, 'post', side_effect=lambda url, json=None, **kw: sent.append(json.get('voice')) or replies.pop(0)), patch.object(requests, 'get', side_effect=get):
            result = openrouter.gerar_audio(dict(api_key='sk-teste'), dict(id='elevenlabs/eleven-v4-turbo'), 'Ho, ho, ho!', {})
        self.assertEqual((sent, result[1]['voice']), ([None, 'george'], 'george'))
        self.assertEqual(asked, [('https://openrouter.ai/api/v1/models', None)], 'o catálogo é público: a chave não vai')
        with patch.object(requests, 'get', side_effect=AssertionError('não se pergunta a outros servidores')):
            self.assertEqual(openrouter._vozes_do_catalogo('https://exemplo.invalid/api/v1', 'x'), [])

    def test_voice_names_are_read_from_the_error_and_json_keys_are_not_voices(self):
        reply = Reply(400, data=dict(error=dict(message="Invalid value: 'alloy'. Supported values are: 'af_heart', 'af-bella' and 'am_adam'.", type='invalid_request_error', param='voice')))
        self.assertEqual(openrouter._vozes_no_erro(reply, 'alloy'), ['af_heart', 'af-bella', 'am_adam'])
        self.assertEqual(openrouter._vozes_no_erro(Reply(400, text='erro qualquer'), 'alloy'), [])


class VoiceChoiceBridgeTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        import api
        import config
        self.tmp = tempfile.TemporaryDirectory()
        home = Path(self.tmp.name).resolve()
        (home / 'settings').mkdir()
        self.patches = [patch('config.config_dir', return_value=home / 'settings'), patch('config.application_root', return_value=home / 'app')]
        for item in self.patches:
            item.start()
        cfg = config.default_config()
        cfg['providers'].append(dict(id='router', name='OpenRouter', kind='openrouter', api_key='sk-nuvem', models=[
            dict(id='eleven', name='Eleven', type='audio', defaults={'speed': 1.1}, voices=['george', 'Sarah']),
            dict(id='fish', name='Fish', type='audio'), dict(id='chat', name='Chat', type='chat', voices=['x'])]))
        config.save_config(cfg)
        self.config = config
        self.app = api.Api()

    def tearDown(self):
        self.app._lsp.close()
        self.app._mcp.close()
        self.app._folder_tools.close()
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()

    def model(self, state, model_id):
        return next(m for p in state['providers'] for m in p['models'] if m['id'] == model_id)

    def test_the_voice_of_an_audio_model_is_chosen_and_cleared(self):
        state = self.app.get_state()
        self.assertEqual(self.model(state, 'eleven')['voices'], ['george', 'Sarah'], 'a interface recebe as vozes do modelo de áudio')
        self.assertNotIn('voices', self.model(state, 'fish'))
        self.assertNotIn('voices', self.model(state, 'chat'), 'só os modelos de áudio levam vozes')
        state = self.app.set_model_voice('router', 'eleven', ' sarah ')
        self.assertEqual(self.model(state, 'eleven')['defaults'], {'speed': 1.1, 'voice': 'Sarah'}, 'fica com a grafia do catálogo e os outros valores não se perdem')
        self.assertFalse(self.app.set_model_voice('router', 'eleven', 'maria')['ok'], 'voz que o modelo não tem')
        state = self.app.set_model_voice('router', 'eleven', '')
        self.assertEqual(self.model(state, 'eleven')['defaults'], {'speed': 1.1})
        state = self.app.set_model_voice('router', 'fish', 'qualquer-nome')
        self.assertEqual(self.model(state, 'fish')['defaults'], {'voice': 'qualquer-nome'}, 'sem lista conhecida aceita-se o que o utilizador escrever')
        for provider, model, voice in (('router', 'chat', 'x'), ('router', 'nada', 'x'), ('outro', 'eleven', 'x'), ('router', 'fish', 'v' * 81)):
            self.assertFalse(self.app.set_model_voice(provider, model, voice)['ok'], (provider, model))

    def test_the_catalogue_is_synced_once_after_the_app_learns_about_voices(self):
        import time

        import providers
        cfg = self.config.load_config()
        cfg['providers'][-1]['catalog_updated_at'] = time.time()  # sincronizado há pouco, mas por uma versão que não guardava vozes
        self.config.save_config(cfg)
        from providers import catalog
        entry = catalog.normalize(dict(id='eleven', name='Eleven', architecture=dict(output_modalities=['speech']), endpoints=['/api/v1/audio/speech'],
                                       supported_voices=['george', 'Sarah', 'adam']), 'openrouter')
        with patch.object(providers, 'list_models', return_value=dict(models=[entry])) as listed:
            state = self.app.sync_provider_models('router', False)
            self.app.sync_provider_models('router', False)
        self.assertEqual(listed.call_count, 1, 'uma vez por causa da versão; depois volta a esperar as 24 horas')
        self.assertEqual(self.model(state, 'eleven')['voices'], ['george', 'Sarah', 'adam'])


if __name__ == '__main__':
    unittest.main()
