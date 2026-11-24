import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import api
import config
import integration_catalog as catalog
import integration_services as services
from mcp_bridge import MCPClient, validate_server


class Page(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write('<h1>Olá Fetch</h1><script>secret_script()</script><p>Conteúdo local.</p><a href="/next">Seguinte</a>'.encode())

    def log_message(self, *args):
        pass


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.temp.name).resolve()
        self.patches = [patch("config.config_dir", return_value=self.root / "settings"), patch("config.application_root", return_value=self.root / "app")]
        for p in self.patches:
            p.start()
        config.save_config(config.default_config())
        self.app = api.Api()

    def tearDown(self):
        self.app._mcp.close()
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def test_fetch_auto_provision_respects_removal_and_disabled(self):
        catalog.ensure_fetch()
        cfg = config.load_config()
        self.assertEqual(len(cfg["mcp_servers"]), 1)
        self.assertEqual(cfg["mcp_servers"][0]["approval"], "auto")
        cfg["mcp_servers"][0]["enabled"] = False
        config.save_config(cfg)
        catalog.ensure_fetch()
        self.assertFalse(config.load_config()["mcp_servers"][0]["enabled"])
        self.app.remove_mcp_server("studio-fetch")
        catalog.ensure_fetch()
        self.assertEqual(config.load_config()["mcp_servers"], [])

    def test_fetch_real_stdio_and_http(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), Page)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        client = MCPClient(validate_server({**catalog.server_for("fetch"), "id": "fetch-test"}), str(self.root))
        try:
            tools = client.connect()
            self.assertIn("fetch_url", [t["name"] for t in tools])
            result = client.call("fetch_url", {"url": "http://127.0.0.1:" + str(server.server_port)})
            self.assertFalse(result["isError"], result)
            page = json.loads(result["content"][0]["text"])
            self.assertIn("Olá Fetch", page["text"])
            self.assertNotIn("secret_script", page["text"])
            self.assertTrue(page["links"][0].endswith("/next"))
            rejected = client.call("fetch_url", {"url": "file:///C:/Windows/win.ini"})
            self.assertTrue(rejected["isError"])
        finally:
            client.close()
            server.shutdown()
            server.server_close()
            thread.join(2)

    def test_credentials_encrypted_preserved_and_not_exposed(self):
        result = self.app.save_mcp_preset("brave", {"api_key": "brave-private-probe", "approval": "auto"})
        self.assertTrue(result["ok"], result)
        self.assertNotIn("brave-private-probe", json.dumps(result))
        cfg = config.load_config()
        self.assertNotIn("brave-private-probe", json.dumps(cfg))
        store = services.SettingsStore("brave")
        if os.name == "nt":
            self.assertNotIn(b"brave-private-probe", store.path.read_bytes())
        self.assertEqual(store.read()["api_key"], "brave-private-probe")
        edited = self.app.save_mcp_preset("brave", {"api_key": "", "enabled": False})
        self.assertTrue(edited["ok"], edited)
        self.assertEqual(store.read()["api_key"], "brave-private-probe")
        self.assertEqual(edited["server_id"], result["server_id"])
        self.assertFalse(config.load_config()["mcp_servers"][0]["enabled"])

    def test_all_bundled_servers_discover_and_readonly_schema_refreshes(self):
        for kind in services.KINDS:
            with self.subTest(kind=kind):
                client = MCPClient(validate_server({**catalog.server_for(kind), "id": "test-" + kind}), str(self.root))
                try:
                    definitions = client.connect()
                    self.assertIn("connection_test", [t["name"] for t in definitions])
                    self.assertNotIn("execute", [t["name"] for t in definitions])
                    self.assertNotIn("send_message", [t["name"] for t in definitions])
                    if kind == "discord":
                        services.SettingsStore(kind).write({"token": "private-test", "readonly": "false"})
                        refreshed = client.discover_tools()
                        self.assertIn("send_message", [t["name"] for t in refreshed])
                finally:
                    client.close()

    def test_api_tests_service_and_reports_provider_failure(self):
        saved = self.app.save_mcp_preset("fetch")
        self.assertTrue(saved["ok"], saved)
        result = self.app.test_mcp_server(saved["server_id"])
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["server"]["service_verified"])
        saved = self.app.save_mcp_preset("brave", {"api_key": "not-real-key"})
        with patch.object(self.app._mcp, "call", return_value={"isError": True, "content": [{"type": "text", "text": "HTTP 401"}]}):
            result = self.app.test_mcp_server(saved["server_id"])
        self.assertFalse(result["ok"], result)
        state = next(s for s in self.app.get_mcp_servers()["servers"] if s["id"] == saved["server_id"])
        self.assertFalse(state["service_verified"])
        self.assertEqual(state["service_error"], "HTTP 401")

    def test_missing_credentials_and_bad_ports_do_not_save(self):
        for kind in ("brave", "discord", "postgres", "mysql"):
            result = self.app.save_mcp_preset(kind, {})
            self.assertFalse(result["ok"], (kind, result))
        bad = self.app.save_mcp_preset("mysql", {"host": "localhost", "database": "test", "user": "me", "port": "70000"})
        self.assertFalse(bad["ok"])
        self.assertEqual(config.load_config()["mcp_servers"], [])

    def test_brave_uses_key_and_limits_without_real_account(self):
        with patch("integration_services.http_json", return_value={"web": {"results": [{"title": "Result", "url": "https://example.org", "description": "Text"}]}}) as request:
            result = services.execute("brave", "web_search", {"query": "teste", "count": 999}, {"api_key": "private-key"})
            self.assertEqual(result["results"][0]["title"], "Result")
            self.assertEqual(request.call_args.kwargs["headers"]["X-Subscription-Token"], "private-key")
            self.assertEqual(request.call_args.kwargs["params"]["count"], 20)
        with patch("integration_services.http_json", side_effect=RuntimeError("failed private-key")):
            self.assertNotIn("private-key", json.dumps(services.safe_execute("brave", "web_search", {"query": "test"}, {"api_key": "private-key"})))

    def test_discord_readonly_and_send_contract_without_sending(self):
        settings = {"token": "bot-private-key", "readonly": "true"}
        with patch("integration_services.http_json") as request:
            with self.assertRaises(ValueError):
                services.execute("discord", "send_message", {"channel_id": "123", "text": "hello"}, settings)
            request.assert_not_called()
        with patch("integration_services.http_json", return_value={"id": "456"}) as request:
            result = services.execute("discord", "send_message", {"channel_id": "123", "text": "@everyone hello"}, {**settings, "readonly": "false"})
            self.assertTrue(result["sent"])
            self.assertEqual(request.call_args.kwargs["json"]["allowed_mentions"], {"parse": []})
            self.assertEqual(request.call_args.kwargs["headers"]["Authorization"], "Bot bot-private-key")

    def test_database_transaction_readonly_writes_parameters_and_cleanup(self):
        settings = {"host": "localhost", "port": "5432", "database": "test", "user": "test", "password": "private-db", "tls": "false", "readonly": "true"}
        for kind, driver in (("postgres", "pg8000.dbapi.connect"), ("mysql", "pymysql.connect")):
            with self.subTest(kind=kind), patch(driver) as connect:
                connection = connect.return_value
                cursor = connection.cursor.return_value
                cursor.description = [("answer",)]
                cursor.rowcount = 1
                cursor.fetchmany.return_value = [(42,)]
                result = services.execute(kind, "query", {"sql": "SELECT %s", "params": [42]}, settings)
                self.assertEqual(result["rows"], [[42]])
                cursor.execute.assert_any_call("SELECT %s", [42])
                first = cursor.execute.call_args_list[0].args[0]
                self.assertIn("READ ONLY", first)
                connection.rollback.assert_called_once()
                connection.commit.assert_not_called()
                connection.close.assert_called_once()
            with patch(driver) as connect:
                with self.assertRaises(ValueError):
                    services.execute(kind, "execute", {"sql": "DELETE FROM things"}, settings)
                connect.assert_not_called()
            with patch(driver) as connect:
                connection = connect.return_value
                connection.cursor.return_value.description = None
                services.execute(kind, "execute", {"sql": "UPDATE things SET a=%s", "params": [42]}, {**settings, "readonly": "false"})
                connection.commit.assert_called_once()
                connection.close.assert_called_once()
            with patch(driver) as connect:
                connection = connect.return_value
                connection.cursor.return_value.execute.side_effect = RuntimeError("driver error private-db")
                result = services.safe_execute(kind, "query", {"sql": "SELECT 1"}, settings)
                self.assertTrue(result["isError"])
                self.assertNotIn("private-db", json.dumps(result))
                connection.close.assert_called_once()

    def test_project_command_accepts_external_cwd_but_direct_files_remain_scoped(self):
        project = self.root / "project"
        outside = self.root / "outside"
        project.mkdir()
        outside.mkdir()
        (outside / "probe.txt").write_text("external-command-ok")
        ctx = {"on": True, "scope": "project", "approval": "auto", "base": str(project)}
        self.assertEqual(api._agent_cwd(ctx, str(outside)), str(outside))
        result = self.app._agent_exec('type probe.txt' if os.name == 'nt' else 'cat probe.txt', str(outside), ctx, [])
        self.assertIn("external-command-ok", result)
        target, error = api._resolve_in_scope(str(outside / "probe.txt"), ctx)
        self.assertIsNone(target)
        self.assertTrue(error)


if __name__ == "__main__":
    unittest.main()
