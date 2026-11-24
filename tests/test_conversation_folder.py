"""Numa conversa sem projeto a pasta de trabalho é a pasta da conversa: os dados da app não entram nas listagens."""

import tempfile
import unittest
from pathlib import Path

import chat_messages
import coding_tools
from workspace_snapshot import WorkspaceSnapshot


class ConversationFolderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()

    def tearDown(self):
        self.tmp.cleanup()

    def test_checkpoints_do_not_copy_themselves(self):
        """Visto a 24/11/2026: 6474 ficheiros e 312 MB de checkpoints numa conversa de uma manhã; cada comando demorava 15 s."""
        (self.root / 'conversation.json').write_text('[]', encoding='utf-8')
        (self.root / 'test_cctalk.py').write_text('print(1)', encoding='utf-8')
        (self.root / 'src').mkdir()
        (self.root / 'src' / 'checkpoints').mkdir()
        (self.root / 'src' / 'checkpoints' / 'meu.txt').write_text('do utilizador', encoding='utf-8')
        for name in ('checkpoints', 'command-jobs', 'turn-runs', 'attachments'):
            (self.root / name).mkdir()
            (self.root / name / 'dados.bin').write_bytes(b'x' * 100)
        (self.root / 'code-context.sqlite').write_bytes(b'x')
        (self.root / 'code-context.sqlite-wal').write_bytes(b'x')
        seen = sorted(rel for _path, rel in coding_tools.files(self.root))
        self.assertEqual(seen, ['src/checkpoints/meu.txt', 'test_cctalk.py'], 'só os ficheiros de trabalho; uma pasta «checkpoints» mais abaixo é do utilizador')

        sizes = []
        for round_number in range(3):
            snapshot = WorkspaceSnapshot(self.root, self.root, 'comando %d' % round_number)
            key = snapshot.begin()
            (self.root / 'test_cctalk.py').write_text('print(%d)' % (round_number + 2), encoding='utf-8')
            report = snapshot.finish(key)
            self.assertEqual((report['file_count'], report['skipped']), (1, []))
            sizes.append(sum(1 for item in (self.root / 'checkpoints').rglob('*') if item.is_file()))
        self.assertEqual(sizes[1] - sizes[0], sizes[2] - sizes[1], 'cada checkpoint custa o mesmo: não arrasta os anteriores')

        project = self.root / 'projeto'
        project.mkdir()
        (project / 'checkpoints').mkdir()
        (project / 'checkpoints' / 'modelo.txt').write_text('é do projeto', encoding='utf-8')
        self.assertEqual([rel for _path, rel in coding_tools.files(project)], ['checkpoints/modelo.txt'], 'numa pasta de projeto nada é escondido')

    def test_old_bloated_checkpoint_reports_shrink_when_the_conversation_is_saved(self):
        conv = [dict(role='assistant', text='ok', steps=[dict(kind='checkpoint', title='Checkpoint externo', body='x' * 170000, ok=True), dict(kind='tool', title='ler', body='y' * 9000, ok=True)])]
        chat_messages._save_conversation(conv, self.root)
        saved = chat_messages._load_conversation(self.root)
        self.assertLess(len(saved[0]['steps'][0]['body']), 8100)
        self.assertEqual(len(saved[0]['steps'][1]['body']), 9000, 'os outros passos ficam como estavam')


if __name__ == '__main__':
    unittest.main()
