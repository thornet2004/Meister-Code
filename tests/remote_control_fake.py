"""Uma ``Api`` de faz-de-conta para ensaiar o acesso remoto sem modelos nem janela.

Usada por ``test_remote_control.py`` e, como programa, por ``remote-control-ui.cjs``:
    python tests/remote_control_fake.py     → escreve uma linha JSON com ``url`` e ``code`` e fica a servir até receber uma linha no stdin
"""
import json
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import remote_control  # noqa: E402

PAGE = Path(__file__).resolve().parents[1] / 'web' / 'remote'


class FakeApi:
    """Guarda conversas em memória; uma resposta chega em bocados e, se a mensagem pedir, passa por um cartão de aprovação."""

    def __init__(self, delay=0.0):
        self.delay = delay
        self.scripts = []          # o que a app mandaria executar na janela
        self.active = 'c1'
        self.project = ''
        self.conversations = {'c1': [dict(role='user', text='olá', media=[], files=[]), dict(role='assistant', text='Olá! <b>não é HTML</b>', steps=[dict(title='ler_ficheiro', ok=True, body='segredo')],
                                                                                           media=[dict(path='C:/Users/alguem/imagem.png', type='image')], files=[])], 'c2': []}
        self.approvals = {}
        self.cancelled = threading.Event()
        self.remote = None

    def _stream_js(self, script):
        self.scripts.append(script)

    def get_state(self):
        return dict(ok=True, app_version='0.0.0', active_project_id=self.project, active_conversation_id=self.active, providers=[dict(name='segredo', api_key='sk-nao-pode-sair')],
                    projects=[dict(id='p1', name='Projeto Um', path='C:/Users/alguem/projeto')], conversations=[dict(id=key, title='Conversa ' + key) for key in self.conversations])

    def get_conversation(self):
        return dict(ok=True, messages=list(self.conversations[self.active]))

    def set_active_conversation(self, ident):
        if ident not in self.conversations:
            return dict(ok=False, error='Conversa não encontrada.')
        self.active, self.project = ident, ''
        return dict(ok=True)

    def set_active_project(self, ident):
        if ident != 'p1':
            return dict(ok=False, error='Projeto não encontrado.')
        self.project = ident
        return dict(ok=True)

    def create_conversation(self, _title):
        ident = 'c%d' % (len(self.conversations) + 1)
        self.conversations[ident] = []
        self.active, self.project = ident, ''
        return dict(ok=True)

    def cancel_chat(self):
        self.cancelled.set()
        return dict(ok=True)

    def respond_approval(self, ident, decision):
        record = self.approvals.get(ident)
        if record:
            record['decision'] = decision
            record['event'].set()
        return dict(ok=True)

    def chat(self, text, _attachments):
        conversation = self.conversations[self.active]
        conversation.append(dict(role='user', text=text, media=[], files=[]))
        if 'falha' in text:
            return dict(ok=False, error='O provedor recusou.')
        self.cancelled.clear()
        self.remote.stream_start()
        answer = 'Resposta a: ' + text
        if 'comando' in text:
            record = dict(event=threading.Event(), decision=None)
            self.approvals['a1'] = record
            self.remote.approval_asked(dict(id='a1', category='dangerous', summary='Comando perigoso', detail='Remove-Item -Recurse C:\\tudo'))
            record['event'].wait(20)
            self.remote.approval_done('a1')
            answer = 'Comando executado.' if record['decision'] == 'allow' else 'Comando recusado.'
        for piece in (answer[:6], answer[6:]):
            if self.cancelled.is_set():
                answer = '[interrompido]'
                break
            time.sleep(self.delay)
            self.remote.stream_text(piece)
        self.remote.stream_end()
        conversation.append(dict(role='assistant', text=answer, media=[], files=[], steps=[]))
        return dict(ok=True)


def build(delay=0.0, store_path=None):
    api = FakeApi(delay)
    if store_path is None:  # isolado: cada rig de ensaio com o seu ficheiro, fora do APPDATA do utilizador
        store_path = Path(tempfile.mkdtemp()) / 'remote_devices.json'
    remote = remote_control.RemoteControl(api, PAGE, store_path=store_path)
    api.remote = remote
    return api, remote


if __name__ == '__main__':
    _api, _remote = build(delay=0.4)
    info = _remote.start(0, '127.0.0.1')
    print(json.dumps(dict(url='http://127.0.0.1:%d/' % info['port'], code=info['code'])), flush=True)
    for line in sys.stdin:  # cada linha pede o código atual (muda depois de cada emparelhamento); «fim» termina
        if line.strip() == 'fim':
            break
        print(json.dumps(dict(code=_remote.status()['code'])), flush=True)
    _remote.stop()
