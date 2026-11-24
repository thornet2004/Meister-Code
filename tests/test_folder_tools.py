import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import api
import config
import folder_tools
from mcp_bridge import redact

ROOT = Path(__file__).resolve().parents[1]


class FolderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.temp.name).resolve()
        self.patches = [patch("config.config_dir", return_value=self.root / "settings"), patch("config.application_root", return_value=self.root / "app")]
        for item in self.patches:
            item.start()
        config.save_config(config.default_config())
        self.app = api.Api()

    def tearDown(self):
        self.app._folder_tools.close()
        self.app._mcp.close()
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def manifest(self, directory=None, name="Demo", approval="auto"):
        folder = (directory or folder_tools.root()) / name
        folder.mkdir(parents=True)
        data = {"version": 1, "name": name, "description": "Uma ferramenta de teste.", "enabled": True, "approval": approval,
                "server": {"transport": "stdio", "command": sys.executable, "args": ["-u", str(ROOT / "mcp_demo.py")], "cwd": "${workspace}", "env": {"TOKEN": "folder-secret-value"}}}
        path = folder / folder_tools.MANIFEST
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def row(self, name="Demo"):
        return next(r for r in folder_tools.scan(config.load_config()) if r["name"] == name)

    def test_folder_discovery_does_not_launch_and_redacts_secrets(self):
        self.manifest()
        with patch("subprocess.Popen", side_effect=AssertionError("Não deve executar ao listar")):
            result = self.app.get_tool_catalog()
        self.assertTrue(result["ok"], result)
        self.assertNotIn("folder-secret-value", json.dumps(result))
        self.assertEqual(len(result["folder_tools"]), 1)
        names = {t["name"] for t in result["tools"]}
        self.assertIn("ferramentas_pesquisar", names)
        self.assertIn("ferramentas_executar", names)

    def test_real_mcp_search_execute_and_disable(self):
        self.manifest()
        sid = self.row()["id"]
        tested = self.app.test_folder_tool(sid)
        self.assertTrue(tested["ok"], tested)
        self.assertEqual(tested["count"], 2)
        empty = self.app._folder_tools.search(config.load_config(), sid)
        self.assertEqual(empty["total"], 2)
        found = self.app._folder_tools.search(config.load_config(), sid, "demo_somar")
        self.assertEqual(found["tools"][0]["name"], "demo_somar")
        self.assertIn("a", found["tools"][0]["inputSchema"]["properties"])
        result = self.app._folder_tools.execute(config.load_config(), sid, "demo_somar", {"a": 20, "b": 22}, lambda *args: self.fail("auto não deve confirmar"))
        self.assertEqual(result["structuredContent"]["soma"], 42)
        process = self.app._folder_tools.manager.entries[sid]["client"].transport.process
        self.assertTrue(self.app.set_folder_tool(sid, False)["ok"])
        self.assertIsNotNone(process.poll())
        with self.assertRaises(ValueError):
            self.app._folder_tools.execute(config.load_config(), sid, "demo_somar", {}, lambda *args: True)
        self.assertEqual(len(folder_tools.tool_definitions(folder_tools.scan(config.load_config()))), 0)
        self.assertTrue((folder_tools.root() / "Demo").exists())

    def test_approval_refusal_and_config_change_prevent_execution(self):
        self.manifest(approval="each")
        sid = self.row()["id"]
        with self.assertRaises(PermissionError):
            self.app._folder_tools.execute(config.load_config(), sid, "demo_echo", {"texto": "hello"}, lambda *args: False)
        def disable(*args):
            self.app.set_folder_tool(sid, False)
            return True
        with self.assertRaises(ValueError):
            self.app._folder_tools.execute(config.load_config(), sid, "demo_echo", {"texto": "hello"}, disable)

    def test_project_tools_only_appear_in_active_project(self):
        self.manifest(name="Global")
        cfg = config.load_config()
        project = self.root / "project"
        project.mkdir()
        cfg.update(projects=[{"id": "p", "name": "Project", "path": str(project)}], active_project_id="p")
        config.save_config(cfg)
        self.manifest(project / "Ferramentas", "ProjectOnly")
        rows = folder_tools.scan(config.load_config())
        self.assertEqual({r["name"] for r in rows}, {"Global", "ProjectOnly"})
        project_row = next(r for r in rows if r["name"] == "ProjectOnly")
        self.assertEqual(project_row["scope"], "project")
        self.assertTrue(self.app.test_folder_tool(project_row["id"])["ok"])
        cfg = config.load_config()
        cfg["active_project_id"] = ""
        config.save_config(cfg)
        self.app.get_folder_tools()
        self.assertEqual([r["name"] for r in folder_tools.scan(config.load_config())], ["Global"])
        self.assertNotIn(project_row["id"], self.app._folder_tools.manager.entries)

    def test_invalid_manifest_is_reported_without_secret_contents(self):
        path = self.manifest()
        path.write_text('{"token":"folder-secret-value",', encoding="utf-8")
        result = self.app.get_folder_tools()
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["tools"][0]["error"])
        self.assertNotIn("folder-secret-value", json.dumps(result))
        self.assertFalse(result["tools"][0]["enabled"])

    def test_relative_cwd_resolves_inside_tool_directory(self):
        path = self.manifest()
        (path.parent / "subfolder").mkdir()
        data = json.loads(path.read_text(encoding="utf-8"))
        data["server"]["cwd"] = "subfolder"
        path.write_text(json.dumps(data), encoding="utf-8")
        row = self.row()
        self.assertFalse(row["error"], row)
        self.assertEqual(row["server"]["cwd"], str(path.parent / "subfolder"))

    def test_large_catalog_search_does_not_drop_operations_after_direct_cap(self):
        self.manifest()
        sid = self.row()["id"]
        definitions = [{"name": "operation_" + str(i), "description": "test", "inputSchema": {"type": "object"}} for i in range(350)]
        with patch("mcp_bridge.MCPClient.connect", return_value=definitions):
            found = self.app._folder_tools.search(config.load_config(), sid, "operation_349")
        self.assertEqual(found["tools"][0]["name"], "operation_349")
        self.assertEqual(found["matches"], 1)

    def test_model_receives_folder_catalog_and_executes_real_operation(self):
        self.manifest()
        cfg = config.load_config()
        cfg["providers"] = [{"id": "fake", "kind": "openrouter", "models": [{"id": "text", "type": "chat"}]}]
        cfg["chat"] = {"provider_id": "fake", "model_id": "text"}
        config.save_config(cfg)
        sid = self.row()["id"]
        turns = []
        def adapter(provider, model, messages, tools, params):
            names = {t["function"]["name"] for t in tools}
            self.assertIn("ferramentas_pesquisar", names)
            turns.append(messages[:])
            if len(turns) == 1:
                arguments = {"id": sid, "operacao": "demo_somar", "argumentos": {"a": 20, "b": 22}}
                raw = {"role": "assistant", "content": None, "tool_calls": [{"id": "folder1", "type": "function", "function": {"name": "ferramentas_executar", "arguments": json.dumps(arguments)}}]}
                return {"content": "", "raw_message": raw, "tool_calls": [{"id": "folder1", "name": "ferramentas_executar", "arguments": arguments}]}
            return {"content": "42", "tool_calls": []}
        with patch("providers.get_chat_adapter", return_value=adapter):
            result = self.app.chat("Usa a ferramenta Demo para somar 20 e 22")
        self.assertTrue(result["ok"], result)
        self.assertTrue(any(m["role"] == "tool" and '42' in m.get("content", "") for m in turns[-1]))

    def test_layout_documents_manifest_without_overwriting_user_file(self):
        directory = folder_tools.ensure_layout()
        self.assertIn("ferramenta.json", (directory / "LEIA-ME.md").read_text(encoding="utf-8"))
        (directory / "LEIA-ME.md").write_text("custom", encoding="utf-8")
        folder_tools.ensure_layout()
        self.assertEqual((directory / "LEIA-ME.md").read_text(encoding="utf-8"), "custom")

    def test_public_rea_options_do_not_corrupt_schemas_but_tokens_are_hidden(self):
        schema={"enum":["compact","full","off"],"description":"secret-token-value"}
        clean=redact(schema,{"env":{"REA_MCP_INPUT_SCHEMA_PROFILE":"compact","REA_MCP_OUTPUT_SCHEMA_PROFILE":"off","API_TOKEN":"secret-token-value"}})
        self.assertEqual(clean["enum"],schema["enum"])
        self.assertNotIn("secret-token-value",clean["description"])

    def test_installer_pins_package_and_avoids_global_setup(self):
        folder = folder_tools.ensure_layout() / "REA"
        runtime = folder / "runtime" / ("node-v" + folder_tools.NODE_VERSION + "-win-x64")
        runtime.mkdir(parents=True)
        (runtime / "node.exe").write_bytes(b"fixture")
        package = folder / "package"
        entry = package / "node_modules/rea-agents/scripts/rea.mjs"
        entry.parent.mkdir(parents=True)
        entry.write_text("// fixture", encoding="utf-8")
        lock = {"packages": {"node_modules/rea-agents": {"version": folder_tools.REA_VERSION, "integrity": folder_tools.REA_INTEGRITY}}}
        (package / "package-lock.json").write_text(json.dumps(lock), encoding="utf-8")
        with patch("folder_tools.subprocess.Popen") as popen:
            popen.return_value.returncode = 0
            self.app._folder_tools.installer._run()
        self.assertEqual(self.app._folder_tools.installer.status()["state"], "ready")
        command = popen.call_args.args[0]
        self.assertIn("rea-agents@" + folder_tools.REA_VERSION, command)
        self.assertIn("--ignore-scripts", command)
        self.assertIn("--omit=optional", command)
        self.assertNotIn("setup", command)
        manifest = json.loads((folder / folder_tools.MANIFEST).read_text(encoding="utf-8"))
        self.assertEqual(manifest["server"]["env"]["REA_MCP_OUTPUT_SCHEMA_PROFILE"], "off")
        self.assertIn("mcp", manifest["server"]["args"])
        lock["packages"]["node_modules/rea-agents"]["integrity"] = "wrong"
        (package / "package-lock.json").write_text(json.dumps(lock), encoding="utf-8")
        with patch("folder_tools.subprocess.Popen") as popen:
            popen.return_value.returncode = 0
            self.app._folder_tools.installer._run()
        self.assertEqual(self.app._folder_tools.installer.status()["state"], "error")
        self.assertIn("integridade", self.app._folder_tools.installer.status()["message"])


if __name__ == "__main__":
    unittest.main()
