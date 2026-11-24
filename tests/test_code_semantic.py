"""Pesquisa de código por significado: índice de vetores e pedido de embeddings."""
import hashlib
import json
import re
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import code_semantic
from code_semantic import SemanticIndex
from providers import embeddings
from providers.base import ProviderError

# Sinónimos que o "modelo" de teste trata como o mesmo conceito: é isto que
# distingue a pesquisa por significado da pesquisa por palavras iguais.
CONCEPTS = {'login': 'auth', 'autenticar': 'auth', 'autenticação': 'auth', 'password': 'auth', 'senha': 'auth',
            'fatura': 'invoice', 'faturas': 'invoice', 'invoice': 'invoice', 'pagamento': 'invoice',
            'imagem': 'image', 'imagens': 'image', 'thumbnail': 'image', 'redimensionar': 'image', 'miniatura': 'image'}


def fake_vector(text, size=48):
    vector = [0.0] * size
    for word in re.findall(r'\w+', text.lower()):
        concept = CONCEPTS.get(word)
        if concept:
            vector[int(hashlib.sha1(concept.encode()).hexdigest(), 16) % size] += 5.0
        vector[int(hashlib.sha1(word.encode()).hexdigest(), 16) % size] += 0.2
    vector[0] += 0.01  # nunca nulo
    return vector


class Embedder:
    def __init__(self):
        self.calls = 0
        self.texts = []

    def __call__(self, texts):
        self.calls += 1
        self.texts.extend(texts)
        return [fake_vector(text) for text in texts]


class SemanticIndexTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name).resolve()
        self.root = base / 'projeto'
        self.meta = base / 'meta'
        self.root.mkdir()
        self.meta.mkdir()
        (self.root / 'auth.py').write_text('def verificar_senha(utilizador, senha):\n    """Autenticar o utilizador com a password guardada."""\n    return comparar(utilizador, senha)\n', encoding='utf-8')
        (self.root / 'billing.py').write_text('def emitir(cliente, total):\n    """Cria a fatura e regista o pagamento do cliente."""\n    return gravar(cliente, total)\n', encoding='utf-8')
        (self.root / 'media.py').write_text('def miniatura(ficheiro, largura):\n    """Redimensionar a imagem para criar um thumbnail."""\n    return escalar(ficheiro, largura)\n', encoding='utf-8')
        (self.root / '.env').write_text('API_KEY=segredo-que-nao-pode-sair\n', encoding='utf-8')
        self.embed = Embedder()
        self.index = SemanticIndex(self.meta, self.root)

    def tearDown(self):
        self.temp.cleanup()

    def search(self, question, limit=3):
        return self.index.search(fake_vector(question), limit)

    def test_finds_code_by_meaning_without_shared_words(self):
        status = self.index.refresh(self.embed, 'teste/modelo')
        self.assertEqual(status['state'], 'ready')
        self.assertEqual(status['files'], 3)
        # "login" não aparece em nenhum ficheiro; o conceito está em auth.py
        self.assertEqual(self.search('onde é feito o login')[0]['path'], 'auth.py')
        self.assertEqual(self.search('invoice')[0]['path'], 'billing.py')
        first = self.search('gerar thumbnail')[0]
        self.assertEqual(first['path'], 'media.py')
        self.assertEqual(first['line'], 1)
        self.assertIn('miniatura', first['excerpt'])
        self.assertFalse(first['stale'])
        self.assertGreater(first['score'], 0.5)

    def test_secret_files_are_never_sent_to_the_model(self):
        self.index.refresh(self.embed, 'teste/modelo')
        self.assertFalse(any('segredo-que-nao-pode-sair' in text or text.startswith('.env') for text in self.embed.texts))

    def test_refresh_is_incremental(self):
        self.index.refresh(self.embed, 'teste/modelo')
        sent = len(self.embed.texts)
        status = self.index.refresh(self.embed, 'teste/modelo')
        self.assertEqual(len(self.embed.texts), sent, 'nada mudou: não se pede nenhum vetor')
        self.assertEqual(status['embedded'], 0)
        (self.root / 'billing.py').write_text('def emitir(cliente, total):\n    """Cria a fatura, aplica o desconto e regista o pagamento."""\n    return gravar(cliente, total)\n', encoding='utf-8')
        self.index.refresh(self.embed, 'teste/modelo')
        new = self.embed.texts[sent:]
        self.assertEqual(len(new), 1)
        self.assertTrue(new[0].startswith('billing.py'))

    def test_deleted_file_leaves_the_index(self):
        self.index.refresh(self.embed, 'teste/modelo')
        (self.root / 'media.py').unlink()
        status = self.index.refresh(self.embed, 'teste/modelo')
        self.assertEqual(status['files'], 2)
        self.assertNotIn('media.py', [row['path'] for row in self.search('thumbnail', 5)])

    def test_changing_model_discards_old_vectors(self):
        self.index.refresh(self.embed, 'teste/modelo-a')
        sent = len(self.embed.texts)
        status = self.index.refresh(self.embed, 'teste/modelo-b')
        self.assertEqual(len(self.embed.texts), sent * 2, 'vetores de outro modelo não se comparam: recalcula tudo')
        self.assertEqual(status['signature'], 'teste/modelo-b')

    def test_changed_file_is_reported_as_stale_until_reindexed(self):
        self.index.refresh(self.embed, 'teste/modelo')
        (self.root / 'auth.py').write_text('# reescrito depois da indexação\n' * 3, encoding='utf-8')
        first = self.search('login')[0]
        self.assertEqual(first['path'], 'auth.py')
        self.assertTrue(first['stale'])
        self.assertNotIn('excerpt', first)

    def test_budget_limits_one_refresh_and_keeps_files_whole(self):
        for number in range(6):
            (self.root / f'extra{number}.py').write_text(f'def tarefa_{number}():\n    return "valor {number} com texto suficiente"\n', encoding='utf-8')
        with patch.object(code_semantic, 'MAX_CHUNKS_PER_REFRESH', 4):
            status = self.index.refresh(self.embed, 'teste/modelo')
        self.assertEqual(status['embedded'], 4)
        self.assertEqual(status['pending'], 5)
        self.assertTrue(status['truncated'])
        status = self.index.refresh(self.embed, 'teste/modelo')  # a atualização seguinte continua
        self.assertEqual(status['pending'], 0)
        self.assertEqual(status['files'], 9)

    def test_cancel_stops_between_batches(self):
        cancel = threading.Event()
        cancel.set()
        status = self.index.refresh(self.embed, 'teste/modelo', cancel=cancel)
        self.assertTrue(status['cancelled'])
        self.assertEqual(self.embed.calls, 0)
        self.assertEqual(status['state'], 'not_indexed')

    def test_app_data_of_a_loose_conversation_is_never_indexed_or_sent(self):
        """Numa conversa solta a pasta de trabalho é a pasta de dados da app: o histórico não é código."""
        from code_context import CodeIndex
        root = self.meta  # pasta de metadados == pasta de trabalho
        (root / 'script.py').write_text('def miniatura(ficheiro):\n    """Redimensionar a imagem para o thumbnail."""\n    return ficheiro\n', encoding='utf-8')
        (root / 'conversation.json').write_text('[{"role": "user", "text": "mensagem privada do utilizador"}]', encoding='utf-8')
        (root / 'conversation-info.json').write_text('{"title": "titulo privado"}', encoding='utf-8')
        (root / 'history.json').write_text('[{"prompt": "pedido privado"}]', encoding='utf-8')
        (root / 'attachments').mkdir()
        (root / 'attachments' / 'nota.txt').write_text('anexo privado do utilizador com texto', encoding='utf-8')
        (root / 'turn-runs').mkdir()
        (root / 'turn-runs' / 'registo.json').write_text('{"comando": "registo privado de execucao"}', encoding='utf-8')
        index = SemanticIndex(root, root)
        status = index.refresh(self.embed, 'teste/modelo')
        self.assertEqual(status['files'], 1)
        self.assertEqual({text.split('\n', 1)[0] for text in self.embed.texts}, {'script.py'})
        self.assertFalse(any('privad' in text for text in self.embed.texts))
        lexical = CodeIndex(root, root).search('privada mensagem utilizador titulo')
        self.assertEqual(lexical['results'], [])
        # num projeto (metadados numa subpasta própria) um ficheiro do utilizador com o mesmo nome conta
        (self.root / 'history.json').write_text('{"nota": "ficheiro do projeto do utilizador"}', encoding='utf-8')
        project = SemanticIndex(self.meta / 'sub', self.root)
        (self.meta / 'sub').mkdir()
        project.refresh(self.embed, 'teste/modelo')
        self.assertTrue(any(text.startswith('history.json') for text in self.embed.texts))

    def test_long_file_is_split_into_overlapping_chunks(self):
        text = '\n'.join(f'linha {n} com algum conteudo' for n in range(1, 101))
        parts = code_semantic.chunks(text)
        self.assertEqual(parts[0][0], 1)
        self.assertEqual(parts[0][1], code_semantic.CHUNK_LINES)
        self.assertEqual(parts[1][0], code_semantic.CHUNK_LINES - code_semantic.CHUNK_OVERLAP + 1)
        self.assertEqual(parts[-1][1], 100)
        self.assertEqual(code_semantic.chunks('x\n'), [])


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class EmbeddingsRequestTest(unittest.TestCase):
    PROVIDER = {'kind': 'openai', 'base_url': 'https://exemplo.test/v1', 'api_key': 'sk-teste-123'}

    def test_posts_openai_format_and_restores_order(self):
        payload = {'data': [{'index': 1, 'embedding': [0, 1]}, {'index': 0, 'embedding': [1, 0]}]}
        with patch('providers.multi.request', return_value=FakeResponse(payload)) as request:
            vectors = embeddings.embed(self.PROVIDER, 'modelo-emb', ['a', 'b'])
        self.assertEqual(vectors, [[1.0, 0.0], [0.0, 1.0]])
        provider, method, path, body = request.call_args.args
        self.assertEqual((method, path), ('POST', '/embeddings'))
        self.assertEqual(body, {'model': 'modelo-emb', 'input': ['a', 'b']})

    def test_rejects_providers_without_this_api_and_bad_answers(self):
        with self.assertRaises(ProviderError):
            embeddings.embed({'kind': 'anthropic', 'api_key': 'x'}, 'm', ['a'])
        with self.assertRaises(ProviderError):
            embeddings.embed(self.PROVIDER, '', ['a'])
        for payload in ({'data': []}, {'data': [{'index': 0, 'embedding': []}]}, {'error': 'x'},
                        {'data': [{'index': 0, 'embedding': [1]}, {'index': 1, 'embedding': [1, 2]}]}):
            with patch('providers.multi.request', return_value=FakeResponse(payload)):
                with self.assertRaises(ProviderError):
                    embeddings.embed(self.PROVIDER, 'm', ['a', 'b'] if len(payload.get('data', [])) == 2 else ['a'])
        self.assertEqual(embeddings.embed(self.PROVIDER, 'm', []), [])


class SemanticApiTest(unittest.TestCase):
    """Ponte: definições, indexação em segundo plano, pesquisa e ferramenta do agente."""

    def setUp(self):
        import time

        import api
        import config
        self.time = time
        self.config = config
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        base = Path(self.temp.name).resolve()
        self.settings = base / 'settings'
        self.settings.mkdir()
        self.patches = [patch('config.application_root', return_value=base / 'app'), patch('config.config_dir', return_value=self.settings),
                        patch('providers.embeddings.embed', side_effect=lambda provider, model, texts: [fake_vector(text) for text in texts])]
        self.embed = None
        for item in self.patches:
            started = item.start()
            self.embed = started
        self.app = api.Api()
        self.assertTrue(self.app.get_state()['ok'])  # cria a conversa ativa
        cfg = config.load_config()
        cfg['providers'] = [
            {'id': 'local', 'name': 'Ollama', 'kind': 'ollama', 'base_url': 'http://localhost:11434/v1', 'api_key': '',
             'models': [], 'catalog': [{'id': 'nomic-embed-text', 'categories': ['embeddings']}, {'id': 'llama3', 'categories': ['chat']}]},
            {'id': 'nuvem', 'name': 'OpenAI', 'kind': 'openai', 'base_url': '', 'api_key': 'sk-segredo-999', 'models': [], 'catalog': []},
            {'id': 'claude', 'name': 'Anthropic', 'kind': 'anthropic', 'base_url': '', 'api_key': 'sk-ant-x', 'models': [], 'catalog': []},
        ]
        config.save_config(cfg)
        self.meta, self.root = config.resolve_context(config.load_config())
        (self.root / 'auth.py').write_text('def verificar_senha(utilizador, senha):\n    """Autenticar o utilizador com a password guardada."""\n    return comparar(utilizador, senha)\n', encoding='utf-8')
        (self.root / 'billing.py').write_text('def emitir(cliente, total):\n    """Cria a fatura e regista o pagamento do cliente."""\n    return gravar(cliente, total)\n', encoding='utf-8')

    def tearDown(self):
        job = getattr(self.app, '_semantic_job', None)
        if job and job.get('_thread'):
            job['_thread'].join(timeout=10)
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def wait_job(self):
        deadline = self.time.time() + 20
        while self.time.time() < deadline:
            job = self.app.get_semantic_search()['job']
            if job and job['state'] != 'running':
                return job
            self.time.sleep(0.05)
        self.fail('a indexação não terminou')

    def enable(self, provider_id='local', model_id='nomic-embed-text'):
        result = self.app.set_semantic_search({'enabled': True, 'provider_id': provider_id, 'model_id': model_id})
        self.assertTrue(result['ok'], result)
        return result

    def test_is_off_by_default_and_lists_only_compatible_providers(self):
        state = self.app.get_semantic_search()
        self.assertTrue(state['ok'], state)
        self.assertEqual(state['settings'], {'enabled': False, 'provider_id': '', 'model_id': ''})
        self.assertEqual([p['id'] for p in state['providers']], ['local', 'nuvem'])
        self.assertEqual(state['providers'][0]['models'], ['nomic-embed-text'])
        self.assertTrue(state['providers'][0]['local'])
        self.assertFalse(state['providers'][1]['local'])
        self.assertNotIn('sk-segredo-999', str(state))
        self.assertEqual(state['index']['state'], 'not_indexed')
        # desligada: não indexa nem pesquisa, e nada é enviado
        self.assertFalse(self.app.start_semantic_index()['ok'])
        self.assertFalse(self.app.search_semantic('login')['ok'])
        self.embed.assert_not_called()

    def test_index_then_search_by_meaning(self):
        self.enable()
        self.assertIn('Indexa primeiro', self.app.search_semantic('login')['error'])
        started = self.app.start_semantic_index()
        self.assertTrue(started['ok'], started)
        job = self.wait_job()
        self.assertEqual(job['state'], 'done', job)
        found = self.app.search_semantic('onde é feito o login')
        self.assertTrue(found['ok'], found)
        self.assertEqual(found['results'][0]['path'], 'auth.py')
        self.assertEqual(self.app.get_semantic_search()['index']['files'], 2, 'só os dois ficheiros do utilizador; os dados da conversa ficam de fora')
        # mudar de modelo invalida o índice até se indexar de novo
        self.enable(model_id='outro-modelo')
        self.assertIn('outro modelo', self.app.search_semantic('login')['error'])
        self.assertTrue(self.app.clear_semantic_index()['ok'])
        self.assertEqual(self.app.get_semantic_search()['index']['state'], 'not_indexed')

    def test_agent_tool_only_exists_when_ready(self):
        tools = [{'function': {'name': 'codigo_contexto'}}, {'function': {'name': 'codigo_semantico'}}]
        ctx = {'on': True, 'base': str(self.root), '_guidance_root': str(self.root)}
        names = lambda: [t['function']['name'] for t in self.app._semantic_filter_tools(self.config.load_config(), ctx, tools)]  # noqa: E731
        self.assertEqual(names(), ['codigo_contexto'])
        self.enable()
        self.assertEqual(names(), ['codigo_contexto'], 'ligada mas ainda sem índice')
        self.app.start_semantic_index()
        self.wait_job()
        self.assertEqual(names(), ['codigo_contexto', 'codigo_semantico'])
        steps = []
        answer = json.loads(self.app._semantic_tool({'pesquisa': 'invoice', 'limite': 2}, ctx, self.meta, steps))
        self.assertEqual(answer['results'][0]['path'], 'billing.py')
        self.assertEqual(steps[0]['title'], 'codigo_semantico')
        self.app.set_semantic_search({'enabled': False})
        self.assertEqual(names(), ['codigo_contexto'])
        self.assertIn('error', json.loads(self.app._semantic_tool({'pesquisa': 'invoice'}, ctx, self.meta, [])))

    def test_provider_failure_ends_job_with_error_and_hides_key(self):
        self.enable(provider_id='nuvem', model_id='text-embedding-3-small')
        self.embed.side_effect = RuntimeError('falhou com a chave sk-segredo-999')
        self.assertTrue(self.app.start_semantic_index()['ok'])
        job = self.wait_job()
        self.assertEqual(job['state'], 'error')
        self.assertNotIn('sk-segredo-999', job['message'])
        self.assertEqual(self.app.get_semantic_search()['index']['state'], 'not_indexed')

    def test_settings_validation(self):
        self.assertFalse(self.app.set_semantic_search({'provider_id': 'nao-existe'})['ok'])
        self.enable(provider_id='claude')
        self.assertIn('não tem embeddings', self.app.start_semantic_index()['error'])
        self.enable(provider_id='local', model_id='')
        self.assertIn('modelo de embeddings', self.app.start_semantic_index()['error'])


if __name__ == '__main__':
    unittest.main()
