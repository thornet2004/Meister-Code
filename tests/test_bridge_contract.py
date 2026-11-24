"""A ponte com a interface não pode mudar por acidente.

Compara os métodos públicos de ``api.Api`` (nomes e parâmetros) com a lista
guardada em ``tests/bridge-contract.json``. Ao acrescentar, remover ou alterar
de propósito um método chamado pela interface, atualizar a lista com:

    python tests/bridge_snapshot.py guardar tests/bridge-contract.json
"""
import json
import unittest
from pathlib import Path

from bridge_snapshot import snapshot

CONTRACT = Path(__file__).with_name('bridge-contract.json')


class BridgeContractTest(unittest.TestCase):
    def test_public_methods_match_saved_contract(self):
        saved = json.loads(CONTRACT.read_text(encoding='utf-8'))
        current = snapshot()
        self.assertEqual(sorted(set(saved) - set(current)), [], 'métodos que a interface deixou de poder chamar')
        self.assertEqual(sorted(set(current) - set(saved)), [], 'métodos novos por registar no contrato')
        changed = sorted(name for name in saved if saved[name] != current[name])
        self.assertEqual(changed, [], 'métodos com parâmetros diferentes')


if __name__ == '__main__':
    unittest.main()
