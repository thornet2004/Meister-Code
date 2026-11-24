"""Ensaio REAL da ferramenta do agente ``ferramenta_instalar`` contra o GitHub verdadeiro (fora da suite).

Chama a ferramenta tal como o agente a chama, com a classe ``Api`` verdadeira, numa pasta temporária:
não toca na configuração nem na pasta ``Ferramentas`` do utilizador, e não chama nenhum modelo.
Usa a API pública do GitHub sem conta (limite: 60 consultas por hora) e descarrega alguns MB.

    python tests/tool_request_real_smoke.py
"""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SOURCE_REPO = 'https://github.com/sharkdp/hexyl'        # só código
RELEASE_REPO = 'https://github.com/BurntSushi/ripgrep'  # ficheiro de uma release
KNOWN_REPO = 'https://github.com/dev-lab/pcb-retrace'   # já está na lista da app


def main() -> int:
    import api
    import config
    import tool_installer
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        (root / 'settings').mkdir()
        tools = root / 'app' / 'Ferramentas'
        asked = []
        with patch('config.config_dir', return_value=root / 'settings'), patch('config.application_root', return_value=root / 'app'):
            config.save_config(config.default_config())
            app = api.Api()

            def call(**args):
                steps = []
                result = json.loads(app._tool_install_tool(args, steps))
                assert steps and steps[0]['ok'] == ('error' not in result), (result, steps)
                return result

            def ask(category, summary, detail):
                asked.append(detail)
                return 'allow'
            try:
                listing = call(acao='listar')
                assert len(listing['ferramentas']) == 45 and all(row['descricao'] for row in listing['ferramentas'])
                print('listar: 45 ferramentas com descrição')

                known = call(acao='consultar', url=KNOWN_REPO)
                assert known['ja_na_lista'] == 'PcbRetrace', known
                print('consultar (já na lista):', known['repositorio'], '->', known['ja_na_lista'])

                info = call(acao='consultar', url=SOURCE_REPO)
                assert len(info['commit']) == 40 and info['licenca'] != '' and not tools.exists(), info
                print('consultar:', info['repositorio'], '| licença', info['licenca'], '| versão', info['versao'], '| commit', info['commit'][:8], '|', len(info['ficheiros_da_release']), 'ficheiros na release')

                refused = call(acao='instalar', url=SOURCE_REPO)
                assert 'não autorizada' in refused['error'] and not tools.exists(), refused
                print('instalar sem janela: recusado, nada escrito')

                with patch.object(app, '_ask_approval', side_effect=ask):
                    source = call(acao='instalar', url=SOURCE_REPO, descricao='Visualizador hexadecimal para o terminal. Serve para inspecionar ficheiros binários.')
                    assert source['estado'] == 'instalada agora', source
                    folder = Path(source['pasta'])
                    assert (folder / 'source' / 'Cargo.toml').is_file() and not (folder / 'downloads').exists(), list(folder.iterdir())
                    print('instalar código:', source['chave'], '->', folder.name + '/source', '(%d ficheiros)' % sum(1 for item in (folder / 'source').rglob('*') if item.is_file()))

                    release = call(acao='consultar', url=RELEASE_REPO)
                    name = next(item['nome'] for item in release['ficheiros_da_release'] if item['nome'].endswith('x86_64-pc-windows-msvc.zip'))
                    binary = call(acao='instalar', url=RELEASE_REPO, ficheiro=name)
                    assert binary['estado'] == 'instalada agora', binary
                    found = sorted(item.name for item in (Path(binary['pasta']) / 'app').rglob('rg.exe'))
                    assert found == ['rg.exe'], found
                    print('instalar ficheiro da release:', binary['chave'], release['versao'], name, '-> rg.exe presente (não executado)')

                    again = call(acao='instalar', url=SOURCE_REPO)
                    assert source['chave'] in again['error'], again
                assert len(asked) == 2 and all(str(tools) in detail and 'nada é executado' in detail for detail in asked), asked
                saved = json.loads((tools / tool_installer.EXTRA_NAME).read_text(encoding='utf-8'))['tools']
                assert [item['key'] for item in saved] == [source['chave'], binary['chave']] and all(len(item['steps'][0]['sha256']) == 64 for item in saved)
                rows = {row['key']: row for row in app.get_tool_updates()['tools']}
                assert len(rows) == 46 and all(rows[item['key']]['status'] == 'installed' and rows[item['key']]['extra'] for item in saved)
                # uma segunda leitura do mesmo commit tem de dar o mesmo SHA-256 (o zip do GitHub é estável)
                import hashlib
                import requests
                second = hashlib.sha256(requests.get(saved[0]['steps'][0]['url'], timeout=60).content).hexdigest()
                assert second == saved[0]['steps'][0]['sha256'], 'o zip do commit mudou entre dois downloads'
                print('lista extra: 2 entradas com commit/release e SHA-256; painel com 46; segundo download com o mesmo SHA-256')
            finally:
                installer = getattr(app, '_tool_installer', None)
                if installer:
                    installer.close()
                app._lsp.close()
                app._mcp.close()
                app._folder_tools.close()
    print('PASS: ferramenta_instalar contra o GitHub verdadeiro')
    return 0


if __name__ == '__main__':
    sys.exit(main())
