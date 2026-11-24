"""Lista de tarefas do agente: armazenamento, ferramenta ``tarefas_definir`` e o que chega à interface."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import api
import config
from code_context import Continuity


class TaskStoreTests(unittest.TestCase):
    def test_set_tasks_replaces_list_keeps_ids_and_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Continuity(tmp)
            store.update('decision', 'Usar SQLite.')
            first = store.set_tasks([dict(text='Ler o código', state='doing'), dict(text='Escrever testes', state='open')])['tasks']
            self.assertEqual([(t['text'], t['state']) for t in first], [('Ler o código', 'doing'), ('Escrever testes', 'open')])
            second = store.set_tasks([dict(text='Ler o código', state='done'), dict(text='Escrever testes', state='doing'), dict(text='Correr a suite', state='open')])['tasks']
            self.assertEqual([t['id'] for t in second[:2]], [t['id'] for t in first], 'a mesma tarefa mantém o ID')
            self.assertEqual([t['state'] for t in second], ['done', 'doing', 'open'])
            self.assertEqual(len(Continuity(tmp).load()['decisions']), 1, 'as decisões não são tocadas')
            self.assertEqual(store.set_tasks([dict(text='Só esta', state='open')])['tasks'][0]['text'], 'Só esta')
            self.assertEqual(store.set_tasks([])['tasks'], [])

    def test_set_tasks_rejects_bad_input_without_changing_the_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Continuity(tmp)
            store.set_tasks([dict(text='Fica', state='open')])
            bad = [
                'texto',
                [dict(text='', state='open')],
                [dict(text='a', state='started')],
                [dict(text='a', state='open'), dict(text='a', state='done')],
                [dict(text='a', state='doing'), dict(text='b', state='doing')],
                ['a'],
                [dict(text='t%d' % i, state='open') for i in range(61)],
            ]
            for items in bad:
                with self.assertRaises(ValueError):
                    store.set_tasks(items)
            self.assertEqual([t['text'] for t in store.load()['tasks']], ['Fica'])

    def test_doing_state_in_single_updates_and_prompt_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Continuity(tmp)
            tasks = store.set_tasks([dict(text='Feita', state='done'), dict(text='Em curso', state='doing')])['tasks']
            store.update('task', 'Em curso', tasks[1]['id'], 'doing')
            records = json.loads(store.prompt().split('\n', 1)[1])['records']['tasks']
            self.assertEqual(records[0]['text'], 'Em curso', 'o que está por fazer vem antes do que está feito')


class TaskToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.project = self.root / 'project'
        self.project.mkdir()
        settings = self.root / 'settings'
        settings.mkdir()
        self.patches = [patch('config.config_dir', return_value=settings), patch('config.application_root', return_value=self.root / 'app')]
        for item in self.patches:
            item.start()
        cfg = config.default_config()
        cfg.update(storage_layout=2, storage_root=str(self.root / 'app'), projects=[dict(id='p', name='Project', path=str(self.project))], active_project_id='p',
                   providers=[dict(id='provider', kind='openrouter', api_key='private-secret', models=[dict(id='model', type='chat')])], chat=dict(provider_id='provider', model_id='model'))
        cfg['preferences']['agent'] = dict(enabled=True, scope='project', approval='auto')
        config.save_config(cfg)
        self.app = api.Api()
        self.pushed = []
        self.stream = patch.object(self.app, '_stream_js', side_effect=self.pushed.append)
        self.stream.start()

    def tearDown(self):
        self.stream.stop()
        jobs = list(self.app._tasks.jobs.values())
        self.app._tasks.close()
        for job in jobs:
            job['done'].wait(3)
        self.app._validations.close()
        self.app._commands.close()
        self.app._lsp.close()
        self.app._mcp.close()
        self.app._folder_tools.close()
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()

    def call(self, name, arguments, cfg=None, ctx=None):
        cfg = cfg or config.load_config()
        ctx = ctx or self.app._agent_context(cfg)
        meta, _ = config.resolve_context(cfg)
        steps = []
        return json.loads(self.app._handle_tool(cfg, dict(name=name, arguments=arguments), [], steps, ctx, meta, self.project)), steps

    def pushed_tasks(self):
        script = self.pushed[-1]
        prefix = 'window.showAgentTasks && window.showAgentTasks('
        self.assertTrue(script.startswith(prefix) and script.endswith(')'), script[:80])
        return json.loads(script[len(prefix):-1])

    def test_tool_saves_the_list_and_shows_it_at_once(self):
        result, steps = self.call('tarefas_definir', dict(tarefas=[dict(texto='Ler o código', estado='em_curso'), dict(texto='Açúcar & <b>', estado='pendente')]))
        self.assertEqual(result, dict(tarefas=[dict(texto='Ler o código', estado='em_curso'), dict(texto='Açúcar & <b>', estado='pendente')], concluidas=0, total=2))
        self.assertEqual([(t['text'], t['state']) for t in self.pushed_tasks()], [('Ler o código', 'doing'), ('Açúcar & <b>', 'open')])
        self.assertTrue(self.pushed[-1].isascii(), 'o que vai para evaluate_js não leva caracteres por escapar')
        self.assertEqual((steps[-1]['kind'], steps[-1]['ok']), ('tasks', True))
        self.assertIn('▶ Ler o código', steps[-1]['body'])
        usage = self.app.get_context_usage()
        self.assertTrue(usage['ok'], usage)
        self.assertEqual([t['state'] for t in usage['tasks']], ['doing', 'open'], 'a lista reaparece ao abrir a conversa')

    def test_tool_errors_are_reported_and_nothing_is_shown(self):
        self.call('tarefas_definir', dict(tarefas=[dict(texto='Fica', estado='pendente')]))
        shown = len(self.pushed)
        for arguments in (dict(), dict(tarefas='x'), dict(tarefas=[dict(texto='a', estado='feito')]), dict(tarefas=[dict(texto='a', estado='em_curso'), dict(texto='b', estado='em_curso')])):
            result, steps = self.call('tarefas_definir', arguments)
            self.assertIn('error', result)
            self.assertFalse(steps[-1]['ok'])
        self.assertEqual(len(self.pushed), shown)
        self.assertEqual([t['text'] for t in self.app.get_context_usage()['tasks']], ['Fica'])

    def test_single_record_tool_also_updates_the_panel(self):
        result, _ = self.call('contexto_registar', dict(tipo='task', texto='Tarefa avulsa'))
        self.assertEqual(result['tasks'][0]['text'], 'Tarefa avulsa')
        self.assertEqual(self.pushed_tasks()[0]['text'], 'Tarefa avulsa')
        self.call('contexto_registar', dict(tipo='task', texto='Tarefa avulsa', id=result['tasks'][0]['id'], estado='doing'))
        self.assertEqual(self.pushed_tasks()[0]['state'], 'doing')

    def test_offered_only_to_the_writing_agent(self):
        cfg = config.load_config()
        names = {t['function']['name'] for t in self.app._available_tools(cfg, self.app._agent_context(cfg), connect=False)}
        self.assertIn('tarefas_definir', names)
        cfg['preferences']['agent_profile'] = 'plan'
        ctx = self.app._agent_context(cfg)
        self.assertNotIn('tarefas_definir', {t['function']['name'] for t in self.app._available_tools(cfg, ctx, connect=False)})
        result, _ = self.call('tarefas_definir', dict(tarefas=[dict(texto='a', estado='pendente')]), cfg, ctx)
        self.assertIn('bloqueada', result['error'])
        cfg = config.load_config()
        child = dict(self.app._agent_context(cfg), subagent=True, readonly=True)
        result, _ = self.call('tarefas_definir', dict(tarefas=[dict(texto='a', estado='pendente')]), cfg, child)
        self.assertIn('bloqueada', result['error'], 'um subagente não mexe na lista da conversa')
        self.assertEqual(self.pushed, [])
        self.assertEqual(self.app.get_context_usage()['tasks'], [])


class InterfaceIdTests(unittest.TestCase):
    def test_index_html_has_no_duplicate_ids(self):
        # Ao criar o painel da lista usei um id que já era do painel dos subagentes; isto trava a repetição.
        import collections
        import re
        html = (Path(__file__).resolve().parent.parent / 'web' / 'index.html').read_text(encoding='utf-8')
        counts = collections.Counter(re.findall(r'\bid="([^"]+)"', html))
        self.assertEqual([name for name, count in counts.items() if count > 1], [])
        self.assertIn('task-plan', counts)


if __name__ == '__main__':
    unittest.main()
