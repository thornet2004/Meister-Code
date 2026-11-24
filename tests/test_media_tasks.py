"""Imagem e vídeo pelo Replicate, fal.ai e Kie.ai (``providers/media_tasks.py``), sem rede.

Os pedidos HTTP são substituídos por um servidor de faz-de-conta que guarda o que recebeu.
Nenhum destes provedores foi chamado de verdade: precisam das chaves do utilizador e gastam créditos.
"""
import json
import unittest
from unittest.mock import patch

import providers
from providers import media_tasks
from providers.base import ProviderError

KEY = 'chave-secreta-123'
PNG = b'\x89PNG dados da imagem'
MP4 = b'\x00\x00\x00\x18ftypmp42 dados do video'


class Reply:
    def __init__(self, data=None, status=200, content=b'', content_type='application/json', text=None):
        self.data, self.status_code, self.content, self.headers = data, status, content, {'Content-Type': content_type}
        self.ok = status < 400
        self.text = text if text is not None else (json.dumps(data) if data is not None else '')

    def json(self):
        if self.data is None:
            raise ValueError('sem JSON')
        return self.data

    def iter_content(self, size):
        for start in range(0, len(self.content), 7):
            yield self.content[start:start + 7]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class Server:
    """Responde por ordem a cada (método, endereço) e regista os pedidos."""

    def __init__(self, replies, files=None):
        self.replies, self.files, self.calls, self.downloads = dict(replies), dict(files or {}), [], []

    def request(self, method, url, headers=None, json=None, timeout=None):
        self.calls.append(dict(method=method, url=url, headers=dict(headers or {}), body=json))
        queue = self.replies.get((method, url))
        if not queue:
            return Reply(dict(detail='não previsto: %s %s' % (method, url)), status=404)
        return queue.pop(0) if len(queue) > 1 else queue[0]

    def get(self, url, stream=None, timeout=None, headers=None):
        self.downloads.append(dict(url=url, headers=dict(headers or {})))
        if url not in self.files:
            return Reply(status=404)
        content, kind = self.files[url]
        return Reply(content=content, content_type=kind)


class Base(unittest.TestCase):
    def run_adapter(self, kind, capability, model_id, server, params=None, prompt='um gato a tocar piano', base_url=''):
        provider = dict(kind=kind, api_key=KEY, base_url=base_url)
        with patch.object(media_tasks.requests, 'request', side_effect=server.request), patch.object(media_tasks.requests, 'get', side_effect=server.get), \
                patch.object(media_tasks, '_sleep') as sleep:
            try:
                return providers.get_adapter(kind, capability)(provider, dict(id=model_id), prompt, params or {})
            finally:
                self.sleeps = sleep.call_count

    def assert_key_only_to(self, server, host):
        for call in server.calls:
            self.assertTrue(call['url'].startswith('https://' + host + '/'), call['url'])
        for download in server.downloads:
            self.assertEqual(download['headers'], {}, 'os ficheiros gerados são descarregados sem a chave')


class ReplicateTests(Base):
    CREATE = 'https://api.replicate.com/v1/models/black-forest-labs/flux-schnell/predictions'
    FOLLOW = 'https://api.replicate.com/v1/predictions/abc123'
    FILE = 'https://replicate.delivery/xezq/saida-0.webp'

    def test_official_model_waits_and_downloads_every_output(self):
        server = Server({('POST', self.CREATE): [Reply(dict(id='abc123', status='starting', urls=dict(get=self.FOLLOW)))],
                         ('GET', self.FOLLOW): [Reply(dict(status='processing')), Reply(dict(status='succeeded', output=[self.FILE, self.FILE + '?2']))]},
                        {self.FILE: (PNG, 'image/webp'), self.FILE + '?2': (PNG + b'2', 'image/webp')})
        files, meta = self.run_adapter('replicate', 'image', 'black-forest-labs/flux-schnell', server, dict(aspect_ratio='16:9', seed=7, resolution='', n=4, _experimental=True, input=dict(num_outputs=2, _privado=1)))
        self.assertEqual((files, meta), ([PNG, PNG + b'2'], dict(ext='webp', media='image')))
        create = server.calls[0]
        self.assertEqual(create['body'], dict(input=dict(prompt='um gato a tocar piano', aspect_ratio='16:9', seed=7, num_outputs=2)), 'só os campos conhecidos e o input do modelo')
        self.assertEqual((create['headers']['Authorization'], create['headers']['Prefer']), ('Bearer ' + KEY, 'wait=30'))
        self.assertEqual(self.sleeps, 2)
        self.assert_key_only_to(server, 'api.replicate.com')

    def test_versioned_model_and_single_output_string(self):
        version = 'a' * 64
        url = 'https://api.replicate.com/v1/predictions'
        server = Server({('POST', url): [Reply(dict(id='abc123', status='succeeded', output=self.FILE, urls=dict(get=self.FOLLOW)))]}, {self.FILE: (MP4, 'video/mp4')})
        files, meta = self.run_adapter('replicate', 'video', 'dono/modelo:' + version, server, dict(duration=5, aspect_ratio='9:16'))
        self.assertEqual((files, meta['ext'], meta['media']), ([MP4], 'mp4', 'video'))
        self.assertEqual(server.calls[0]['body'], dict(version='dono/modelo:' + version, input=dict(prompt='um gato a tocar piano', duration=5, aspect_ratio='9:16')))
        self.assertEqual(len(server.calls), 1, 'já veio concluído: não consulta outra vez')
        self.assertEqual(self.sleeps, 0)

    def test_failures_and_untrusted_answers(self):
        failed = Server({('POST', self.CREATE): [Reply(dict(id='abc123', status='failed', error='NSFW com a %s dentro' % KEY))]})
        with self.assertRaises(ProviderError) as raised:
            self.run_adapter('replicate', 'image', 'black-forest-labs/flux-schnell', failed)
        self.assertIn('failed', str(raised.exception))
        self.assertNotIn(KEY, str(raised.exception))
        # um endereço de consulta noutro servidor é ignorado: a chave não vai para lá
        elsewhere = Server({('POST', self.CREATE): [Reply(dict(id='abc123', status='starting', urls=dict(get='https://evil.example/roubar')))],
                            ('GET', self.FOLLOW): [Reply(dict(status='succeeded', output=self.FILE))]}, {self.FILE: (PNG, 'image/png')})
        self.assertEqual(self.run_adapter('replicate', 'image', 'black-forest-labs/flux-schnell', elsewhere)[0], [PNG])
        self.assert_key_only_to(elsewhere, 'api.replicate.com')
        http = Server({('POST', self.CREATE): [Reply(dict(detail='Unauthenticated ' + KEY), status=401)]})
        with self.assertRaises(ProviderError) as raised:
            self.run_adapter('replicate', 'image', 'black-forest-labs/flux-schnell', http)
        self.assertIn('401', str(raised.exception))
        self.assertNotIn(KEY, str(raised.exception))
        empty = Server({('POST', self.CREATE): [Reply(dict(id='abc123', status='succeeded', output=None))]})
        insecure = Server({('POST', self.CREATE): [Reply(dict(id='abc123', status='succeeded', output='http://sem-https.example/x.png'))]})
        for server in (empty, insecure):
            with self.assertRaises(ProviderError):
                self.run_adapter('replicate', 'image', 'black-forest-labs/flux-schnell', server)
        for bad in ('', 'semdono', '../x/y', 'dono/modelo:curta', 'dono/mod elo', 'a/b?x=1'):
            with self.assertRaises(ProviderError, msg=bad):
                self.run_adapter('replicate', 'image', bad, Server({}))

    def test_waiting_gives_up_and_oversized_files_are_refused(self):
        forever = Server({('POST', self.CREATE): [Reply(dict(id='abc123', status='starting'))], ('GET', self.FOLLOW): [Reply(dict(status='processing'))]})
        with self.assertRaises(ProviderError) as raised:
            self.run_adapter('replicate', 'image', 'black-forest-labs/flux-schnell', forever)
        self.assertIn('Tempo esgotado', str(raised.exception))
        self.assertEqual(self.sleeps, media_tasks.MAX_WAIT['image'] // media_tasks.POLL_INTERVAL)
        big = Server({('POST', self.CREATE): [Reply(dict(id='abc123', status='succeeded', output=self.FILE))]}, {self.FILE: (b'x' * 50, 'image/png')})
        with patch.dict(media_tasks.MAX_BYTES, {'image': 20}):
            with self.assertRaises(ProviderError) as raised:
                self.run_adapter('replicate', 'image', 'black-forest-labs/flux-schnell', big)
        self.assertIn('limite', str(raised.exception))

    def test_model_list_comes_from_the_two_collections(self):
        base = 'https://api.replicate.com/v1/collections/'
        server = Server({('GET', base + 'text-to-image'): [Reply(dict(models=[dict(owner='black-forest-labs', name='flux-schnell', description='Rápido'), dict(owner='x', name='y z'), 'lixo',
                                                                             dict(owner='black-forest-labs', name='flux-schnell')]))],
                         ('GET', base + 'text-to-video'): [Reply(dict(models=[dict(owner='google', name='veo-3')]))]})
        with patch.object(media_tasks.requests, 'request', side_effect=server.request):
            listing = providers.list_models(dict(kind='replicate', api_key=KEY, base_url=''))
        self.assertEqual([(row['id'], row['types']) for row in listing['models']], [('black-forest-labs/flux-schnell', ['image']), ('google/veo-3', ['video'])])
        self.assertFalse(listing['truncated'])
        from providers.catalog import merge
        provider = dict(models=[])
        self.assertEqual(merge(provider, listing['models']), 2, 'o catálogo da app aceita estas linhas')
        self.assertEqual([(m['id'], m['type']) for m in provider['models']], [('black-forest-labs/flux-schnell', 'image'), ('google/veo-3', 'video')])


class FalTests(Base):
    CREATE = 'https://queue.fal.run/fal-ai/flux/schnell'
    STATUS = 'https://queue.fal.run/fal-ai/flux/requests/r1/status'
    RESULT = 'https://queue.fal.run/fal-ai/flux/requests/r1'
    FILE = 'https://v3.fal.media/files/abc/saida.jpeg'

    def job(self, **changes):
        return dict(dict(request_id='r1', status_url=self.STATUS, response_url=self.RESULT, cancel_url=self.RESULT + '/cancel'), **changes)

    def test_queue_flow_for_images_and_video(self):
        server = Server({('POST', self.CREATE): [Reply(self.job())], ('GET', self.STATUS): [Reply(dict(status='IN_QUEUE', queue_position=2)), Reply(dict(status='IN_PROGRESS')), Reply(dict(status='COMPLETED'))],
                         ('GET', self.RESULT): [Reply(dict(images=[dict(url=self.FILE, width=1024, content_type='image/jpeg')], seed=3, prompt='https://nao-e-um-ficheiro.example/'))]},
                        {self.FILE: (PNG, 'application/octet-stream')})
        files, meta = self.run_adapter('fal', 'image', 'fal-ai/flux/schnell', server, dict(aspect_ratio='1:1', input=dict(image_size='square_hd')))
        self.assertEqual((files, meta), ([PNG], dict(ext='jpg', media='image')), 'a extensão vem do endereço quando o tipo não diz nada')
        self.assertEqual(server.calls[0]['body'], dict(prompt='um gato a tocar piano', aspect_ratio='1:1', image_size='square_hd'), 'no fal.ai o input é o próprio corpo')
        self.assertEqual(server.calls[0]['headers']['Authorization'], 'Key ' + KEY)
        self.assertEqual([item['url'] for item in server.downloads], [self.FILE], 'só os campos «url» contam como ficheiros')
        self.assertEqual(self.sleeps, 2)
        self.assert_key_only_to(server, 'queue.fal.run')
        video = Server({('POST', self.CREATE): [Reply(self.job())], ('GET', self.STATUS): [Reply(dict(status='COMPLETED'))], ('GET', self.RESULT): [Reply(dict(video=dict(url=self.FILE.replace('.jpeg', '.bin'))))]},
                       {self.FILE.replace('.jpeg', '.bin'): (MP4, 'video/mp4')})
        self.assertEqual(self.run_adapter('fal', 'video', 'fal-ai/flux/schnell', video), ([MP4], dict(ext='mp4', media='video')))

    def test_errors_and_foreign_tracking_addresses(self):
        failed = Server({('POST', self.CREATE): [Reply(self.job())], ('GET', self.STATUS): [Reply(dict(status='COMPLETED', error='conteúdo recusado', error_type='content_policy'))]})
        with self.assertRaises(ProviderError) as raised:
            self.run_adapter('fal', 'image', 'fal-ai/flux/schnell', failed)
        self.assertIn('conteúdo recusado', str(raised.exception))
        for changes in (dict(status_url='https://evil.example/status'), dict(response_url='http://queue.fal.run/x'), dict(status_url=None)):
            server = Server({('POST', self.CREATE): [Reply(self.job(**changes))]})
            with self.assertRaises(ProviderError, msg=changes):
                self.run_adapter('fal', 'image', 'fal-ai/flux/schnell', server)
            self.assertEqual(len(server.calls), 1, 'não consulta endereços que não sejam do fal.ai')
        invalid = Server({('POST', self.CREATE): [Reply(dict(detail=[dict(msg='field required')]), status=422)]})
        with self.assertRaises(ProviderError) as raised:
            self.run_adapter('fal', 'image', 'fal-ai/flux/schnell', invalid)
        self.assertIn('422', str(raised.exception))
        with patch.object(media_tasks.requests, 'request') as never:
            listing = providers.list_models(dict(kind='fal', api_key=KEY, base_url=''))
            never.assert_not_called()
        self.assertEqual(listing['models'], [])
        self.assertIn('identificador', listing['note'])


class KieTests(Base):
    CREATE = 'https://api.kie.ai/api/v1/jobs/createTask'
    QUERY = 'https://api.kie.ai/api/v1/jobs/recordInfo?taskId=task_z-image_1'
    FILE = 'https://tempfile.kie.example/saida.png'

    def record(self, state, **more):
        return Reply(dict(code=200, msg='success', data=dict(dict(taskId='task_z-image_1', state=state, resultJson='', failCode='', failMsg=''), **more)))

    def test_task_flow(self):
        server = Server({('POST', self.CREATE): [Reply(dict(code=200, msg='success', data=dict(taskId='task_z-image_1')))],
                         ('GET', self.QUERY): [self.record('waiting'), self.record('queuing'), self.record('generating'), self.record('success', resultJson=json.dumps(dict(resultUrls=[self.FILE])))]},
                        {self.FILE: (PNG, 'image/png')})
        files, meta = self.run_adapter('kie', 'image', 'z-image', server, dict(aspect_ratio='4:3'))
        self.assertEqual((files, meta), ([PNG], dict(ext='png', media='image')))
        self.assertEqual(server.calls[0]['body'], dict(model='z-image', input=dict(prompt='um gato a tocar piano', aspect_ratio='4:3')))
        self.assertEqual(server.calls[0]['headers']['Authorization'], 'Bearer ' + KEY)
        self.assertEqual(self.sleeps, 3)
        self.assert_key_only_to(server, 'api.kie.ai')

    def test_errors_arrive_with_http_200(self):
        refused = Server({('POST', self.CREATE): [Reply(dict(code=402, msg='Insufficient credits ' + KEY, data=None))]})
        with self.assertRaises(ProviderError) as raised:
            self.run_adapter('kie', 'image', 'z-image', refused)
        self.assertIn('402', str(raised.exception))
        self.assertNotIn(KEY, str(raised.exception))
        failed = Server({('POST', self.CREATE): [Reply(dict(code=200, msg='success', data=dict(taskId='task_z-image_1')))],
                         ('GET', self.QUERY): [self.record('fail', failCode='500', failMsg='modelo indisponível')]})
        with self.assertRaises(ProviderError) as raised:
            self.run_adapter('kie', 'video', 'z-image', failed)
        self.assertIn('modelo indisponível', str(raised.exception))
        for result in ('isto não é json', '', json.dumps(dict(resultObject={})), json.dumps(['x'])):
            server = Server({('POST', self.CREATE): [Reply(dict(code=200, msg='success', data=dict(taskId='task_z-image_1')))], ('GET', self.QUERY): [self.record('success', resultJson=result)]})
            with self.assertRaises(ProviderError, msg=result):
                self.run_adapter('kie', 'image', 'z-image', server)
        no_task = Server({('POST', self.CREATE): [Reply(dict(code=200, msg='success', data=dict()))]})
        with self.assertRaises(ProviderError):
            self.run_adapter('kie', 'image', 'z-image', no_task)


class RegistrationTests(unittest.TestCase):
    def test_kinds_offer_image_and_video_but_not_chat(self):
        presets = providers.provider_presets()
        for kind in media_tasks.KINDS:
            self.assertEqual(providers.family_caps(kind), dict(image=True, chat=False, video=True, audio=False), kind)
            self.assertTrue(presets[kind]['base_url'].startswith('https://') and presets[kind]['requires_key'], kind)
            with self.assertRaises(ProviderError):
                providers.get_adapter(kind, 'chat')
        self.assertEqual(set(providers._FAMILIES), set(presets))

    def test_key_and_address_are_checked_before_any_request(self):
        with patch.object(media_tasks.requests, 'request') as never:
            for provider in (dict(kind='replicate', api_key='', base_url=''), dict(kind='fal', api_key=KEY, base_url='http://queue.fal.run'), dict(kind='kie', api_key=KEY, base_url='https://user:pass@api.kie.ai/api/v1')):
                with self.assertRaises(ProviderError, msg=provider):
                    providers.get_adapter(provider['kind'], 'image')(provider, dict(id='a/b'), 'x', {})
            never.assert_not_called()


if __name__ == '__main__':
    unittest.main()
