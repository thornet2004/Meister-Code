import base64
import hashlib
import importlib.util
import json
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import requests
from mcp_bridge import MCPClient, public_server, redact, validate_server
from mcp_oauth import OAuthJobs, OAuthRequired, OAuthStore, access_token, token_status


@unittest.skipUnless(importlib.util.find_spec("mcp") is not None, "SDK mcp não instalado neste ambiente")
class OAuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.temp.name).resolve()
        self.config_patch = patch("config.config_dir", return_value=self.root)
        self.config_patch.start()
        self.jobs = []; self.opened = []; self.errors = []; self.grants = []; self.tokens = set()
        self.deny = False; self.no_registration = False; self.refreshes = 0
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def respond(self, data, status=200):
                body = json.dumps(data).encode()
                self.send_response(status); self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
            def do_GET(self):
                parsed = urlsplit(self.path)
                if parsed.path.startswith("/.well-known/oauth-protected-resource"):
                    self.respond({"resource":owner.url, "authorization_servers":[owner.issuer], "scopes_supported":["read"]})
                elif parsed.path.startswith("/.well-known/oauth-authorization-server"):
                    value = {"issuer":owner.issuer, "authorization_endpoint":owner.issuer+"/authorize", "token_endpoint":owner.issuer+"/token",
                             "response_types_supported":["code"], "grant_types_supported":["authorization_code", "refresh_token"],
                             "token_endpoint_auth_methods_supported":["none"], "code_challenge_methods_supported":["S256"], "scopes_supported":["read"]}
                    if not owner.no_registration: value["registration_endpoint"] = owner.issuer+"/register"
                    self.respond(value)
                elif parsed.path == "/authorize":
                    params = parse_qs(parsed.query); owner.authorization = params
                    if params.get("code_challenge_method") != ["S256"]: owner.errors.append("PKCE missing")
                    target = params["redirect_uri"][0]
                    values = {"state":params["state"][0], "iss":owner.issuer}
                    values.update({"error":"access_denied"} if owner.deny else {"code":"test-auth-code"})
                    self.send_response(302); self.send_header("Location", target+"?"+urlencode(values)); self.send_header("Content-Length","0"); self.end_headers()
                else: self.respond({},404)
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length",0)))
                if self.path == "/register":
                    if owner.no_registration: self.respond({"error":"registration_unavailable"},404); return
                    value = json.loads(body); value["client_id"] = "test-native-client"; self.respond(value,201)
                elif self.path == "/token":
                    data = parse_qs(body.decode()); owner.grants.append(data)
                    if data.get("grant_type") == ["authorization_code"]:
                        verifier = data["code_verifier"][0]
                        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
                        if challenge != owner.authorization["code_challenge"][0]: owner.errors.append("PKCE mismatch")
                    else:
                        owner.refreshes += 1
                        if not data.get("refresh_token",[""])[0].startswith("private-refresh-"): owner.errors.append("Refresh missing")
                    number = len(owner.grants)
                    token = "private-access-"+str(number); owner.tokens.add(token)
                    self.respond({"access_token":token, "refresh_token":"private-refresh-"+str(number), "token_type":"Bearer", "expires_in":3600, "scope":"read"})
                elif self.path == "/mcp":
                    if self.headers.get("Authorization","").removeprefix("Bearer ") not in owner.tokens:
                        self.send_response(401); self.send_header("WWW-Authenticate", 'Bearer resource_metadata="'+owner.issuer+'/.well-known/oauth-protected-resource", scope="read"')
                        self.send_header("Content-Length","0"); self.end_headers(); return
                    message = json.loads(body)
                    if message["method"] == "server/discover": result={"supportedVersions":["2026-07-28"], "capabilities":{"tools":{}}}
                    elif message["method"] == "tools/list": result={"tools":[]}
                    else: result={"content":[{"type":"text","text":"authorized"}]}
                    self.respond({"jsonrpc":"2.0", "id":message["id"], "result":result})
                else: self.respond({},404)
        self.http = ThreadingHTTPServer(("127.0.0.1",0), Handler)
        threading.Thread(target=self.http.serve_forever,daemon=True).start()
        self.issuer = f"http://127.0.0.1:{self.http.server_port}"
        self.url = self.issuer+"/mcp"
        self.server = validate_server({"id":"oauth-test", "name":"OAuth local", "transport":"http", "url":self.url, "auth_mode":"oauth"})

    def tearDown(self):
        for job in self.jobs:
            job.close()
            for value in job.jobs.values(): value["thread"].join(timeout=5)
        self.http.shutdown(); self.http.server_close()
        self.config_patch.stop(); self.temp.cleanup()

    def opener(self, url):
        self.opened.append(url)
        response = requests.get(url,timeout=5)
        self.assertEqual(response.status_code,200)
        return True

    def authorize(self, opener=None):
        job = OAuthJobs(opener=opener or self.opener); self.jobs.append(job)
        job.start(self.server)
        return job

    def wait(self, job, expected="connected"):
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            state=job.status(self.server["id"])
            if state["state"] not in ("starting","waiting"):
                self.assertEqual(state["state"],expected,state);return state
            time.sleep(0.05)
        self.fail("OAuth job timed out")

    def test_login_pkce_encrypted_storage_and_mcp_connection(self):
        self.wait(self.authorize())
        store=OAuthStore(self.server)
        self.assertEqual(access_token(self.server),"private-access-1")
        self.assertNotIn(b"private-access",store.path.read_bytes())
        self.assertNotIn(b"private-refresh",store.path.read_bytes())
        self.assertTrue(token_status(self.server)["linked"])
        self.assertNotIn("private-access",json.dumps(public_server(self.server)))
        self.assertNotIn("private-access",redact("private-access-1",self.server))
        self.assertEqual(self.errors,[])
        self.assertEqual(self.grants[0]["resource"],[self.url])
        client=MCPClient(self.server,str(self.root))
        try: self.assertEqual(client.connect(),[])
        finally: client.close()

    def test_refresh_renews_without_opening_browser_and_is_bound_to_endpoint(self):
        self.wait(self.authorize())
        opened=len(self.opened)
        OAuthStore(self.server).update(expires_at=time.time()-5)
        self.assertEqual(access_token(self.server),"private-access-2")
        self.assertEqual(self.refreshes,1);self.assertEqual(len(self.opened),opened)
        self.assertEqual(OAuthStore(self.server).read()["tokens"]["refresh_token"],"private-refresh-2")
        with self.assertRaises(OAuthRequired):access_token({**self.server,"url":self.url+"/other"})

    def test_callback_rejects_wrong_state_and_issuer_then_accepts_valid_return(self):
        def opener(url):
            query=parse_qs(urlsplit(url).query);redirect=query["redirect_uri"][0]
            bad=requests.get(redirect,params={"code":"bad","state":"wrong"},timeout=5)
            self.assertEqual(bad.status_code,400)
            bad=requests.get(redirect,params={"code":"bad","state":query["state"][0],"iss":"https://wrong.example"},timeout=5)
            self.assertEqual(bad.status_code,400)
            return self.opener(url)
        self.wait(self.authorize(opener))
        self.assertEqual(self.errors,[])

    def test_cancel_and_denied_authorization(self):
        self.deny=True
        self.wait(self.authorize(),"error")
        self.assertFalse(token_status(self.server)["linked"])
        self.deny=False
        job=self.authorize(lambda url:True)
        deadline=time.monotonic()+10
        while time.monotonic()<deadline and job.status(self.server["id"])["state"]!="waiting":time.sleep(0.05)
        job.cancel(self.server["id"])
        self.wait(job,"cancelled")
        self.assertFalse(OAuthStore(self.server).path.exists())

    def test_no_client_registration_reports_requirement_without_fake_success(self):
        self.no_registration=True
        state=self.wait(self.authorize(),"error")
        self.assertIn("Client ID",state["message"])
        self.assertFalse(token_status(self.server)["linked"])

    def test_pre_registered_client_works_without_dynamic_registration(self):
        self.no_registration=True
        self.server["oauth_client_id"]="registered-native-client"
        OAuthStore(self.server).update(manual_client_secret="private-registered-secret")
        self.wait(self.authorize())
        self.assertEqual(self.grants[0]["client_id"],["registered-native-client"])
        self.assertEqual(self.grants[0]["client_secret"],["private-registered-secret"])
        self.assertNotIn("private-registered-secret",json.dumps(public_server(self.server)))

    def test_oauth_scope_is_sent(self):
        self.server["oauth_scope"]="read"
        self.wait(self.authorize())
        self.assertEqual(self.authorization.get("scope"),["read"])

    def test_cancel_keeps_previous_authorization(self):
        self.wait(self.authorize())
        before=access_token(self.server)
        job=self.authorize(lambda url:True)
        deadline=time.monotonic()+10
        while time.monotonic()<deadline and job.status(self.server["id"])["state"]!="waiting":
            time.sleep(0.05)
        job.cancel(self.server["id"])
        self.wait(job,"cancelled")
        self.assertEqual(access_token(self.server),before)
        self.assertTrue(token_status(self.server)["linked"])

    def test_401_refreshes_and_retries(self):
        self.wait(self.authorize())
        self.tokens.clear()
        client=MCPClient(self.server,str(self.root))
        try:
            self.assertEqual(client.connect(),[])
        finally:
            client.close()
        self.assertGreaterEqual(self.refreshes,1)
        self.assertTrue(token_status(self.server)["linked"])

    def test_store_replace_restores_previous_tokens(self):
        store=OAuthStore(self.server)
        store.update(tokens={"access_token":"private-a"},expires_at=time.time()+3600)
        backup=store.read()
        store.update(tokens=None,expires_at=None)
        store.replace(backup)
        self.assertEqual(store.read()["tokens"]["access_token"],"private-a")

    def test_protect_roundtrip(self):
        from mcp_oauth import _protect
        data=b'{"tokens":{"access_token":"x"}}'
        self.assertEqual(_protect(_protect(data,b"entropy"),b"entropy",True),data)


if __name__=="__main__":unittest.main()
