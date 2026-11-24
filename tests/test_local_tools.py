import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import api
import config
from local_tools import GraphMemory, git_query, scoped_path, sqlite_run
from tool_catalog import BROWSER_TOOLS, LOCAL_TOOLS


class LocalToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root=Path(self.temp.name).resolve()
    def tearDown(self): self.temp.cleanup()

    def test_sqlite_schema_read_write_and_readonly_protection(self):
        path=self.root/'test.sqlite'
        sqlite_run(path,'CREATE TABLE example(id INTEGER PRIMARY KEY, name TEXT)',write=True)
        sqlite_run(path,'INSERT INTO example(name) VALUES(?)',['Olá'],write=True)
        self.assertEqual(sqlite_run(path,'SELECT name FROM example')['rows'],[{'name':'Olá'}])
        self.assertEqual(sqlite_run(path,'',schema=True)['schema'][0]['columns'][1]['name'],'name')
        with self.assertRaises(sqlite3.OperationalError): sqlite_run(path,'DELETE FROM example')
        with self.assertRaises(sqlite3.DatabaseError): sqlite_run(path,"ATTACH DATABASE ':memory:' AS other")
        self.assertEqual(sqlite_run(path,'SELECT COUNT(*) AS n FROM example')['rows'][0]['n'],1)
        with self.assertRaises(ValueError): scoped_path('../outside.sqlite',{'base':str(self.root),'scope':'project'})

    def test_memory_graph_persists_and_contexts_are_separate(self):
        memory=GraphMemory(self.root/'one')
        memory.save('Projeto','software',['Usa Python'])
        memory.save('SQLite','database',['Base local'])
        memory.relate('Projeto','SQLite','utiliza')
        restored=GraphMemory(self.root/'one').search('Projeto')
        self.assertEqual(restored['entities'][0]['observations'],['Usa Python'])
        self.assertEqual(restored['relations'][0]['label'],'utiliza')
        self.assertEqual(GraphMemory(self.root/'two').search()['entities'],[])
        memory.forget('SQLite')
        self.assertEqual(memory.search()['relations'],[])

    def test_git_status_diff_and_history(self):
        def git(*args):
            subprocess.run(['git','-c','commit.gpgsign=false','-c','core.hooksPath='+str(self.root/'no-hooks'),*args],cwd=self.root,capture_output=True,check=True)
        git('init')
        file=self.root/'code.txt';file.write_text('first\n',encoding='utf-8')
        git('add','code.txt')
        git('-c','user.name=Test','-c','user.email=test@example.invalid','commit','-m','local tools smoke')
        file.write_text('first\nnew\n',encoding='utf-8')
        context={'base':str(self.root),'scope':'project'}
        self.assertIn('code.txt',git_query({'acao':'estado'},context)['output'])
        self.assertIn('+new',git_query({'acao':'diff'},context)['output'])
        self.assertIn('local tools smoke',git_query({'acao':'historico'},context)['output'])

    def test_model_receives_catalog_uses_tool_and_remembers_next_session(self):
        settings=self.root/'settings';settings.mkdir()
        with patch('config.config_dir',return_value=settings),patch('config.application_root',return_value=self.root/'app'):
            cfg=config.load_config()
            cfg['providers']=[{'id':'fake','kind':'openrouter','models':[{'id':'text','type':'chat'}]}]
            cfg['chat']={'provider_id':'fake','model_id':'text'}
            config.save_config(cfg)
            app=api.Api();app._window=MagicMock()
            calls=[]
            def adapter(provider,model,messages,tools,params):
                names={t['function']['name'] for t in tools}
                self.assertTrue(set(BROWSER_TOOLS).issubset(names))
                self.assertTrue(set(LOCAL_TOOLS).issubset(names))
                self.assertIn('sem perguntar',messages[0]['content'])
                calls.append(messages[:])
                if len(calls)==1:
                    raw={'role':'assistant','content':None,'tool_calls':[{'id':'m1','type':'function','function':{'name':'memoria_guardar','arguments':'{"nome":"Preferência","observacoes":["facto duradouro"]}'}}]}
                    return {'content':'','raw_message':raw,'tool_calls':[{'id':'m1','name':'memoria_guardar','arguments':{'nome':'Preferência','observacoes':['facto duradouro']}}]}
                return {'content':'Guardado.','tool_calls':[]}
            with patch('providers.get_chat_adapter',return_value=adapter),patch.object(app,'_ask_approval',side_effect=AssertionError('Unexpected approval')):
                self.assertTrue(app.chat('Lembra isto')['ok'])
            self.assertTrue(any(m['role']=='tool' and 'saved' in m['content'] for m in calls[1]))
            second=api.Api();second._window=MagicMock()
            with patch('providers.get_chat_adapter',return_value=adapter):
                self.assertTrue(second.chat('O que ficou guardado?')['ok'])
            self.assertTrue(any('facto duradouro' in m.get('content','') for m in calls[-1] if m['role']=='system'))
            self.assertTrue(any('Resultados das ferramentas' in (m.get('content') or '') for m in calls[-1] if m['role']=='assistant'))


if __name__=='__main__':unittest.main()
