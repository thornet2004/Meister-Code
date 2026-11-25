import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import api
from agent_runtime import READ_TOOLS
from knowledge_store import KnowledgeStore
from tool_catalog import LOCAL_TOOLS


class KnowledgeStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.meta = Path(self.temp.name).resolve() / ".studio"
    def tearDown(self): self.temp.cleanup()

    def test_save_search_read_forget_and_idempotent_title(self):
        store = KnowledgeStore(self.meta)
        a = store.save("Função de login", "Fica em 0x401000, chama validar_senha", "auth,login", "funcao", "0x401000")
        self.assertFalse(a["atualizada"]); self.assertIsInstance(a["id"], int)
        store.save("Strings suspeitas", "senha=, admin, debug", "strings", "nota", "")
        found = store.search("login")["notas"]
        hit = [n for n in found if n["id"] == a["id"]]
        self.assertTrue(hit and isinstance(hit[0]["trecho"], str))
        full = store.read(a["id"])
        self.assertTrue(full["encontrada"]); self.assertIn("validar_senha", full["nota"]["texto"])
        again = store.save("Função de login", "Afinal chama hash_senha", "auth", "funcao", "0x401000")  # mesmo título: atualiza
        self.assertTrue(again["atualizada"]); self.assertEqual(again["id"], a["id"])
        self.assertEqual(len(store.search()["notas"]), 2)
        self.assertIn("hash_senha", store.read(a["id"])["nota"]["texto"])
        self.assertNotIn("validar_senha", store.read(a["id"])["nota"]["texto"])
        store.save("Login (renomeada)", note_id=a["id"])  # atualizar por id
        self.assertEqual(store.read(a["id"])["nota"]["titulo"], "Login (renomeada)")
        self.assertTrue(store.forget(a["id"])["apagada"])
        self.assertFalse(store.read(a["id"])["encontrada"])
        self.assertEqual(len(store.search()["notas"]), 1)

    def test_contexts_are_separate_and_empty_is_safe(self):
        KnowledgeStore(self.meta / "um").save("Nota A", "texto")
        self.assertEqual(KnowledgeStore(self.meta / "dois").search()["notas"], [])
        self.assertFalse(KnowledgeStore(self.meta / "vazio").read(1)["encontrada"])
        self.assertFalse(KnowledgeStore(self.meta / "vazio").forget(1)["apagada"])

    def test_query_with_fts_special_chars_does_not_crash(self):
        store = KnowledgeStore(self.meta)
        store.save("Teste", "conteúdo com ligação e outros termos")
        self.assertIsInstance(store.search('ligação AND (NEAR* "')["notas"], list)

    def test_empty_title_rejected_and_bad_id(self):
        store = KnowledgeStore(self.meta)
        with self.assertRaises(ValueError): store.save("   ")
        with self.assertRaises(ValueError): store.read("abc")
        with self.assertRaises(ValueError): store.save("Nova", note_id=999999)

    def test_tools_registered_and_read_permissions(self):
        for name in ("conhecimento_guardar", "conhecimento_procurar", "conhecimento_ler", "conhecimento_apagar"):
            self.assertIn(name, LOCAL_TOOLS)
        self.assertIn("conhecimento_procurar", READ_TOOLS)
        self.assertIn("conhecimento_ler", READ_TOOLS)
        self.assertNotIn("conhecimento_guardar", READ_TOOLS)

    def test_semantic_search_ranks_by_vector(self):
        store = KnowledgeStore(self.meta)
        store.save("Alvo", "assunto A", vector=[1.0, 0.0, 0.0], signature="emb:x/m")
        store.save("Outro", "assunto B", vector=[0.0, 1.0, 0.0], signature="emb:x/m")
        res = store.search("", limit=5, query_vector=[0.9, 0.1, 0.0], signature="emb:x/m")["notas"]
        self.assertEqual(res[0]["titulo"], "Alvo")
        self.assertIn("semelhanca", res[0])
        outra = store.search("", limit=5, query_vector=[1.0, 0.0, 0.0], signature="emb:outra")["notas"]
        self.assertFalse(any("semelhanca" in n for n in outra))  # assinatura diferente não entra na semântica

    def test_migrates_old_db_without_vector_columns(self):
        self.meta.mkdir(parents=True, exist_ok=True)
        import sqlite3
        con = sqlite3.connect(self.meta / "knowledge.sqlite")
        con.executescript("CREATE TABLE notes(id INTEGER PRIMARY KEY AUTOINCREMENT,titulo TEXT NOT NULL,texto TEXT NOT NULL DEFAULT '',"
                          "etiquetas TEXT NOT NULL DEFAULT '',tipo TEXT NOT NULL DEFAULT '',ref TEXT NOT NULL DEFAULT '',criado REAL NOT NULL,atualizado REAL NOT NULL);")
        con.commit(); con.close()
        store = KnowledgeStore(self.meta)
        saved = store.save("Nota", "texto", vector=[1.0, 0.0], signature="emb:x")  # tem de migrar e aceitar o vetor
        self.assertIn("id", saved)
        self.assertTrue(store.read(saved["id"])["encontrada"])

    def test_dispatch_routes_knowledge_tools(self):
        settings = self.meta / "settings"; settings.mkdir(parents=True)
        with patch("config.config_dir", return_value=settings), patch("config.application_root", return_value=self.meta / "app"):
            app = api.Api(); app._window = MagicMock()
            proj = self.meta / "proj"
            ctx = {"base": str(proj), "scope": "project", "on": True}
            saved = json.loads(app._dispatch_local_tool("conhecimento_guardar", {"titulo": "Alvo", "texto": "detalhe secreto"}, [], ctx, str(proj), str(proj)))
            self.assertIn("id", saved)
            found = json.loads(app._dispatch_local_tool("conhecimento_procurar", {"consulta": "secreto"}, [], ctx, str(proj), str(proj)))
            self.assertTrue(any(n["titulo"] == "Alvo" for n in found["notas"]))


if __name__ == "__main__": unittest.main()
