"""Fotografia da ponte js_api: métodos públicos da classe ``Api`` e parâmetros.

Segue a regra do pywebview (``inject_pywebview``/``get_functions``): entra tudo
o que ``dir()`` mostra, não começa por ``_`` e é função. Serve para provar que
uma reorganização do código não mudou o que a interface consegue chamar.

Uso:
    python tests/bridge_snapshot.py guardar <ficheiro.json>
    python tests/bridge_snapshot.py comparar <ficheiro.json>
"""
import inspect
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def snapshot() -> dict:
    import api

    functions = {}
    for name in dir(api.Api):
        if name.startswith('_'):
            continue
        attr = getattr(api.Api, name)
        if inspect.isfunction(attr):
            spec = inspect.getfullargspec(attr)
            functions[name] = {
                'params': spec.args[1:],
                'defaults': [repr(value) for value in (spec.defaults or ())],
            }
    return functions


def main(argv) -> int:
    if len(argv) != 3 or argv[1] not in ('guardar', 'comparar'):
        print(__doc__)
        return 2
    path = Path(argv[2])
    current = snapshot()
    if argv[1] == 'guardar':
        path.write_text(json.dumps(current, ensure_ascii=False, indent=1, sort_keys=True), encoding='utf-8')
        print(f'{len(current)} métodos guardados em {path}')
        return 0
    saved = json.loads(path.read_text(encoding='utf-8'))
    missing = sorted(set(saved) - set(current))
    added = sorted(set(current) - set(saved))
    changed = sorted(name for name in set(saved) & set(current) if saved[name] != current[name])
    print(f'antes: {len(saved)} métodos; agora: {len(current)}')
    for label, names in (('em falta', missing), ('novos', added), ('com parâmetros diferentes', changed)):
        if names:
            print(f'{label}: {names}')
    if missing or added or changed:
        return 1
    print('ponte idêntica')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
