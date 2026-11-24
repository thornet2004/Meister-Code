"""A secção «A minha rig»: provedor à parte, que se liga e desliga, com esforço de raciocínio e voz."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import rig


class Reply:
    def __init__(self, status=200, data=None):
        self.status_code, self.data = status, data

    def json(self):
        if self.data is None:
            raise ValueError('sem JSON')
        return self.data


PROPS = dict(model_alias='qwen3.8-27b', default_generation_settings=dict(n_ctx=32768))


class RigModuleTests(unittest.TestCase):
    def test_address_accepts_the_v1_suffix_and_refuses_anything_odd(self):
        self.assertEqual(rig.origin(' http://192.168.0.10:8081/v1/ '), 'http://192.168.0.10:8081')
        self.assertEqual(rig.origin('https://ia.exemplo.pt'), 'https://ia.exemplo.pt')
        self.assertEqual((rig.origin(''), rig.origin(None)), ('', ''))
        for bad in ('192.168.0.10:8081', 'http://u:p@rig:1', 'http://rig:1/outra', 'http://rig:1?x=1', 'ftp://rig'):
            with self.assertRaises(rig.RigError, msg=bad):
                rig.origin(bad)
        self.assertEqual(rig.whisper_address('http://192.168.0.10:8081'), 'http://192.168.0.10:8089')
        self.assertEqual(rig.whisper_address('https://rig.exemplo.pt', gateway=True), 'https://rig.exemplo.pt', 'pelo porteiro a voz usa a mesma porta')

    def test_probe_reads_model_and_context_and_explains_failures(self):
        import requests
        calls = []

        def get(url, **kwargs):
            calls.append((url, kwargs['headers']))
            return replies.pop(0)
        replies = [Reply(data=PROPS), Reply(401), Reply(503), Reply(500), Reply(200), Reply(data=dict(model_alias=''))]
        with patch.object(requests, 'get', side_effect=get):
            self.assertEqual(rig.probe('http://rig:8081', 'segredo'), dict(model='qwen3.8-27b', context=32768))
            for expected in ('recusou a chave', 'a carregar', 'erro 500', 'formato', 'que modelo'):
                with self.assertRaises(rig.RigError) as raised:
                    rig.probe('http://rig:8081')
                self.assertIn(expected, str(raised.exception))
        self.assertEqual(calls[0], ('http://rig:8081/props', {'Authorization': 'Bearer segredo'}))
        self.assertEqual(calls[1][1], {}, 'sem chave não se manda cabeçalho')
        with patch.object(requests, 'get', side_effect=requests.ConnectionError('fora')):
            with self.assertRaises(rig.RigError) as raised:
                rig.probe('http://rig:8081')
        self.assertIn('não respondeu', str(raised.exception))

    def test_every_model_on_the_rig_is_listed_with_its_own_server(self):
        import requests
        from providers import multi
        served = {'http://192.168.0.10:8081/props': dict(model_alias='qwen3.8-27b', default_generation_settings=dict(n_ctx=32768)),
                  'http://192.168.0.10:8082/props': dict(model_alias='qwen3.8-27b-uncensored', default_generation_settings=dict(n_ctx=16384)),
                  'http://192.168.0.10:8084/props': dict(model_alias='qwen3.8-27b', default_generation_settings=dict(n_ctx=8192))}

        def get(url, **kwargs):
            if url not in served:
                raise requests.ConnectionError('porta fechada')
            return Reply(data=served[url])
        with patch.object(requests, 'get', side_effect=get):
            found = rig.probe_all('http://192.168.0.10:8081', 'segredo')
        self.assertEqual(found, [dict(model='qwen3.8-27b', context=32768, base='http://192.168.0.10:8081'),
                                 dict(model='qwen3.8-27b-uncensored', context=16384, base='http://192.168.0.10:8082')], 'pela ordem das portas, sem repetir nomes')
        with patch.object(requests, 'get', side_effect=requests.ConnectionError('fora')):
            with self.assertRaises(rig.RigError):
                rig.probe_all('http://192.168.0.10:8081')  # a porta indicada tem de responder

        # Porteiro: uma porta única responde por todos os modelos (é assim que se entra de fora, por HTTPS)
        asked = []

        def gate(url, **kwargs):
            asked.append((url, kwargs['headers']))
            return Reply(data=listing) if url.endswith('/v1/models') else Reply(404)
        listing = dict(object='list', porteiro=1, papel='amigo', whisper=True, data=[dict(id='qwen3.8-27b', context=32768), dict(id='outro'), dict(id='')])
        with patch.object(requests, 'get', side_effect=gate):
            found = rig.probe_all('https://rig.exemplo.pt', 'chave-amigo')
            self.assertEqual(found, [dict(model='qwen3.8-27b', context=32768, base='https://rig.exemplo.pt', gateway=True),
                                     dict(model='outro', context=0, base='https://rig.exemplo.pt', gateway=True)])
            self.assertEqual(asked, [('https://rig.exemplo.pt/v1/models', {'Authorization': 'Bearer chave-amigo'})], 'não se anda à procura de portas')
            listing = dict(object='list', porteiro=1, data=[])
            with self.assertRaises(rig.RigError) as raised:
                rig.probe_all('https://rig.exemplo.pt', 'chave-amigo')
            self.assertIn('nenhum modelo', str(raised.exception))
            with patch.object(requests, 'get', return_value=Reply(401)), self.assertRaises(rig.RigError) as raised:
                rig.probe_all('https://rig.exemplo.pt', 'errada')
            self.assertIn('recusou a chave', str(raised.exception))
            listing = dict(object='list', data=[dict(id='qwen3.8-27b')])  # um servidor llama.cpp também tem /v1/models: não é porteiro
            self.assertIsNone(rig.gateway('http://192.168.0.10:8081', ''))

        mine = dict(rig=True, kind='openai-compatible', base_url='http://192.168.0.10:8081/v1', api_key='segredo')
        second = dict(id='qwen3.8-27b-uncensored', base_url='http://192.168.0.10:8082/v1')
        self.assertEqual(rig.routed(mine, second)['base_url'], 'http://192.168.0.10:8082/v1')
        self.assertIs(rig.routed(mine, dict(id='x')), mine)
        self.assertEqual(rig.routed(dict(kind='openrouter', base_url='a'), second)['base_url'], 'a', 'só a rig tem um servidor por modelo')
        urls = []

        def post(method, url, **kwargs):
            urls.append(url)
            return Reply(data={'choices': [{'message': {'content': 'ok'}, 'finish_reason': 'stop'}]})

        class Context(Reply):
            ok = True
            headers = {'Content-Type': 'application/json'}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        def request(method, url, **kwargs):
            urls.append(url)
            return Context(data={'choices': [{'message': {'content': 'ok'}, 'finish_reason': 'stop'}]})
        with patch.object(multi.requests, 'request', side_effect=request):
            multi.compatible(mine, second, [dict(role='user', content='olá')])
            multi.compatible(mine, dict(id='qwen3.8-27b'), [dict(role='user', content='olá')])
        self.assertEqual(urls, ['http://192.168.0.10:8082/v1/chat/completions', 'http://192.168.0.10:8081/v1/chat/completions'])

    def test_reasoning_follows_the_chosen_effort_only_on_the_rig(self):
        mine = dict(rig=True, effort='pesado')
        self.assertEqual(rig.reasoning(mine), {'reasoning_effort': 'high'})
        self.assertEqual(rig.reasoning(dict(rig=True, effort='moderado')), {'reasoning_effort': 'medium'})
        self.assertEqual(rig.reasoning(dict(rig=True)), {'reasoning_effort': 'low'}, 'sem escolha é o leve')
        self.assertEqual(rig.reasoning(mine, voice=True), {'reasoning_effort': 'none'}, 'na conversa por voz não se raciocina')
        self.assertEqual(rig.reasoning(dict(kind='openrouter')), {}, 'os outros provedores ficam como estavam')


class RigBridgeTests(unittest.TestCase):
    def setUp(self):
        import api
        import config
        self.tmp = tempfile.TemporaryDirectory()
        home = Path(self.tmp.name).resolve()
        (home / 'settings').mkdir()
        self.patches = [patch('config.config_dir', return_value=home / 'settings'), patch('config.application_root', return_value=home / 'app')]
        for item in self.patches:
            item.start()
        cfg = config.default_config()
        cfg['providers'].append(dict(id='router', name='OpenRouter', kind='openrouter', api_key='sk-nuvem', models=[dict(id='deepseek', name='DeepSeek', type='chat')]))
        cfg['chat'] = dict(provider_id='router', model_id='deepseek')
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

    def test_without_a_chat_model_nothing_is_chosen_for_the_user(self):
        import requests
        with patch.object(requests, 'get', side_effect=lambda url, **kwargs: Reply(data=PROPS)):
            self.assertTrue(self.app.set_rig(dict(enabled=True, address='http://192.168.0.10:8081'))['rig']['enabled'])
        cfg = self.config.load_config()
        rig.find(cfg)['previous'] = {}  # quem só usava a rig para conversar não tem modelo online para onde voltar
        self.config.save_config(cfg)
        state = self.app.set_rig(dict(enabled=False))
        self.assertEqual((state['rig']['enabled'], state['selections']['chat']), (False, {}))

        with patch.object(requests, 'get', side_effect=AssertionError('a app não se liga à rig por iniciativa própria')), \
                patch('providers.get_chat_adapter', side_effect=AssertionError('nem escolhe um modelo de conversa pelo utilizador')):
            answer = self.app.chat('gera um áudio com o riso do Pai Natal')
        self.assertFalse(answer['ok'])
        self.assertIn('«💬 Conversa»', answer['error'])
        self.assertIn('«Provedor local»', answer['error'], 'com a rig configurada, lembra-se o caminho para ela')
        state = self.app.get_state()
        self.assertEqual((state['rig']['enabled'], state['selections']['chat']), (False, {}), 'nada foi escolhido pela app')

    def test_a_rig_model_that_cannot_see_does_not_get_the_generated_images(self):
        """Visto a 24/11/2026: depois de gerar uma imagem, o pedido seguinte à rig levou-a em base64 e o servidor, sem leitura de
        imagens, contou-a como 110 mil tokens de texto («exceeds the available context size»)."""
        import base64
        import requests

        import chat_messages
        import providers
        self.assertFalse(chat_messages._accepts_images(dict(), dict(id='x', accepts_images=False)))
        self.assertTrue(chat_messages._accepts_images(dict(), dict(id='x', accepts_images=True)))
        blind = dict(PROPS, modalities=dict(vision=False, audio=False))
        with patch.object(requests, 'get', side_effect=lambda url, **kwargs: Reply(data=blind) if url.endswith(':8081/props') else Reply(404)):
            self.assertEqual(rig.probe('http://192.168.0.10:8081'), dict(model='qwen3.8-27b', context=32768, vision=False))
            self.assertTrue(self.app.set_rig(dict(enabled=True, address='http://192.168.0.10:8081'))['rig']['enabled'])
        stored = rig.find(self.config.load_config())
        self.assertIs(stored['models'][0]['accepts_images'], False)
        listing = dict(object='list', porteiro=1, data=[dict(id='a', context=1, vision=True), dict(id='b', context=1, vision=False), dict(id='c', context=1)])
        with patch.object(requests, 'get', return_value=Reply(data=listing)):
            self.assertEqual([m.get('vision') for m in rig.gateway('https://rig.exemplo.pt', 'k')], [True, False, None], 'sem dizer, não se sabe')

        picture = Path(self.tmp.name) / 'gerada.png'
        picture.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='))
        seen = []

        def adapter(provider, model, messages, tools=None, params=None):
            has_image = any(isinstance(m.get('content'), list) and any(p.get('type') == 'image_url' for p in m['content']) for m in messages)
            seen.append(has_image)
            if has_image:
                raise providers.ProviderError('Erro HTTP 400: {"error":{"code":400,"message":"request (110388 tokens) exceeds the available context size (65536 tokens), try increasing it","type":"exceed_context_size_error"}}')
            return {'content': 'Vi a nota da imagem.', 'tool_calls': []}

        def talk(text):
            with patch('providers.get_chat_adapter', return_value=adapter), patch.object(chat_messages, '_media_list', side_effect=lambda m: [dict(type='image', path=str(picture))] if m.get('role') == 'assistant' and m.get('media') else []):
                return self.app.chat(text)
        with patch('providers.get_chat_adapter', return_value=lambda *a, **k: {'content': 'Aqui está o logótipo.', 'tool_calls': []}):
            self.assertTrue(self.app.chat('faz um logótipo')['ok'])
        import api
        meta_dir, _ = self.config.resolve_context(self.config.load_config())
        conv = api._load_conversation(meta_dir)
        conv[-1]['media'] = [dict(path=str(picture), type='image')]
        api._save_conversation(conv, meta_dir)

        self.assertTrue(talk('gostas?')['ok'])
        self.assertEqual(seen, [False], 'o modelo da rig não lê imagens: nem se tenta')

        # servidor que não disse se lê imagens: tenta-se, o contexto rebenta por causa delas, repete-se sem elas
        cfg = self.config.load_config()
        rig.find(cfg)['models'][0].pop('accepts_images')
        self.config.save_config(cfg)
        seen.clear()
        answer = talk('e agora?')
        self.assertTrue(answer['ok'], answer)
        self.assertEqual(seen, [True, False])

    def test_voice_turn_leaves_out_the_code_context_to_answer_fast(self):
        """Visto a 24/11/2026: na conversa por voz o agente demorava uma eternidade — o código do projeto ia no prompt a
        cada pergunta e obrigava a rig a reprocessar tudo. No modo voz esse bloco não é enviado."""
        seen = []

        def adapter(provider, model, messages, tools=None, params=None):
            seen.append('\n'.join(m.get('content') for m in messages if isinstance(m.get('content'), str)))
            return {'content': 'Olá.', 'tool_calls': []}

        def fake_attach(ctx, meta, query, refresh=False):
            ctx['_continuity'] = ''
            ctx['_code_context'] = 'MARCA_CONTEXTO_DE_CODIGO'
            return refresh

        with patch('providers.get_chat_adapter', return_value=adapter), patch.object(self.app, '_attach_project_context', side_effect=fake_attach):
            self.app._voice_reply = True
            self.assertTrue(self.app.chat('que horas são')['ok'])
            self.assertNotIn('MARCA_CONTEXTO_DE_CODIGO', seen[-1], 'por voz, o código do projeto não vai no prompt')
            self.app._voice_reply = False
            self.assertTrue(self.app.chat('e agora')['ok'])
            self.assertIn('MARCA_CONTEXTO_DE_CODIGO', seen[-1], 'em texto, continua a ir')
        self.app._voice_reply = False

    def test_the_code_model_is_chosen_apart_and_the_chat_model_hands_the_work_over(self):
        """Pedido do user (24/11/2026): um campo «Código» à parte do da conversa; quem conversa interpreta e passa o trabalho."""
        import api_helpers
        cfg = self.config.load_config()
        cfg['providers'][-1]['models'] += [dict(id='coder', name='Coder', type='chat', categories=['code']), dict(id='flux', name='Flux', type='image')]
        self.config.save_config(cfg)
        self.assertEqual(self.app.get_state()['selections']['code'], {}, 'nada é escolhido pela app')
        self.assertFalse(self.app.set_model('code', 'router', 'flux')['ok'], 'um modelo de imagem não serve para código')
        calls = []

        def adapter(provider, model, messages, tools=None, params=None):
            names = [t['function']['name'] for t in tools or []]
            calls.append((model['id'], 'usar_modelo_codigo' in names))
            if model['id'] == 'deepseek' and 'usar_modelo_codigo' in names:
                call = dict(id='c1', name='usar_modelo_codigo', arguments=dict(tarefa='Cria uma calculadora em Python.'))
                raw = dict(role='assistant', content=None, tool_calls=[dict(id='c1', type='function', function=dict(name='usar_modelo_codigo', arguments='{}'))], _native='resto')
                return dict(content='', tool_calls=[call], raw_message=raw)
            if model['id'] == 'coder':
                self.assertFalse(any('_native' in m for m in messages))
                self.assertIn('Cria uma calculadora', messages[-1]['content'])
            return dict(content='Feito por ' + model['id'] + '.', tool_calls=[])

        with patch('providers.get_chat_adapter', return_value=adapter):
            self.assertTrue(self.app.chat('olá')['ok'])
            self.assertEqual(calls, [('deepseek', False)], 'sem modelo de código escolhido, programa o da conversa')
            self.assertEqual(self.app.set_model('code', 'router', 'deepseek')['selections']['code'], dict(provider_id='router', model_id='deepseek'))
            calls.clear()
            self.assertTrue(self.app.chat('olá outra vez')['ok'])
            self.assertEqual(calls, [('deepseek', False)], 'o mesmo modelo nos dois campos: não há a quem passar')
            self.assertTrue(self.app.set_model('code', 'router', 'coder')['ok'])
            calls.clear()
            self.assertTrue(self.app.chat('usa o teu modelo de código e faz uma calculadora')['ok'])
        self.assertEqual(calls, [('deepseek', True), ('coder', False)], 'o da conversa interpreta, o de código faz — e já não pode passar a outro')
        meta_dir, _ = self.config.resolve_context(self.config.load_config())
        import api
        last = api._load_conversation(meta_dir)[-1]
        self.assertEqual((last['text'], last['model']), ('Feito por coder.', dict(provider_id='router', model_id='coder')))
        self.assertEqual([step['title'] for step in last['steps']], ['usar_modelo_codigo'])
        self.assertEqual(self.app.set_model('chat', 'router', 'coder')['selections']['chat']['model_id'], 'coder')

        # «Provedor local»: os modelos online deixam de contar, mesmo que estejam escolhidos
        cfg = self.config.load_config()
        cfg['image'] = dict(provider_id='router', model_id='flux')
        self.assertEqual(api_helpers._resolve_model(cfg, 'image')[1]['id'], 'flux')
        self.assertEqual(api_helpers._resolve_model(cfg, 'code')[1]['id'], 'coder')
        cfg['providers'].append(dict(id='a-minha-rig', rig=True, enabled=True, kind='openai-compatible', models=[dict(id='qwen', type='chat', categories=['code'])]))
        self.assertEqual((api_helpers._resolve_model(cfg, 'image'), api_helpers._resolve_model(cfg, 'code')), ((None, None), (None, None)))
        cfg['code'] = dict(provider_id='a-minha-rig', model_id='qwen')
        self.assertEqual(api_helpers._resolve_model(cfg, 'code')[1]['id'], 'qwen')
        with self.assertRaises(Exception) as raised:
            self.app._run_configured(cfg, 'image', 'um gato', meta_dir, meta_dir)
        self.assertIn('Provedor local', str(raised.exception))

    def test_old_tool_results_are_cut_before_the_request_overflows_the_window(self):
        """Visto a 24/11/2026: um agente despejou um executável descompilado na conversa e o pedido morreu com
        «request (66514 tokens) exceeds the available context size (65536 tokens)»."""
        import chat_messages
        import providers
        note = chat_messages.TRIM_NOTE
        big = [dict(role='system', content='s'), dict(role='user', content='descompila')]
        for index in range(4):
            big += [dict(role='assistant', content=None, tool_calls=[dict(id=str(index))]), dict(role='tool', tool_call_id=str(index), content=str(index) * 30000)]
        untouched = [dict(m) for m in big]
        self.assertEqual(chat_messages._fit_context(big, 0), 0, 'sem janela conhecida não se corta nada')
        self.assertEqual(chat_messages._fit_context(big, 200000), 0, 'longe do limite não se corta nada')
        self.assertEqual(big, untouched)
        self.assertEqual(chat_messages._fit_context(big, 30000), 2)
        results = [m['content'] for m in big if m['role'] == 'tool']
        self.assertEqual([r.endswith(note) for r in results], [True, True, False, False], 'primeiro os mais antigos; os dois últimos ficam inteiros')
        self.assertTrue(results[0].startswith('0' * 300 + chr(10)))
        self.assertLessEqual(chat_messages._context_tokens(big), 24000)
        self.assertEqual(chat_messages._fit_context(big, 9000), 2, 'em último caso também os recentes, com mais texto guardado')
        self.assertEqual(chat_messages._fit_context(big, 9000), 0, 'o que já foi cortado não se corta outra vez')
        system = chat_messages._build_model_messages([dict(role='user', text='olá')], None, [dict(type='function', function=dict(name='x', description='', parameters={}))])[0]['content']
        self.assertIn('JANELA DE CONTEXTO', system, 'as regras de trabalho vão sozinhas quando há ferramentas')
        self.assertNotIn('JANELA DE CONTEXTO', chat_messages._build_model_messages([dict(role='user', text='olá')], None, [])[0]['content'])

        def run(window):
            cfg = self.config.load_config()
            cfg['providers'][-1]['models'][0]['defaults'] = dict(context_window=window) if window else {}
            self.config.save_config(cfg)
            seen = []

            def adapter(provider, model, messages, tools=None, params=None):
                results = [m['content'] for m in messages if m.get('role') == 'tool']
                seen.append([r.endswith(note) for r in results])
                if not window and len(results) == 3 and not any(seen[-1]):
                    raise providers.ProviderError('Erro HTTP 400: {"error":{"code":400,"message":"request (66514 tokens) exceeds the available context size (40000 tokens), try increasing it","type":"exceed_context_size_error"}}')
                if len(results) < 3:
                    call = dict(id='c%d' % len(results), name='ler_ficheiro', arguments=dict(caminho='parte%d.txt' % len(results)))
                    return dict(content='', tool_calls=[call], raw_message=dict(role='assistant', content=None, tool_calls=[dict(id=call['id'], type='function', function=dict(name='ler_ficheiro', arguments='{}'))]))
                return dict(content='Analisado.', tool_calls=[])
            with patch('providers.get_chat_adapter', return_value=adapter), patch.object(self.app, '_handle_tool', side_effect=lambda cfg, tc, *rest: tc['id'][-1] * 30000):
                answer = self.app.chat('descompila o programa')
            self.assertTrue(answer['ok'], answer)
            import api
            meta_dir, _ = self.config.resolve_context(self.config.load_config())
            return seen, [step['title'] for step in api._load_conversation(meta_dir)[-1]['steps']]

        seen, steps = run(38000)
        self.assertEqual(seen[-1], [True, False, False], 'com a janela do modelo conhecida, corta-se antes de pedir')
        self.assertIn('janela de contexto', steps)
        seen, steps = run(0)
        self.assertEqual(seen[-2:], [[False, False, False], [True, True, False]], 'sem a conhecer: o servidor recusa, corta-se e repete-se uma vez')
        self.assertIn('janela de contexto', steps)

    def test_a_long_request_is_stopped_by_the_users_limits_not_by_a_hidden_ceiling(self):
        """Pedido do user (24/11/2026): sai o teto fixo de 25 rondas; mandam os limites dele, com 4 milhões de tokens por omissão."""
        import execution_limits
        self.assertEqual((execution_limits.DEFAULTS['tokens'], self.app.get_execution_limits()['limits']['tokens']), (4000000, 4000000))
        cfg = self.config.load_config()
        cfg['preferences']['execution_limits'] = dict(seconds=900, tokens=200000, tool_calls=50, cost=0, input_per_million=0, output_per_million=0)
        self.config.save_config(cfg)
        self.assertEqual(self.app.get_execution_limits()['limits'], dict(seconds=900, tokens=4000000, tool_calls=50, cost=0, input_per_million=0, output_per_million=0),
                         'quem tinha guardado o valor antigo por omissão passa para o novo; o resto fica como estava')
        cfg['preferences']['execution_limits']['tokens'] = 500000
        self.config.save_config(cfg)
        self.assertEqual(self.app.get_execution_limits()['limits']['tokens'], 500000, 'um valor escolhido pelo utilizador não é mexido')
        cfg['preferences'].pop('execution_limits')
        self.config.save_config(cfg)

        def run(rounds):
            count = [0]

            def adapter(provider, model, messages, tools=None, params=None):
                count[0] += 1
                if count[0] > rounds:
                    return dict(content='Acabei.', tool_calls=[])
                call = dict(id='c%d' % count[0], name='ler_ficheiro', arguments=dict(caminho='parte%d.txt' % count[0]))
                return dict(content='', tool_calls=[call], raw_message=dict(role='assistant', content=None, tool_calls=[dict(id=call['id'], type='function', function=dict(name='ler_ficheiro', arguments='{}'))]))
            with patch('providers.get_chat_adapter', return_value=adapter), patch.object(self.app, '_handle_tool', side_effect=lambda cfg, tc, *rest: 'resultado ' + tc['id']):
                self.assertTrue(self.app.chat('trabalho longo')['ok'])
            import api
            meta_dir, _ = self.config.resolve_context(self.config.load_config())
            self.last = api._load_conversation(meta_dir)[-1]
            return count[0], self.last['text']

        self.assertEqual(run(40), (41, 'Acabei.'), '40 rondas de ferramentas já não são cortadas às 25')
        self.assertTrue(self.app.set_execution_limits(dict(seconds=1800, tokens=4000000, tool_calls=10, cost=0, input_per_million=0, output_per_million=0))['ok'])
        calls, text = run(40)
        self.assertEqual(calls, 10)
        self.assertIn('Limite de chamadas de ferramentas atingido', text)
        self.assertEqual((self.last['turn_state'], self.last['stop_reason']), ('limited', 'Limite de chamadas de ferramentas atingido.'), 'a interface diz no fim porque parou')
        self.assertTrue(self.app.set_execution_limits(dict(seconds=1800, tokens=4000000, tool_calls=100, cost=0, input_per_million=0, output_per_million=0))['ok'])
        run(2)
        self.assertNotIn('stop_reason', self.last, 'um pedido que acabou bem não leva aviso')
        silent = iter([dict(content='Vou ler.', tool_calls=[dict(id='s1', name='ler_ficheiro', arguments=dict(caminho='a.txt'))], raw_message=dict(role='assistant', content='Vou ler.')), dict(content='', tool_calls=[])])
        with patch('providers.get_chat_adapter', return_value=lambda *a, **k: next(silent)), patch.object(self.app, '_handle_tool', side_effect=lambda cfg, tc, generated, steps, *rest: steps.append(dict(kind='tool', title='ler_ficheiro', body='', ok=True)) or 'conteúdo'):
            self.assertTrue(self.app.chat('lê e diz-me')['ok'])
        import api
        last = api._load_conversation(self.config.resolve_context(self.config.load_config())[0])[-1]
        self.assertEqual(last.get('stop_reason'), 'O modelo terminou sem escrever uma resposta final.')

    def test_through_the_gateway_models_and_voice_share_one_address(self):
        import requests
        listing = dict(object='list', porteiro=1, papel='amigo', whisper=True, data=[dict(id='qwen3.8-27b', context=32768), dict(id='qwen3.8-27b-uncensored', context=16384)])
        with patch.object(requests, 'get', side_effect=lambda url, **kwargs: Reply(data=listing) if url == 'https://rig.exemplo.pt/v1/models' else Reply(404)):
            state = self.app.set_rig(dict(enabled=True, address='https://rig.exemplo.pt', api_key='mr-amigo', whisper=True))
        self.assertNotIn('rig_error', state)
        self.assertEqual((state['rig']['enabled'], state['rig']['gateway'], state['rig']['models']), (True, True, ['qwen3.8-27b', 'qwen3.8-27b-uncensored']))
        self.assertEqual(state['preferences']['voice_server'], 'https://rig.exemplo.pt', 'a voz entra pela mesma porta')
        stored = rig.find(self.config.load_config())
        self.assertEqual([(m['base_url'], m['defaults']) for m in stored['models']],
                         [('https://rig.exemplo.pt/v1', {'context_window': 32768}), ('https://rig.exemplo.pt/v1', {'context_window': 16384})])
        self.assertNotIn('mr-amigo', repr(state))
        # voltar a um endereço com um servidor por porta desfaz a marca do porteiro
        with patch.object(requests, 'get', side_effect=lambda url, **kwargs: Reply(data=PROPS) if url.endswith(':8081/props') else Reply(404)):
            state = self.app.set_rig(dict(enabled=True, address='http://192.168.0.10:8081', whisper=True))
        self.assertEqual((state['rig']['gateway'], state['preferences']['voice_server']), (False, 'http://192.168.0.10:8089'))

    def test_online_and_local_are_two_separate_modes(self):
        import requests
        online = dict(provider_id='router', model_id='deepseek')
        self.assertTrue(self.app.set_agent_model('explore', 'router', 'deepseek')['ok'])
        state = self.app.get_state()
        self.assertEqual((state['rig']['enabled'], [p['id'] for p in state['providers']]), (False, ['router']))
        self.assertFalse(self.app.set_rig(dict(enabled=True, address=''))['ok'], 'local sem endereço')
        self.assertFalse(self.app.set_rig(dict(enabled=True, address='http://rig:8081/outra'))['ok'])
        self.assertFalse(self.app.set_rig(dict(enabled=False, address='http://rig:8081', effort='brutal'))['ok'])

        with patch.object(requests, 'get', side_effect=requests.ConnectionError('fora')):
            state = self.app.set_rig(dict(enabled=True, address='http://192.168.0.10:8081', api_key='chave-rig', effort='moderado', whisper=True))
        self.assertTrue(state['ok'])
        self.assertIn('não respondeu', state['rig_error'])
        self.assertEqual((state['rig']['enabled'], state['rig']['address'], state['rig']['has_key'], state['rig']['effort']),
                         (False, 'http://192.168.0.10:8081', True, 'moderado'), 'fica guardado, mas continua-se online')
        self.assertEqual(([p['id'] for p in state['providers']], state['selections']['chat'], state['preferences']['voice_server']), (['router'], online, ''))

        seen = []

        def get(url, **kwargs):
            seen.append(kwargs['headers'])
            return Reply(data=PROPS)
        with patch.object(requests, 'get', side_effect=get):
            state = self.app.set_rig(dict(enabled=True, address='http://192.168.0.10:8081/v1', api_key='', effort='pesado', whisper=True))
            again = self.app.set_rig(dict(enabled=True, effort='leve', whisper=True))  # mudar o esforço já em modo local
        self.assertNotIn('rig_error', state)
        self.assertEqual(seen[0], {'Authorization': 'Bearer chave-rig'}, 'chave vazia mantém a guardada')
        self.assertEqual(state['rig'], dict(enabled=True, address='http://192.168.0.10:8081', has_key=True, effort='pesado', whisper=True, gateway=False, model='qwen3.8-27b', models=['qwen3.8-27b'], context=32768))
        mine = next(p for p in state['providers'] if p['rig'])
        self.assertEqual((mine['name'], mine['kind'], mine['models'][0]['id'], mine['models'][0]['defaults'], mine['models'][0]['categories']),
                         ('Meister Chat', 'openai-compatible', 'qwen3.8-27b', {'context_window': 32768}, ['code']))
        self.assertEqual(state['selections']['chat'], dict(provider_id=mine['id'], model_id='qwen3.8-27b'), 'em modo local a conversa é da rig')
        self.assertEqual(state['preferences']['agent_models'], {}, 'e os subagentes também')
        self.assertEqual(state['preferences']['voice_server'], 'http://192.168.0.10:8089')
        self.assertNotIn('chave-rig', repr(state), 'a chave nunca vai para a interface')
        self.assertEqual((again['rig']['effort'], again['rig']['enabled']), ('leve', True))
        stored = rig.find(self.config.load_config())
        self.assertEqual(rig.reasoning(stored), {'reasoning_effort': 'low'})
        self.assertEqual(stored['previous']['chat'], online, 'mexer no esforço não apaga o que estava guardado do modo online')

        # Já em modo local, uma falha passageira da rig (ao mudar o esforço, por exemplo) não tira a app do modo local
        with patch.object(requests, 'get', side_effect=requests.ConnectionError('fora')):
            hiccup = self.app.set_rig(dict(enabled=True, effort='moderado', whisper=True))
        self.assertIn('não respondeu', hiccup['rig_error'])
        self.assertEqual((hiccup['rig']['enabled'], hiccup['rig']['effort'], hiccup['rig']['models'], hiccup['selections']['chat']),
                         (True, 'moderado', ['qwen3.8-27b'], dict(provider_id=mine['id'], model_id='qwen3.8-27b')), 'continua local, com o modelo escolhido')
        self.assertEqual(rig.find(self.config.load_config())['previous']['chat'], online, 'e o que estava guardado do modo online não se perde')
        with patch.object(requests, 'get', side_effect=get):
            self.assertEqual(self.app.set_rig(dict(enabled=True, effort='leve', whisper=True))['rig']['effort'], 'leve')
        # …mas trocar a chave por uma que a rig recusa volta a pôr a app online, como ao ligar pela primeira vez
        with patch.object(requests, 'get', return_value=Reply(401)):
            refused = self.app.set_rig(dict(enabled=True, api_key='chave-errada', whisper=True))
        self.assertEqual((refused['rig']['enabled'], refused['selections']['chat']), (False, online))
        with patch.object(requests, 'get', side_effect=get):
            self.assertTrue(self.app.set_rig(dict(enabled=True, api_key='chave-rig', effort='leve', whisper=True))['rig']['enabled'])

        state = self.app.set_rig(dict(enabled=False))
        self.assertEqual((state['rig']['enabled'], state['rig']['address'], state['rig']['effort'], state['rig']['whisper']), (False, 'http://192.168.0.10:8081', 'leve', False))
        self.assertEqual(([p['id'] for p in state['providers']], state['selections']['chat'], state['preferences']['agent_models'], state['preferences']['voice_server']),
                         (['router'], online, dict(explore=online), ''), 'voltar a online repõe as escolhas que lá estavam')
        stored = rig.find(self.config.load_config())
        self.assertTrue(stored['api_key'], 'a chave continua guardada')
        self.assertNotIn('previous', stored)

    def test_going_back_online_does_not_restore_a_model_that_is_gone(self):
        import requests
        with patch.object(requests, 'get', return_value=Reply(data=PROPS)):
            self.app.set_rig(dict(enabled=True, address='http://rig:8081'))
        self.assertTrue(self.app.remove_model('router', 'deepseek')['ok'])
        state = self.app.set_rig(dict(enabled=False))
        self.assertEqual(state['selections']['chat'], {})
        self.assertEqual(state['rig']['effort'], 'leve')


if __name__ == '__main__':
    unittest.main()
