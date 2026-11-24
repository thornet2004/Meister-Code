import base64
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import api
import config
import storage
from terminal import PowerShellSession


class WorkspaceToolsTests(unittest.TestCase):
    def test_powershell_persists_state_and_handles_errors(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "child").mkdir()
            session = PowerShellSession()
            try:
                session.execute("$testValue = 42", folder)
                result = session.execute("Write-Output $testValue", folder)
                self.assertEqual(result["output"].strip(), "42")
                session.execute("Set-Location child", folder)
                self.assertEqual(session.execute("Get-Location", folder)["cwd"], str(root / "child"))
                self.assertFalse(session.execute("Write-Error 'expected error'", folder)["success"])
                self.assertIn("recuperado", session.execute("Write-Output 'recuperado'", folder)["output"])
                self.assertEqual(session.execute("Write-Output 'a'", str(root / "child"))["cwd"], str(root / "child"))
                self.assertEqual(session.execute("Write-Output ([char]0x00e1)", folder)["output"].strip(), "á")
            finally:
                session.close()

    def test_browser_validates_urls_and_has_no_privileged_bridge(self):
        app = api.Api()
        with patch("embedded_browser.EmbeddedBrowser") as browser:
            for url in ("javascript:alert(1)", "file:///C:/Windows", "https://"):
                self.assertFalse(app.open_browser(url)["ok"])
            browser.assert_not_called()
            self.assertTrue(app.open_browser("localhost:3000")["ok"])
            browser.return_value.open.assert_called_once_with("http://localhost:3000")

    def test_attachment_is_saved_with_original_content(self):
        with tempfile.TemporaryDirectory() as folder:
            data = "ficheiro anexado á conversa".encode("utf-8")
            result = api._save_attachments([
                {"name": "teste.txt", "mime": "text/plain", "b64": base64.b64encode(data).decode("ascii")}
            ], folder)
            self.assertEqual(Path(result[0]["path"]).read_bytes(), data)
            self.assertEqual(result[0]["kind"], "text")
            again = api._save_attachments([
                {"name": "teste.txt", "mime": "text/plain", "b64": base64.b64encode(b"second").decode("ascii")}
            ], folder)
            self.assertNotEqual(result[0]["path"], again[0]["path"])
            self.assertEqual(Path(result[0]["path"]).read_bytes(), data)


class StorageAndScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.temp.name).resolve()
        self.settings = self.root / "settings"
        self.app_root = self.root / "app"
        self.settings.mkdir()
        self.app_root.mkdir()
        self.patches = [
            patch("config.config_dir", return_value=self.settings),
            patch("config.application_root", return_value=self.app_root),
        ]
        for item in self.patches:
            item.start()
        self.app = api.Api()

    def tearDown(self):
        self.app._mcp.close()
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_media_read_is_limited_to_managed_folders(self):
        cfg = config.load_config()
        meta_dir, _output = config.resolve_context(cfg)
        media = Path(meta_dir) / "ok.png"
        media.write_bytes(b"PNG")
        self.assertTrue(self.app.get_media(str(media))["ok"])
        outside = self.root / "outside.txt"
        outside.write_text("private", encoding="utf-8")
        result = self.app.get_media(str(outside))
        self.assertFalse(result["ok"])
        self.assertNotIn("private", json.dumps(result))

    def test_storage_does_not_overwrite_same_second(self):
        meta_dir = self.root / "meta"
        output_dir = self.root / "out"
        first = storage.save_media([b"A"], {"prompt": "igual"}, str(output_dir), meta_dir)
        second = storage.save_media([b"B"], {"prompt": "igual"}, str(output_dir), meta_dir)
        self.assertNotEqual(first[0]["path"], second[0]["path"])
        self.assertEqual(Path(first[0]["path"]).read_bytes(), b"A")
        self.assertEqual(Path(second[0]["path"]).read_bytes(), b"B")
        self.assertEqual(len(storage.load_history(meta_dir)), 2)

    def test_set_model_rejects_wrong_type(self):
        cfg = config.load_config()
        cfg["providers"] = [{
            "id": "p", "name": "P", "kind": "openrouter",
            "models": [
                {"id": "img", "type": "image", "name": "I", "defaults": {}},
                {"id": "txt", "type": "chat", "name": "C", "defaults": {}},
            ],
        }]
        config.save_config(cfg)
        result = self.app.set_model("chat", "p", "img")
        self.assertFalse(result["ok"])
        self.assertIn("imagem", result["error"])
        self.assertEqual(config.load_config()["chat"], {})
        self.assertTrue(self.app.set_model("chat", "p", "txt")["ok"])

    def test_generate_passes_explicit_params_over_defaults(self):
        cfg = config.load_config()
        cfg["providers"] = [{
            "id": "p", "name": "P", "kind": "openrouter",
            "models": [{"id": "tts", "type": "audio", "name": "TTS", "defaults": {"voice": "alloy"}}],
        }]
        cfg["audio"] = {"provider_id": "p", "model_id": "tts"}
        seen = {}

        def adapter(provider, model, content, params):
            seen.update(params)
            return [b"audio"], {"ext": "mp3"}

        with patch("providers.get_adapter", return_value=adapter), \
                patch("storage.save_media", return_value=[{"path": str(self.root / "a.mp3"), "media": "audio"}]):
            entries = self.app._run_configured(
                cfg, "audio", "ola", self.root, self.root, {"voice": "nova"}
            )
        self.assertEqual(seen["voice"], "nova")
        self.assertEqual(len(entries), 1)


if __name__ == "__main__":
    unittest.main()
