"""Testes da ferramenta excel_analisar (wrapper da SheetBrain vendorizada)."""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import excel_tool


def _make_xlsx(path):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["Produto", "Vendas"])
    ws.append(["A", 10])
    ws.append(["B", 32])
    wb.save(path)


class ExcelToolTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="excel-tool-")
        self.xlsx = os.path.join(self.dir, "dados.xlsx")
        _make_xlsx(self.xlsx)
        self.compat = {"id": "p", "kind": "openai-compatible", "base_url": "http://127.0.0.1:1/v1", "api_key": ""}
        self.model = {"id": "modelo-x"}

    def test_pergunta_em_falta(self):
        out = excel_tool.analyse(self.xlsx, "  ", self.compat, self.model)
        self.assertFalse(out["ok"])
        self.assertIn("pergunta", out["erro"].lower())

    def test_ficheiro_inexistente(self):
        out = excel_tool.analyse(os.path.join(self.dir, "nada.xlsx"), "total?", self.compat, self.model)
        self.assertFalse(out["ok"])
        self.assertIn("não encontrado", out["erro"].lower())

    def test_extensao_invalida(self):
        txt = os.path.join(self.dir, "x.txt")
        with open(txt, "w", encoding="utf-8") as fh:
            fh.write("x")
        out = excel_tool.analyse(txt, "total?", self.compat, self.model)
        self.assertFalse(out["ok"])
        self.assertIn(".xlsx", out["erro"])

    def test_provedor_nao_compativel_nao_chama_o_modelo(self):
        anthropic = {"id": "a", "kind": "anthropic", "api_key": "k"}
        with patch("sheetbrain.SheetBrain", side_effect=AssertionError("não devia correr")):
            out = excel_tool.analyse(self.xlsx, "total de vendas?", anthropic, self.model)
        self.assertFalse(out["ok"])
        self.assertIn("compatível com OpenAI", out["erro"])

    def test_corrida_feliz_devolve_resposta(self):
        class FakeAgent:
            def __init__(self, path, config=None, total_token_budget=0):
                self.config = config
                # confirma que aponta ao endereço/modelo certos
                assert config.base_url == "http://127.0.0.1:1/v1"
                assert config.deployment == "modelo-x"

            def run(self, question, **kw):
                print("ruído da SheetBrain para o stdout")  # deve ser absorvido
                return {"success": True, "answer": "O total é 42.", "confidence_score": 0.91,
                        "validation_passed": True, "total_iterations": 1, "total_duration": 3.2}

        with patch("sheetbrain.SheetBrain", FakeAgent):
            out = excel_tool.analyse(self.xlsx, "total de vendas?", self.compat, self.model)
        self.assertTrue(out["ok"])
        self.assertEqual(out["resposta"], "O total é 42.")
        self.assertEqual(out["confianca"], 0.91)
        self.assertTrue(out["validado"])
        self.assertEqual(out["modelo"], "modelo-x")

    def test_erro_do_agente_nao_rebenta(self):
        class Boom:
            def __init__(self, *a, **k):
                raise RuntimeError("estoirou")

        with patch("sheetbrain.SheetBrain", Boom):
            out = excel_tool.analyse(self.xlsx, "total?", self.compat, self.model)
        self.assertFalse(out["ok"])
        self.assertIn("estoirou", out["erro"])


if __name__ == "__main__":
    unittest.main()
