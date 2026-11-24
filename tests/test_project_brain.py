"""Cérebro do projeto: a app mostra o progresso.md ao agente e diz-lhe para o manter (pedido do user, 24/11/2026)."""

import tempfile
import unittest
from pathlib import Path

import chat_messages
import project_guidance


class ProjectBrainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()

    def tearDown(self):
        self.tmp.cleanup()

    def system(self, **extra):
        ctx = dict(on=True, base=str(self.root), _guidance_root=str(self.root), profile='build', **extra)
        tools = [dict(type='function', function=dict(name='ler_ficheiro', description='', parameters={}))]
        return chat_messages._build_model_messages([dict(role='user', text='olá')], ctx, tools)[0]['content']

    def test_the_agent_is_told_to_keep_a_brain_only_inside_a_project(self):
        self.assertIn('CÉREBRO DO PROJETO', self.system(_project=str(self.root)))
        self.assertNotIn('CÉREBRO DO PROJETO', self.system(), 'sem pasta de projeto (todo o PC, conversa solta) não se criam ficheiros')
        self.assertNotIn('CÉREBRO DO PROJETO', self.system(_project=str(self.root), readonly=True), 'um perfil só de leitura não escreve')

    def test_the_progress_file_is_shown_on_every_request_within_a_limit(self):
        self.assertEqual(project_guidance.progress(self.root), '')
        self.assertNotIn('progresso.md (estado do projeto', self.system(_project=str(self.root)))
        (self.root / 'progresso.md').write_text('# Estado\n- frames cctalk reconstruídos; falta o teste das moedas', encoding='utf-8')
        system = self.system(_project=str(self.root))
        self.assertIn('falta o teste das moedas', system)
        self.assertIn('não instruções do utilizador', system)
        (self.root / 'progresso.md').write_text('x' * 50000, encoding='utf-8')
        text = project_guidance.progress(self.root)
        self.assertLess(len(text), 12100)
        self.assertIn('truncado', text)
        (self.root / 'progresso.md').write_bytes(b'\xff\xfe estado antigo')
        self.assertIn('estado antigo', project_guidance.progress(self.root), 'um ficheiro mal codificado não parte o pedido')


if __name__ == '__main__':
    unittest.main()
