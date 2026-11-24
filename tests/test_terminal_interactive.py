"""Terminal interativo (terminal_interactive.InteractiveShell) com PowerShell real."""
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from terminal_interactive import InteractiveShell


@unittest.skipUnless(sys.platform == 'win32', 'requer Windows e PowerShell')
class InteractiveShellTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.cwd = str(Path(self.folder.name).resolve())
        self.shell = InteractiveShell()
        self.cursor = 0

    def tearDown(self):
        self.shell.close()
        self.folder.cleanup()

    def collect(self, until, timeout=30):
        """Lê até ``until(estado, texto acumulado)`` ser verdadeiro."""
        text, deadline = '', time.time() + timeout
        while time.time() < deadline:
            state = self.shell.read(self.cursor)
            text += state['output']
            self.cursor = state['cursor']
            if until(state, text):
                return state, text
            time.sleep(0.05)
        self.fail(f'tempo esgotado; saída até agora: {text!r}')

    def run_command(self, command, timeout=30):
        self.shell.send(command, self.cwd)
        return self.collect(lambda state, _text: not state['busy'], timeout)

    def test_output_exit_code_and_persistent_state(self):
        state, text = self.run_command('$x = 41; $x + 1')
        self.assertEqual(text.strip(), '42')
        self.assertEqual(state['exit_code'], 0)
        self.assertEqual(Path(state['cwd']), Path(self.cwd))
        # variáveis e pasta atual mantêm-se entre comandos
        (Path(self.cwd) / 'sub').mkdir()
        state, text = self.run_command('cd sub; $x')
        self.assertEqual(text.strip(), '41')
        self.assertEqual(Path(state['cwd']), Path(self.cwd) / 'sub')
        state, _text = self.run_command('cmd /c exit 7')
        self.assertEqual(state['exit_code'], 7)

    def test_command_echo_is_not_repeated_in_output(self):
        _state, text = self.run_command("Write-Output 'unico'")
        self.assertEqual(text.strip(), 'unico')

    def test_output_arrives_while_command_is_running(self):
        self.shell.send("'primeiro'; Start-Sleep -Seconds 3; 'segundo'", self.cwd)
        state, text = self.collect(lambda _state, text: 'primeiro' in text, timeout=15)
        self.assertTrue(state['busy'], 'a primeira linha tem de chegar antes de o comando acabar')
        self.assertNotIn('segundo', text)
        _state, rest = self.collect(lambda state, _text: not state['busy'])
        self.assertIn('segundo', rest)

    def test_running_program_receives_typed_input(self):
        self.shell.send("python -c \"n=input('nome? '); print('ola', n)\"", self.cwd)
        state, text = self.collect(lambda _state, text: 'nome?' in text)
        self.assertTrue(state['busy'])
        sent = self.shell.send('Rui', self.cwd)
        self.assertEqual(sent['mode'], 'input')
        state, text = self.collect(lambda state, _text: not state['busy'])
        self.assertIn('ola Rui', text)
        self.assertEqual(state['exit_code'], 0)

    def test_multiline_command_is_one_statement(self):
        state, text = self.run_command("$total = 0\nforeach ($n in 1..4) { $total += $n }\n$total")
        self.assertEqual(text.strip(), '10')
        self.assertFalse(state['busy'])

    def test_stop_kills_launched_program_and_keeps_session(self):
        self.run_command('$keep = 5')
        self.shell.send('python -c "import time; time.sleep(60)"', self.cwd)
        self.collect(lambda state, _text: state['busy'], timeout=5)
        time.sleep(1.0)  # dar tempo ao processo filho para arrancar
        started = time.time()
        result = self.shell.stop()
        self.assertEqual(result, {'stopped': True, 'restarted': False})
        self.collect(lambda state, _text: not state['busy'], timeout=20)
        self.assertLess(time.time() - started, 20)
        _state, text = self.run_command('$keep')
        self.assertEqual(text.strip(), '5')

    def test_stop_restarts_session_when_powershell_itself_is_busy(self):
        self.shell.send('Start-Sleep -Seconds 60', self.cwd)
        self.collect(lambda state, _text: state['busy'], timeout=5)
        time.sleep(0.5)
        result = self.shell.stop()
        self.assertEqual(result, {'stopped': True, 'restarted': True})
        state, text = self.collect(lambda state, _text: not state['busy'], timeout=10)
        self.assertIn('sessão interrompida', text)
        self.assertFalse(state['alive'])
        # o envio seguinte abre outra sessão na mesma pasta
        state, text = self.run_command("'de volta'")
        self.assertIn('de volta', text)
        self.assertEqual(Path(state['cwd']), Path(self.cwd))

    def test_read_cursor_returns_only_new_output(self):
        self.run_command("'a'")
        first = self.cursor
        self.run_command("'b'")
        self.assertEqual(self.shell.read(first)['output'].strip(), 'b')
        self.assertEqual(self.shell.read(self.cursor)['output'], '')

    def test_stop_when_idle_does_nothing(self):
        self.run_command("'x'")
        self.assertEqual(self.shell.stop(), {'stopped': False, 'restarted': False})
        self.assertTrue(self.shell.read(0)['alive'])


if __name__ == '__main__':
    unittest.main()
