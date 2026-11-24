"""Acesso remoto (``remote_control.py``): servidor HTTP verdadeiro em 127.0.0.1, com uma ``Api`` de faz-de-conta.

O ensaio com a ``Api`` verdadeira, a janela e um modelo de ensaio está em ``tests/ui_live_smoke.py``;
a página do telemóvel é ensaiada por ``tests/remote-control-ui.cjs``.
"""
import json
import time
import unittest
from unittest.mock import patch

import requests

import remote_control
from remote_control_fake import build

HEADERS = {'X-MeisterCode': '1', 'Content-Type': 'application/json'}


class Base(unittest.TestCase):
    def setUp(self):
        self.api, self.remote = build()
        info = self.remote.start(0, '127.0.0.1')
        self.base = 'http://127.0.0.1:%d' % info['port']
        self.addCleanup(self.remote.stop)

    def post(self, session, path, body, headers=HEADERS):
        return session.post(self.base + path, data=json.dumps(body), headers=headers, timeout=10)

    def paired(self):
        session = requests.Session()
        reply = self.post(session, '/api/pair', dict(code=self.remote.code))
        self.assertEqual((reply.status_code, reply.json()), (200, dict(ok=True)))
        return session

    def events(self, session, after=0, until=None, timeout=10):
        seen, deadline = [], time.time() + timeout
        while time.time() < deadline:
            data = session.get(self.base + '/api/events?after=%d' % after, timeout=40).json()
            seen += data['events']
            after = data['last']
            if until and any(event['kind'] == until for event in seen):
                break
        return seen


class PairingTests(Base):
    def test_off_until_started_and_gone_when_stopped(self):
        _api, idle = build()
        self.assertEqual((idle.status()['running'], idle.status()['code'], idle.status()['urls']), (False, '', []))
        session = self.paired()
        self.assertEqual(session.get(self.base + '/api/state', timeout=10).status_code, 200)
        self.remote.stop()
        self.assertEqual(self.remote.status()['devices'], [])
        try:  # a porta fechou; uma ligação que tivesse ficado aberta só responde «desligado»
            self.assertEqual(session.get(self.base + '/api/state', timeout=3).status_code, 503)
        except requests.ConnectionError:
            pass
        with self.assertRaises(requests.ConnectionError):
            requests.get(self.base + '/api/state', timeout=3)
        again = self.remote.start(0, '127.0.0.1')
        self.assertNotEqual(again['code'], '')
        self.assertEqual(requests.get('http://127.0.0.1:%d/api/state' % again['port'], cookies=session.cookies, timeout=10).status_code, 401, 'as sessões antigas não sobrevivem a desligar')

    def test_everything_but_the_page_needs_a_paired_device(self):
        anonymous = requests.Session()
        page = anonymous.get(self.base + '/', timeout=10)
        self.assertEqual(page.status_code, 200)
        self.assertIn('Emparelhar este dispositivo', page.text)
        self.assertNotIn(self.remote.code, page.text)
        self.assertIn("script-src 'self'", page.headers['Content-Security-Policy'])
        self.assertEqual((page.headers['X-Frame-Options'], page.headers['Cache-Control']), ('DENY', 'no-store'))
        self.assertEqual(anonymous.get(self.base + '/app.js', timeout=10).status_code, 200)
        for path in ('/api/state', '/api/conversation', '/api/events?after=0'):
            reply = anonymous.get(self.base + path, timeout=10)
            self.assertEqual((reply.status_code, reply.json().get('pair')), (401, True), path)
        for path in ('/api/chat', '/api/select', '/api/new', '/api/stop', '/api/approval'):
            self.assertEqual(self.post(anonymous, path, dict(text='olá')).status_code, 401, path)
        self.assertEqual(self.api.conversations['c1'][-1]['role'], 'assistant', 'nada chegou à app')
        forged = requests.get(self.base + '/api/state', cookies={remote_control.COOKIE: 'adivinhado'}, timeout=10)
        self.assertEqual(forged.status_code, 401)

    def test_code_is_single_use_and_wrong_codes_lock_pairing(self):
        first = self.remote.code
        self.assertRegex(first, r'^[A-Z2-9]{4}-[A-Z2-9]{4}$')
        session = requests.Session()
        self.assertEqual(self.post(session, '/api/pair', dict(code=first.lower().replace('-', ' '))).status_code, 200, 'aceita minúsculas e sem hífen')
        cookie = session.cookies.get_dict()[remote_control.COOKIE]
        self.assertGreaterEqual(len(cookie), 40)
        raw = self.post(requests.Session(), '/api/pair', dict(code=self.remote.code)).headers['Set-Cookie']
        self.assertIn('HttpOnly', raw)
        self.assertIn('SameSite=Strict', raw)
        self.assertNotEqual(self.remote.code, first)
        self.assertEqual(self.post(requests.Session(), '/api/pair', dict(code=first)).status_code, 403, 'o código usado já não serve')
        self.assertEqual(len(self.remote.status()['devices']), 2)
        self.assertTrue(any('remoteControlChanged' in script for script in self.api.scripts), 'a janela da app é avisada de cada dispositivo')
        before = self.remote.code
        for _ in range(remote_control.MAX_FAILURES - 1):  # já houve uma falha acima
            self.assertEqual(self.post(requests.Session(), '/api/pair', dict(code='AAAA-AAAA')).json()['error'], 'Código errado.')
        self.assertNotEqual(self.remote.code, before, 'depois de cinco erros o código muda')
        locked = self.post(requests.Session(), '/api/pair', dict(code=self.remote.code))
        self.assertEqual(locked.status_code, 403)
        self.assertIn('Demasiadas tentativas', locked.json()['error'])
        self.assertGreater(self.remote.status()['locked'], 0)
        self.assertEqual(session.get(self.base + '/api/state', timeout=10).status_code, 200, 'quem já estava emparelhado continua')
        with patch.object(remote_control.time, 'time', return_value=time.time() + remote_control.LOCK_SECONDS + 1):
            self.assertEqual(self.post(requests.Session(), '/api/pair', dict(code=self.remote.code)).status_code, 200)

    def test_device_limit(self):
        for _ in range(remote_control.MAX_SESSIONS):
            self.paired()
        refused = self.post(requests.Session(), '/api/pair', dict(code=self.remote.code))
        self.assertEqual(refused.status_code, 403)
        self.assertIn('dispositivos', refused.json()['error'])

    def test_requests_from_other_pages_are_refused(self):
        session = self.paired()
        cases = dict(sem_cabecalho={'Content-Type': 'application/json'}, formulario={'X-MeisterCode': '1', 'Content-Type': 'text/plain'},
                     outra_origem=dict(HEADERS, Origin='http://evil.example'))
        for label, headers in cases.items():
            self.assertEqual(self.post(session, '/api/chat', dict(text='apaga tudo'), headers).status_code, 403, label)
        self.assertEqual(self.post(session, '/api/chat', dict(text='olá'), dict(HEADERS, Origin=self.base)).status_code, 200, 'a própria página pode')
        self.assertEqual(session.post(self.base + '/api/chat', data='{não é json', headers=HEADERS, timeout=10).status_code, 400)
        self.assertEqual(session.post(self.base + '/api/chat', data='[1]', headers=HEADERS, timeout=10).status_code, 400)
        before = len(self.api.conversations['c1'])
        try:  # recusado sem ler o corpo: o cliente vê 413 ou a ligação cortada a meio do envio
            self.assertEqual(requests.post(self.base + '/api/chat', data='x' * (remote_control.MAX_BODY + 1), headers=HEADERS, cookies=session.cookies, timeout=10).status_code, 413)
        except requests.ConnectionError:
            pass
        time.sleep(0.3)
        self.assertEqual(len(self.api.conversations['c1']), before, 'o pedido recusado não chegou à app')


class RemoteUseTests(Base):
    def test_only_the_listed_addresses_exist_and_nothing_private_leaves(self):
        session = self.paired()
        for path in ('/api/get_state', '/api/terminal_run', '/api/add_provider', '/web/app.js', '/../app.py', '/remote_control.py'):
            self.assertEqual(session.get(self.base + path, timeout=10).status_code, 404, path)
            self.assertEqual(self.post(session, path, {}).status_code, 404, path)
        state = session.get(self.base + '/api/state', timeout=10).json()
        self.assertEqual(sorted(state), ['active_conversation_id', 'active_project_id', 'app_version', 'approval', 'busy', 'conversations', 'last', 'ok', 'projects', 'stream'])
        self.assertEqual(state['projects'], [dict(id='p1', name='Projeto Um')], 'sem caminhos do disco')
        conversation = session.get(self.base + '/api/conversation', timeout=10).json()
        text = json.dumps(dict(state=state, conversation=conversation))
        for private in ('sk-nao-pode-sair', 'C:/Users/alguem', 'segredo'):
            self.assertNotIn(private, text)
        self.assertEqual(conversation['messages'][1], dict(role='assistant', text='Olá! <b>não é HTML</b>', steps=[dict(title='ler_ficheiro', ok=True)], media=['image'], files=[], error=False, created_at=''))

    def test_chat_streams_and_the_desktop_window_is_told(self):
        session = self.paired()
        self.assertEqual(self.post(session, '/api/chat', dict(text='  ')).json()['ok'], False)
        self.assertEqual(self.post(session, '/api/chat', dict(text='x' * (remote_control.MAX_TEXT + 1))).json()['ok'], False)
        self.assertEqual(self.post(session, '/api/chat', dict(text='conta-me uma coisa')).json(), dict(ok=True))
        events = self.events(session, until='done')
        self.assertEqual([event['kind'] for event in events], ['busy', 'stream_start', 'stream', 'stream', 'stream_end', 'done'])
        self.assertEqual(''.join(event['data'] for event in events if event['kind'] == 'stream'), 'Resposta a: conta-me uma coisa')
        self.assertEqual(events[-1]['data'], '')
        self.assertEqual([event['seq'] for event in events], list(range(events[0]['seq'], events[0]['seq'] + 6)))
        last = session.get(self.base + '/api/conversation', timeout=10).json()['messages'][-2:]
        self.assertEqual([(m['role'], m['text']) for m in last], [('user', 'conta-me uma coisa'), ('assistant', 'Resposta a: conta-me uma coisa')])
        scripts = [script for script in self.api.scripts if 'remoteConversationChanged' in script]
        self.assertEqual(len(scripts), 2, 'a janela mostra a mensagem do telemóvel e recarrega no fim')
        self.assertIn('"conta-me uma coisa"', scripts[0])
        self.assertEqual((self.remote.busy, self.remote.stream), (False, ''))
        self.post(session, '/api/chat', dict(text='isto falha'))
        self.assertEqual(self.events(session, after=events[-1]['seq'], until='done')[-1]['data'], 'O provedor recusou.')

    def test_one_answer_at_a_time_and_stop(self):
        self.api.delay = 0.6
        session = self.paired()
        self.assertTrue(self.post(session, '/api/chat', dict(text='demora')).json()['ok'])
        self.assertIn('em curso', self.post(session, '/api/chat', dict(text='outra')).json()['error'])
        self.assertIn('Espera', self.post(session, '/api/select', dict(kind='conversation', id='c2')).json()['error'])
        self.assertIn('Espera', self.post(session, '/api/new', {}).json()['error'])
        self.assertTrue(session.get(self.base + '/api/state', timeout=10).json()['busy'])
        self.assertEqual(self.post(session, '/api/stop', {}).json(), dict(ok=True))
        self.events(session, until='done')
        self.assertEqual(self.api.conversations['c1'][-1]['text'], '[interrompido]')

    def test_approval_card_can_be_answered_from_the_phone(self):
        session = self.paired()
        self.post(session, '/api/chat', dict(text='corre um comando'))
        events = self.events(session, until='approval')
        card = next(event['data'] for event in events if event['kind'] == 'approval')
        self.assertEqual((card['id'], card['category'], card['detail']), ('a1', 'dangerous', 'Remove-Item -Recurse C:\\tudo'))
        self.assertEqual(session.get(self.base + '/api/state', timeout=10).json()['approval']['id'], 'a1', 'quem se liga a meio vê o cartão')
        for bad in (dict(id='a1', decision='session'), dict(id='outro', decision='allow'), dict(id=5, decision='allow'), {}):
            self.assertFalse(self.post(session, '/api/approval', bad).json()['ok'], bad)
        self.assertEqual(self.post(session, '/api/approval', dict(id='a1', decision='deny')).json(), dict(ok=True))
        rest = self.events(session, after=events[-1]['seq'], until='done')
        self.assertIn('approval_done', [event['kind'] for event in rest])
        self.assertEqual(self.api.conversations['c1'][-1]['text'], 'Comando recusado.')
        self.assertIsNone(self.remote.approval)
        self.assertFalse(self.post(session, '/api/approval', dict(id='a1', decision='allow')).json()['ok'], 'um cartão já respondido não se responde outra vez')

    def test_switching_and_messages_typed_on_the_desktop(self):
        session = self.paired()
        self.assertEqual(self.post(session, '/api/select', dict(kind='conversation', id='c2')).json(), dict(ok=True))
        self.assertEqual((self.api.active, session.get(self.base + '/api/conversation', timeout=10).json()['messages']), ('c2', []))
        self.assertEqual(self.post(session, '/api/select', dict(kind='project', id='p1')).json(), dict(ok=True))
        self.assertEqual(session.get(self.base + '/api/state', timeout=10).json()['active_project_id'], 'p1')
        for bad in (dict(kind='conversation', id='nao-existe'), dict(kind='ficheiro', id='c1'), dict(kind='conversation', id=''), dict(kind='conversation')):
            self.assertFalse(self.post(session, '/api/select', bad).json()['ok'], bad)
        self.assertEqual(self.post(session, '/api/new', {}).json(), dict(ok=True))
        self.assertEqual(self.api.active, 'c3')
        start = self.remote.hub.sequence
        # uma mensagem escrita na janela da app: o telemóvel é avisado do princípio e do fim
        self.remote.turn_started()
        self.assertTrue(session.get(self.base + '/api/state', timeout=10).json()['busy'])
        self.assertIn('em curso', self.post(session, '/api/chat', dict(text='ao mesmo tempo')).json()['error'])
        self.remote.stream_start()
        self.remote.stream_text('da janela')
        self.assertEqual(session.get(self.base + '/api/state', timeout=10).json()['stream'], 'da janela')
        self.remote.stream_end()
        self.remote.turn_finished()
        self.assertEqual([event['kind'] for event in self.events(session, after=start, until='done')], ['busy', 'stream_start', 'stream', 'stream_end', 'done'])

    def test_a_device_that_fell_behind_is_told_to_reload(self):
        with patch.object(remote_control, 'EVENT_LIMIT', 5):
            session = self.paired()
            for index in range(12):
                self.remote.hub.publish('stream', str(index))
            data = session.get(self.base + '/api/events?after=2', timeout=10).json()
            self.assertTrue(data['reload'])
            self.assertEqual(len(data['events']), 5)
            self.assertFalse(session.get(self.base + '/api/events?after=%d' % (data['last'] - 1), timeout=10).json()['reload'])
            self.assertEqual(session.get(self.base + '/api/events?after=lixo', timeout=10).json()['ok'], True)

    def test_addresses_never_offer_loopback(self):
        with patch.object(remote_control.socket, 'getaddrinfo', return_value=[(2, 1, 6, '', ('127.0.0.1', 0)), (2, 1, 6, '', ('192.168.1.20', 0)), (2, 1, 6, '', ('10.8.0.2', 0)), (2, 1, 6, '', ('169.254.3.4', 0))]):
            urls = remote_control.addresses(8765)
        self.assertIn('http://192.168.1.20:8765/', urls)
        self.assertIn('http://10.8.0.2:8765/', urls, 'o endereço da VPN também aparece')
        self.assertFalse(any('127.' in url or '169.254.' in url for url in urls))


if __name__ == '__main__':
    unittest.main()
