import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import api
import config


class ManagedStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.base = Path(self.temp.name).resolve()
        self.app_root = self.base / "app"
        self.settings = self.base / "settings"
        self.settings.mkdir()
        self.patches = [patch("config.application_root", return_value=self.app_root), patch("config.config_dir", return_value=self.settings)]
        for item in self.patches:
            item.start()
        self.app = api.Api()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_creation_and_remove_only_from_list(self):
        state = self.app.create_conversation("Conversa guardada")
        self.assertTrue(state["ok"], state)
        conv = state["conversations"][0]
        folder = Path(conv["path"])
        self.assertEqual(folder.parent, self.app_root / "Conversas")
        (folder / "anexo.txt").write_text("conteudo", encoding="utf-8")
        self.assertTrue((folder / "conversation-info.json").exists())
        self.assertTrue(self.app.delete_conversation(conv["id"], False)["ok"])
        self.assertTrue((folder / "anexo.txt").exists())
        self.assertNotIn(conv["id"], [c["id"] for c in config.load_config()["conversations"]])
        state = self.app.create_project("O meu projeto")
        self.assertTrue(state["ok"], state)
        project = next(p for p in state["projects"] if p["id"] == state["active_project_id"])
        folder = Path(project["path"])
        self.assertEqual(folder.parent, self.app_root / "Projectos")
        self.assertTrue((folder / ".studio" / "project-info.json").exists())
        self.assertTrue(self.app.delete_project(project["id"], False)["ok"])
        self.assertTrue(folder.exists())
        replacement = self.app.create_project("O meu projeto")
        self.assertNotEqual(replacement["active_project_id"], project["id"])

    def test_remove_from_disk_and_failed_recycle_keeps_entry(self):
        def recycle(path):
            source = Path(path).resolve()
            self.assertIn(self.app_root, source.parents)
            source.rename(source.with_name(source.name + "-recycled"))
            return "trash"

        for kind in ("conversation", "project"):
            state = getattr(self.app, "create_" + kind)("Teste")
            key = "conversations" if kind == "conversation" else "projects"
            active = state["active_conversation_id" if kind == "conversation" else "active_project_id"]
            entry = next(x for x in state[key] if x["id"] == active)
            folder = Path(entry["path"])
            with patch("api_workspaces._dispose_folder", side_effect=OSError("Recycle failure")):
                result = getattr(self.app, "delete_" + kind)(active, True)
            self.assertFalse(result["ok"])
            self.assertTrue(folder.exists())
            self.assertIn(active, [x["id"] for x in config.load_config()[key]])
            with patch("api_workspaces._dispose_folder", side_effect=recycle):
                result = getattr(self.app, "delete_" + kind)(active, True)
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["deleted_files"], "trash")
            self.assertFalse(folder.exists())

    def test_migration_preserves_original_and_rebases_paths(self):
        old = self.settings / "conversations" / "old-conv"
        old.mkdir(parents=True)
        media = old / "image.png"
        media.write_bytes(b"original media")
        config._write_json(old / "conversation.json", [{"role": "assistant", "media": [{"path": str(media)}]}])
        project = self.base / "legacy-project"
        (project / ".studio").mkdir(parents=True)
        (project / "code.py").write_text("print(42)", encoding="utf-8")
        config._write_json(project / ".studio" / "history.json", [{"path": str(project / "code.py")}])
        cfg = config.default_config()
        cfg["conversations"] = [{"id": "old-conv", "title": "Antiga"}]
        cfg["projects"] = [{"id": "old-project", "name": "Antigo", "path": str(project)}]
        config._write_json(config.config_path(), cfg)
        migrated = config.load_config()
        new = self.app_root / "Conversas" / "old-conv"
        self.assertEqual((new / "image.png").read_bytes(), media.read_bytes())
        data = json.loads((new / "conversation.json").read_text(encoding="utf-8"))
        self.assertEqual(data[0]["media"][0]["path"], str(new / "image.png"))
        new_project = Path(migrated["projects"][0]["path"])
        self.assertEqual(new_project.parent, self.app_root / "Projectos")
        self.assertTrue((project / "code.py").exists())
        self.assertTrue((new_project / "code.py").exists())
        self.assertTrue(config.config_path().with_name("config.before-managed-storage.json").exists())
        self.assertEqual(config.load_config()["projects"], migrated["projects"])
        self.app.delete_conversation("old-conv", False)
        self.assertNotIn("old-conv", [c["id"] for c in config.load_config()["conversations"]])

    def test_migration_keeps_missing_project_and_still_starts(self):
        missing = self.base / "pasta-que-ja-nao-existe"
        cfg = config.default_config()
        cfg["projects"] = [{"id": "gone", "name": "Apagado", "path": str(missing)}]
        cfg["active_project_id"] = "gone"
        config._write_json(config.config_path(), cfg)
        migrated = config.load_config()
        self.assertEqual(migrated["storage_layout"], 2)
        self.assertEqual(migrated["projects"][0]["path"], str(missing))
        self.assertEqual(
            migrated["projects"][0]["migration_error"],
            "A pasta original já não existe.",
        )
        state = self.app.get_state()
        self.assertTrue(state["ok"], state)
        self.assertFalse(state["projects"][0]["exists"])
        self.assertIn("migration_error", state["projects"][0])

    def test_metadata_writes_only_changed_items(self):
        state = self.app.create_conversation("A")
        self.assertTrue(state["ok"], state)
        cfg = config.load_config()
        with patch("config._write_json", wraps=config._write_json) as writer:
            config.save_config(cfg)
            paths = [str(call.args[0]) for call in writer.call_args_list]
        self.assertFalse(any(path.endswith("conversation-info.json") for path in paths))
        cfg["conversations"][0]["title"] = "B"
        with patch("config._write_json", wraps=config._write_json) as writer:
            config.save_config(cfg)
            paths = [str(call.args[0]) for call in writer.call_args_list]
        self.assertTrue(any(path.endswith("conversation-info.json") for path in paths))

    def test_no_automatic_thirty_conversation_limit(self):
        cfg = config.default_config()
        for i in range(35):
            self.app._new_conv_entry(cfg, str(i))
        self.assertEqual(len(cfg["conversations"]), 35)


if __name__ == "__main__":
    unittest.main()
