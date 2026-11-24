import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import api
import config
from providers import catalog, multi


def entry(mid, outputs, inputs=None, endpoints=None, description=''):
    return catalog.normalize(dict(id=mid, name=mid, description=description, context_length=64000,
                                  architecture=dict(input_modalities=inputs or ['text'], output_modalities=outputs),
                                  endpoints=endpoints or [], supported_parameters=['tools']), 'openrouter')


class CatalogTests(unittest.TestCase):
    def test_generation_uses_output_and_actual_endpoint(self):
        vision = entry('vision', ['text'], ['text', 'image', 'video'], ['/api/v1/chat/completions'])
        self.assertEqual(vision['types'], ['chat'])
        self.assertNotIn('image', vision['categories'])
        image = entry('image', ['text', 'image'], endpoints=['/api/v1/chat/completions', '/api/v1/images'])
        self.assertEqual(image['types'], ['chat', 'image'])
        self.assertEqual(entry('tts', ['speech'], endpoints=['/api/v1/audio/speech'])['types'], ['audio'])
        self.assertEqual(entry('embed', ['embeddings'])['types'], [])
        self.assertEqual(entry('transcribe', ['transcription'])['categories'], ['transcription'])

    def test_code_is_additional_inferred_tag(self):
        model = entry('coder', ['text'], endpoints=['/api/v1/chat/completions'])
        self.assertEqual(model['categories'], ['chat', 'code'])
        self.assertTrue(model['code_tag_inferred'])

    def test_merge_keeps_user_names_defaults_and_multimodal_entries(self):
        provider = dict(models=[dict(id='coder', name='Meu nome', type='chat', defaults={'context_window': 0, 'temperature': .2})])
        model = entry('coder', ['text', 'image'], endpoints=['/api/v1/chat/completions', '/api/v1/images'])
        self.assertEqual(catalog.merge(provider, [model]), 1)
        self.assertEqual(provider['models'][0]['defaults'], {'context_window': 0, 'temperature': .2})
        self.assertEqual(provider['models'][0]['name'], 'Meu nome')
        self.assertEqual(catalog.merge(provider, [model]), 0)
        self.assertEqual(len(provider['models']), 2)
        catalog.merge(provider, [])
        self.assertFalse(provider['models'][1]['catalog_available'])

    def test_openrouter_requests_all_output_modalities(self):
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.json.return_value = {'data': []}
        with patch('providers.multi.request', return_value=response) as request:
            multi.models(dict(kind='openrouter', api_key='secret'))
        self.assertEqual(request.call_args.args[2], '/models?output_modalities=all')

    def test_same_model_id_resolves_separately_for_chat_and_image(self):
        provider = dict(id='p', models=[dict(id='multi', type='image'), dict(id='multi', type='chat')])
        cfg = dict(providers=[provider], chat=dict(provider_id='p', model_id='multi'), image=dict(provider_id='p', model_id='multi'))
        self.assertEqual(api._resolve_model(cfg, 'chat')[1]['type'], 'chat')
        self.assertEqual(api._resolve_model(cfg, 'image')[1]['type'], 'image')

    def test_sync_preserves_selections_caches_and_keeps_config_on_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch('config.config_dir', return_value=root/'settings'), patch('config.application_root', return_value=root):
                cfg = config.default_config()
                cfg['providers'] = [dict(id='p', kind='openrouter', api_key='secret', models=[])]
                cfg['chat'] = dict(provider_id='p', model_id='custom')
                config.save_config(cfg)
                app = api.Api()
                try:
                    result = dict(models=[entry('coder', ['text'], endpoints=['/api/v1/chat/completions'])])
                    with patch('providers.list_models', return_value=result) as fetch:
                        self.assertTrue(app.sync_provider_models('p')['ok'])
                        self.assertTrue(app.sync_provider_models('p')['ok'])
                        self.assertEqual(fetch.call_count, 1)
                    self.assertEqual(config.load_config()['chat'], cfg['chat'])
                    before = config.config_path().read_bytes()
                    with patch('providers.list_models', side_effect=RuntimeError('secret offline')):
                        error = app.sync_provider_models('p', True)
                    self.assertFalse(error['ok'])
                    self.assertNotIn('secret', error['error'])
                    self.assertEqual(config.config_path().read_bytes(), before)
                finally:
                    app._mcp.close()


if __name__ == '__main__':
    unittest.main()
