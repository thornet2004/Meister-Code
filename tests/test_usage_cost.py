"""Custo por resposta e por conversa (usage_cost) e o seu registo no chat."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import usage_cost

CFG = {
    'providers': [
        {'id': 'or', 'kind': 'openrouter', 'catalog': [
            {'id': 'barato', 'pricing': {'prompt': '0.000001', 'completion': '0.000002'}},
            {'id': 'gratis', 'pricing': {'prompt': '0', 'completion': '0'}},
            {'id': 'variavel', 'pricing': {'prompt': '-1', 'completion': '-1'}},
            {'id': 'sem-preco', 'pricing': {}},
        ]},
        {'id': 'local', 'kind': 'ollama', 'catalog': []},
    ],
    'preferences': {},
}
USAGE = {'prompt_tokens': 1000, 'completion_tokens': 500, 'total_tokens': 1500}


class PricesTest(unittest.TestCase):
    def test_catalog_price_per_token(self):
        self.assertEqual(usage_cost.prices(CFG, 'or', 'barato'), {'input': 0.000001, 'output': 0.000002, 'source': 'catalog'})
        self.assertAlmostEqual(usage_cost.estimate(USAGE, usage_cost.prices(CFG, 'or', 'barato')), 0.002)
        self.assertEqual(usage_cost.estimate(USAGE, usage_cost.prices(CFG, 'or', 'gratis')), 0.0)

    def test_unknown_when_there_is_no_usable_price(self):
        for model in ('variavel', 'sem-preco', 'nao-existe'):
            self.assertIsNone(usage_cost.prices(CFG, 'or', model), model)
        self.assertIsNone(usage_cost.prices(CFG, 'local', 'llama'))
        self.assertIsNone(usage_cost.estimate(USAGE, None))
        self.assertIsNone(usage_cost.turn_cost(CFG, 'local', 'llama', USAGE))

    def test_manual_prices_are_the_fallback(self):
        cfg = {**CFG, 'preferences': {'execution_limits': {'input_per_million': 3, 'output_per_million': 15}}}
        self.assertEqual(usage_cost.prices(cfg, 'local', 'llama'), {'input': 0.000003, 'output': 0.000015, 'source': 'manual'})
        self.assertEqual(usage_cost.prices(cfg, 'or', 'barato')['source'], 'catalog', 'o catálogo vem primeiro')
        self.assertEqual(usage_cost.turn_cost(cfg, 'local', 'llama', USAGE), {'usd': 0.0105, 'source': 'manual'})
        zero = {**CFG, 'preferences': {'execution_limits': {'input_per_million': 0, 'output_per_million': 0}}}
        self.assertIsNone(usage_cost.prices(zero, 'local', 'llama'))

    def test_cost_reported_by_provider_wins(self):
        self.assertEqual(usage_cost.reported({'cost': 0.0042}), 0.0042)
        self.assertIsNone(usage_cost.reported({'cost': None}))
        self.assertIsNone(usage_cost.reported({'cost': 'x'}))
        self.assertIsNone(usage_cost.reported({}))
        self.assertEqual(usage_cost.turn_cost(CFG, 'or', 'barato', USAGE, 0.0042), {'usd': 0.0042, 'source': 'provider'})

    def test_only_total_tokens_counts_as_input(self):
        self.assertAlmostEqual(usage_cost.estimate({'total_tokens': 1000}, usage_cost.prices(CFG, 'or', 'barato')), 0.001)


class SummaryTest(unittest.TestCase):
    def test_sums_turns_subagents_and_separates_unknown(self):
        conversation = [
            {'role': 'user', 'text': 'olá'},
            {'role': 'assistant', 'usage': USAGE, 'model': {'provider_id': 'or', 'model_id': 'barato'}, 'cost': {'usd': 0.002, 'source': 'catalog'}},
            {'role': 'assistant', 'usage': USAGE, 'model': {'provider_id': 'or', 'model_id': 'barato'}, 'cost': {'usd': 0.0031, 'source': 'provider'}},
            {'role': 'assistant', 'usage': USAGE, 'model': {'provider_id': 'or', 'model_id': 'barato'}},   # antiga, com modelo: estima
            {'role': 'assistant', 'usage': USAGE},                                                           # antiga, sem modelo: desconhecido
            {'role': 'assistant', 'usage': USAGE, 'model': {'provider_id': 'local', 'model_id': 'llama'}},  # sem preço: desconhecido
            {'role': 'assistant', 'usage': {}, 'text': 'sem tokens não conta'},
        ]
        tasks = [{'provider_id': 'or', 'model_id': 'barato', 'usage': USAGE}, {'provider_id': 'or', 'model_id': 'barato', 'usage': {}},
                 {'provider_id': 'local', 'model_id': 'llama', 'usage': USAGE}]
        result = usage_cost.summary(CFG, conversation, tasks)
        self.assertAlmostEqual(result['usd'], 0.002 + 0.0031 + 0.002 + 0.002)
        self.assertEqual(result['turns'], 4)
        self.assertEqual(result['unknown_turns'], 3)
        self.assertFalse(result['exact'])
        self.assertEqual(result['prompt_tokens'], 7000)
        self.assertEqual(result['completion_tokens'], 3500)
        self.assertEqual(result['subagents'], {'usd': 0.002, 'tasks': 2})
        self.assertEqual(result['models'][0]['model_id'], 'barato')
        self.assertEqual(result['currency'], 'USD')
        self.assertEqual({row['model_id']: row['unknown'] for row in result['models']}, {'barato': 0, '(modelo não registado)': 1, 'llama': 2})

    def test_exact_only_when_everything_came_from_the_provider(self):
        turn = {'role': 'assistant', 'usage': USAGE, 'model': {'provider_id': 'or', 'model_id': 'barato'}, 'cost': {'usd': 0.01, 'source': 'provider'}}
        self.assertTrue(usage_cost.summary(CFG, [turn])['exact'])
        self.assertFalse(usage_cost.summary(CFG, [turn, {'role': 'assistant', 'usage': USAGE}])['exact'])
        self.assertFalse(usage_cost.summary(CFG, [])['exact'])
        self.assertEqual(usage_cost.summary(CFG, [])['usd'], 0)


class ChatRecordsCostTest(unittest.TestCase):
    """O chat guarda, com cada resposta, o modelo usado e o custo; o painel de contexto soma."""

    def setUp(self):
        import api
        import config
        self.config = config
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        base = Path(self.temp.name).resolve()
        (base / 'settings').mkdir()
        self.patches = [patch('config.application_root', return_value=base / 'app'), patch('config.config_dir', return_value=base / 'settings')]
        for item in self.patches:
            item.start()
        cfg = config.default_config()
        cfg.update(storage_layout=2, storage_root=str(base / 'app'),
                   providers=[dict(id='or', kind='openrouter', api_key='chave-privada', models=[dict(id='barato', type='chat')],
                                   catalog=[dict(id='barato', pricing=dict(prompt='0.000001', completion='0.000002'))])],
                   chat=dict(provider_id='or', model_id='barato'))
        config.save_config(cfg)
        self.app = api.Api()

    def tearDown(self):
        for closer in (self.app._tasks, self.app._validations, self.app._commands, self.app._lsp, self.app._mcp, self.app._folder_tools, self.app._shell):
            closer.close()
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def answer(self, **usage):
        return dict(content='resposta', tool_calls=[], raw_message=dict(role='assistant', content='resposta'), usage=usage)

    def last(self):
        return self.app.get_conversation()['messages'][-1]

    def test_estimate_from_catalog_then_provider_cost(self):
        with patch('providers.get_chat_adapter', return_value=lambda *a: self.answer(prompt_tokens=1000, completion_tokens=500, total_tokens=1500)):
            self.assertTrue(self.app.chat('primeira')['ok'])
        message = self.last()
        self.assertEqual(message['model'], {'provider_id': 'or', 'model_id': 'barato'})
        self.assertEqual(message['cost'], {'usd': 0.002, 'source': 'catalog'})
        with patch('providers.get_chat_adapter', return_value=lambda *a: self.answer(prompt_tokens=1000, completion_tokens=500, total_tokens=1500, cost=0.0033)):
            self.assertTrue(self.app.chat('segunda')['ok'])
        self.assertEqual(self.last()['cost'], {'usd': 0.0033, 'source': 'provider'})
        cost = self.app.get_context_usage()['cost']
        self.assertAlmostEqual(cost['usd'], 0.0053)
        self.assertEqual(cost['turns'], 2)
        self.assertEqual(cost['unknown_turns'], 0)
        self.assertFalse(cost['exact'])
        self.assertNotIn('chave-privada', str(cost))

    def test_unknown_price_is_not_invented(self):
        cfg = self.config.load_config()
        cfg['providers'][0]['catalog'] = []
        self.config.save_config(cfg)
        with patch('providers.get_chat_adapter', return_value=lambda *a: self.answer(prompt_tokens=10, completion_tokens=5, total_tokens=15)):
            self.assertTrue(self.app.chat('sem preço')['ok'])
        self.assertNotIn('cost', self.last())
        self.assertEqual(self.last()['model']['model_id'], 'barato')
        cost = self.app.get_context_usage()['cost']
        self.assertEqual((cost['usd'], cost['turns'], cost['unknown_turns']), (0, 0, 1))


if __name__ == '__main__':
    unittest.main()
