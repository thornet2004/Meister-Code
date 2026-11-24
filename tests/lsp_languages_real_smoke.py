"""Servidores LSP verdadeiros das linguagens acrescentadas a 18/11/2026: HTML, CSS, JSON, Bash, YAML e PHP.

Arranca cada servidor instalado em ``Ferramentas/_Runtime/lsp`` sobre um projeto temporário e confere
diagnósticos, símbolos e (onde existem) definições e referências. No fim olha para as ligações TCP de
cada processo: nenhum deve ter falado com a rede. Não faz parte da suite (demora ~40 s e precisa dos
pacotes npm instalados). Correr: ``python tests/lsp_languages_real_smoke.py``.
"""
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from coding_lsp import LanguageServers  # noqa: E402

FILES = {
    'pagina.html': '<!doctype html>\n<html><head><style>p { colr: red; }</style></head>\n<body><h1 id="a">Olá</h1><p>texto</body></html>\n',
    'estilo.css': '.caixa { colr: red; }\n.outra { color: blue \n',
    'bom.css': '.caixa { color: red; }\n',
    'dados.json': '{"a": 1, "b": [1, 2,], }\n',
    'bom.json': '{"nome": "x", "itens": [1, 2]}\n',
    'remoto.json': '{"$schema": "https://json.schemastore.org/package.json", "name": 5}\n',
    'bom.sh': '#!/bin/bash\nsaudar() {\n  echo "ola $1"\n}\nsaudar mundo\n',
    'config.yaml': 'nome: x\nitens:\n  - a\n   - b\nchave: [1, 2\n',
    'bom.yaml': 'nome: x\nitens:\n  - a\n  - b\n',
    'codigo.php': '<?php\nfunction saudar(string $nome): string {\n    return "ola " . $nome;\n}\necho saudar("mundo");\n$x = ;\n',
    'bom.php': '<?php\nfunction dobro(int $n): int {\n    return $n * 2;\n}\necho dobro(21);\n',
}


def connections(pid):
    if sys.platform != 'win32':
        return None
    command = "Get-NetTCPConnection -OwningProcess %d -ErrorAction SilentlyContinue | Select-Object RemoteAddress,RemotePort | ConvertTo-Json -Compress" % pid
    return subprocess.run(['powershell', '-NoProfile', '-Command', command], capture_output=True, text=True, timeout=30).stdout.strip()


def main():
    report = {}
    with tempfile.TemporaryDirectory(prefix='meistercode-lsp-') as tmp:
        root = Path(tmp).resolve()
        for name, text in FILES.items():
            (root / name).write_text(text, encoding='utf-8')
        lsp = LanguageServers()
        missing = [row['name'] for row in lsp.status() if row['source'] == 'bundled' and not row['installed']]
        assert not missing, 'servidores por instalar: %s' % missing
        try:
            def diagnose(name):
                result = lsp.diagnose(root, root / name, timeout=20)
                assert result['status'] == 'complete', (name, result)
                return result

            def messages(name):
                return [(d['line'], d['severity'], d['message']) for d in diagnose(name)['diagnostics']]

            def symbols(name):
                return [row['name'] for row in lsp.navigate(root, root / name, 'symbols')['results']]

            # CSS: erro de sintaxe e propriedade desconhecida; ficheiro bom sem diagnósticos
            css = messages('estilo.css')
            assert any(severity == 'error' for _line, severity, _text in css) and any('colr' in text for _line, _severity, text in css), css
            assert messages('bom.css') == [], 'CSS correto não devia ter diagnósticos'
            assert symbols('estilo.css')[:2] == ['.caixa', '.outra']
            # HTML: valida o CSS embutido e dá a estrutura; diz que não valida a estrutura
            html = diagnose('pagina.html')
            assert any('colr' in d['message'] for d in html['diagnostics']), html
            assert 'estrutura do HTML' in html['limits']
            assert 'h1#a' in symbols('pagina.html')
            # JSON: vírgulas a mais; bom sem diagnósticos; esquema remoto não é descarregado
            assert [text for _line, _severity, text in messages('dados.json')] == ['Trailing comma', 'Trailing comma']
            assert messages('bom.json') == []
            remote = messages('remoto.json')
            assert not any('Incorrect type' in text for _line, _severity, text in remote), ('o esquema remoto foi aplicado?', remote)
            assert symbols('bom.json')[:2] == ['nome', 'itens']
            # YAML
            assert any(severity == 'error' for _line, severity, _text in messages('config.yaml'))
            assert messages('bom.yaml') == []
            assert symbols('bom.yaml')[:2] == ['nome', 'itens']
            # Bash: navegação; diagnósticos só com shellcheck (a app avisa quando falta)
            bash = diagnose('bom.sh')
            assert symbols('bom.sh') == ['saudar']
            assert [row['line'] for row in lsp.navigate(root, root / 'bom.sh', 'definitions', 5, 2)['results']] == [2]
            assert sorted(row['line'] for row in lsp.navigate(root, root / 'bom.sh', 'references', 5, 2)['results']) == [2, 5]
            # PHP
            assert any(severity == 'error' and line == 6 for line, severity, _text in messages('codigo.php'))
            assert messages('bom.php') == []
            assert 'dobro' in symbols('bom.php')
            assert [row['line'] for row in lsp.navigate(root, root / 'bom.php', 'definitions', 5, 7)['results']] == [2]
            assert sorted(row['line'] for row in lsp.navigate(root, root / 'bom.php', 'references', 5, 7)['results']) == [2, 5]
            time.sleep(3)
            network = {client.kind: connections(client.process.pid) for client in lsp.clients.values()}
            assert sorted(network) == ['bash', 'css', 'html', 'json', 'php', 'yaml'], network
            if sys.platform == 'win32':
                assert not any(network.values()), ('um servidor abriu ligações de rede', network)
            report = dict(css=css, html=[d['message'] for d in html['diagnostics']], remote_schema=remote, bash_limits=bash.get('limits', ''), network=network)
        finally:
            lsp.close()
    print(json.dumps(report, ensure_ascii=False, indent=1))
    print('PASS: real HTML, CSS, JSON, YAML, Bash and PHP servers - diagnostics, symbols, definitions/references, no TCP connections.')


if __name__ == '__main__':
    main()
