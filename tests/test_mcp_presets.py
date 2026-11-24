import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import api
import config
import integration_catalog as ic


class PresetTests(unittest.TestCase):
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
        config.save_config(config.default_config())
        self.app = api.Api()

    def tearDown(self):
        self.app._mcp.close()
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_catalog_is_opt_in_remote_node_or_bundled(self):
        result = self.app.get_mcp_presets()
        self.assertTrue(result["ok"], result)
        presets = result["presets"]
        self.assertEqual(len(presets), len(ic.CATALOG))
        self.assertTrue(all(p["mode"] in ("remote", "node", "bundled") for p in presets))
        self.assertTrue(all(not p["server_id"] for p in presets))
        catalog = self.app.get_tool_catalog()
        self.assertTrue(catalog["ok"], catalog)
        self.assertEqual(presets, catalog["mcp_presets"])

    def test_save_remote_preset_links_and_removes(self):
        result = self.app.save_mcp_preset("linear", {"enabled": False, "approval": "auto", "oauth_scope": "read"})
        self.assertTrue(result["ok"], result)
        server_id = result["server_id"]
        self.assertTrue(server_id)
        server = config.load_config()["mcp_servers"][0]
        self.assertEqual(server["preset"], "linear")
        self.assertEqual(server["url"], "https://mcp.linear.app/mcp")
        self.assertEqual(server["auth_mode"], "oauth")
        self.assertEqual(server["oauth_scope"], "read")
        self.assertFalse(server["enabled"])
        self.assertEqual(server["approval"], "auto")
        result_presets = self.app.get_mcp_presets()
        self.assertTrue(result_presets["ok"], result_presets)
        preset = next(item for item in result_presets["presets"] if item["kind"] == "linear")
        self.assertEqual(preset["server_id"], server_id)
        self.assertEqual(preset["server"]["name"], "Linear")
        self.assertTrue(self.app.remove_mcp_server(server_id)["ok"])
        self.assertEqual(config.load_config()["mcp_servers"], [])

    def test_manual_preset_keeps_headers_out_of_public_catalog(self):
        result = self.app.save_mcp_preset(
            "github",
            {"enabled": False, "auth_mode": "manual", "headers": {"Authorization": "Bearer private-token"}},
        )
        self.assertTrue(result["ok"], result)
        encoded = json.dumps(result)
        self.assertNotIn("private-token", encoded)
        server = config.load_config()["mcp_servers"][0]
        self.assertEqual(server["headers"]["Authorization"], "Bearer private-token")
        self.assertEqual(result["servers"][0]["header_names"], ["Authorization"])

    def test_profile_is_validated(self):
        self.assertTrue(self.app.set_preference("mcp_profile", "coding")["ok"])
        self.assertEqual(config.load_config()["preferences"]["mcp_profile"], "coding")
        self.assertFalse(self.app.set_preference("mcp_profile", "nope")["ok"])
        self.assertEqual(config.load_config()["preferences"]["mcp_profile"], "coding")

    def test_google_requires_credentials_file(self):
        result = self.app.save_mcp_preset("google_drive", {})
        self.assertFalse(result["ok"])
        self.assertIn("Ficheiro JSON", result["error"])

    def test_google_credentials_are_stored_as_non_secret_settings(self):
        credentials = self.root / "google.json"
        credentials.write_text(json.dumps({"installed": {"client_id": "x"}}), encoding="utf-8")
        with patch("integration_catalog.node_executable", return_value="node"), \
                patch("integration_catalog.installed", return_value=True), \
                patch("integration_catalog.entry_path", return_value=Path("C:/fake/dist/index.js")):
            result = self.app.save_mcp_preset(
                "google_drive", {"credentials_path": str(credentials), "enabled": False}
            )
        self.assertTrue(result["ok"], result)
        cfg = config.load_config()
        self.assertEqual(
            cfg["mcp_preset_settings"]["google_drive"]["credentials_path"],
            str(credentials.resolve()),
        )
        server = cfg["mcp_servers"][0]
        self.assertEqual(server["transport"], "stdio")
        self.assertEqual(server["command"], "node")
        self.assertIn("GOOGLE_DRIVE_OAUTH_CREDENTIALS", result["servers"][0]["env_names"])
        self.assertNotIn(str(credentials), json.dumps(result["servers"]))

    def test_node_component_integrity_is_checked(self):
        item = ic.CATALOG["playwright"]
        runtime = self.root / "runtime"
        folder = runtime / "node_modules" / item["package"]
        folder.mkdir(parents=True)
        (folder / "package.json").write_text(json.dumps({"version": item["version"]}), encoding="utf-8")
        (folder / item["entry"]).write_text("", encoding="utf-8")
        lock = {"packages": {"node_modules/" + item["package"]: {"integrity": "sha512-errado"}}}
        lock_path = runtime / "package-lock.json"
        lock_path.write_text(json.dumps(lock), encoding="utf-8")
        self.assertFalse(ic._installed_in("playwright", runtime))
        lock["packages"]["node_modules/" + item["package"]]["integrity"] = item["integrity"]
        lock_path.write_text(json.dumps(lock), encoding="utf-8")
        self.assertTrue(ic._installed_in("playwright", runtime))


if __name__ == "__main__":
    unittest.main()
