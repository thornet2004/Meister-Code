"""Provedores na nuvem compatíveis com a OpenAI (Together, Fireworks, DeepInfra, CometAPI, APIMart), sem rede."""
import unittest
from unittest.mock import patch

import providers
from providers import multi
from providers.base import ProviderError
from test_multi_providers import Response

CLOUD = {
    'together': 'https://api.together.ai/v1',
    'fireworks': 'https://api.fireworks.ai/inference/v1',
    'deepinfra': 'https://api.deepinfra.com/v1/openai',
    'cometapi': 'https://api.cometapi.com/v1',
    'apimart': 'https://api.apimart.ai/v1',
}
ANSWER = dict(choices=[dict(message=dict(content='olá'), finish_reason='stop')], usage=dict(prompt_tokens=3, completion_tokens=1))


class CloudCompatibleProvidersTests(unittest.TestCase):
    def test_every_kind_has_a_preset_and_a_chat_function(self):
        presets = providers.provider_presets()
        self.assertEqual(set(providers._FAMILIES), set(presets), 'cada tipo aparece no formulário com nome e endereço')
        for kind, base in CLOUD.items():
            self.assertEqual((presets[kind]['base_url'], presets[kind]['requires_key']), (base, True), kind)
            self.assertTrue(presets[kind]['label'], kind)
            self.assertIs(providers._FAMILIES[kind]['chat'], multi.compatible, kind)
        self.assertEqual(presets['openai-compatible']['base_url'], '', 'o tipo genérico continua a existir para os que aparecerem')
        self.assertIs(presets['openai-compatible']['requires_key'], False)

    def test_chat_goes_to_the_preset_address_with_the_key_as_bearer(self):
        for kind, base in CLOUD.items():
            provider = dict(kind=kind, api_key='chave-de-teste', base_url='')
            with patch.object(multi.requests, 'request', return_value=Response(ANSWER)) as request:
                result = multi.compatible(provider, {'id': 'modelo-x'}, [{'role': 'user', 'content': 'olá'}], params={})
            self.assertEqual(result['text'] if 'text' in result else result['raw_message']['content'], 'olá', kind)
            method, url = request.call_args.args[:2]
            self.assertEqual((method, url), ('POST', base + '/chat/completions'), kind)
            self.assertEqual(request.call_args.kwargs['headers']['Authorization'], 'Bearer chave-de-teste', kind)
            self.assertEqual(request.call_args.kwargs['json']['model'], 'modelo-x', kind)

    def test_a_cloud_provider_without_a_key_is_refused_before_any_request(self):
        for kind in CLOUD:
            with patch.object(multi.requests, 'request') as request:
                with self.assertRaises(ProviderError, msg=kind):
                    multi.compatible(dict(kind=kind, api_key='', base_url=''), {'id': 'm'}, [{'role': 'user', 'content': 'olá'}], params={})
            request.assert_not_called()

    def test_the_address_can_be_changed_by_the_user(self):
        provider = dict(kind='together', api_key='k', base_url='https://us-api.together.ai/v1/')
        with patch.object(multi.requests, 'request', return_value=Response(ANSWER)) as request:
            multi.compatible(provider, {'id': 'm'}, [{'role': 'user', 'content': 'olá'}], params={})
        self.assertEqual(request.call_args.args[1], 'https://us-api.together.ai/v1/chat/completions')

    def test_model_list_with_or_without_the_data_wrapper(self):
        provider = dict(kind='together', api_key='k', base_url='')
        rows = [dict(id='meta/llama-x'), 'lixo', dict(id='')]
        for payload in (rows, dict(data=rows), dict(object='list', data=rows)):
            with patch.object(multi.requests, 'request', return_value=Response(payload)) as request:
                listing = providers.list_models(provider)
            self.assertEqual([row['id'] for row in listing['models']], ['meta/llama-x'], payload)
            self.assertEqual(request.call_args.args[:2], ('GET', 'https://api.together.ai/v1/models'))
        for payload in ('texto', 5, None):
            with patch.object(multi.requests, 'request', return_value=Response(payload)):
                with self.assertRaises(ProviderError):
                    providers.list_models(provider)
        with patch.object(multi.requests, 'request', return_value=Response(dict(data=None))):
            self.assertEqual(providers.list_models(provider)['models'], [])


if __name__ == '__main__':
    unittest.main()
