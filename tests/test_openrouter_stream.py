import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from providers import openrouter


class StreamServer:
    def __init__(self, events, done=True):
        self.events = events
        self.received = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                owner.received.append(json.loads(body))
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                try:
                    for event in owner.events:
                        self.wfile.write(("data: " + json.dumps(event, ensure_ascii=False) + "\n\n").encode("utf-8"))
                        self.wfile.flush()
                    if done:self.wfile.write(b"data: [DONE]\n\n")
                except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                    pass

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.http.serve_forever, daemon=True).start()

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.http.server_port}/v1"

    def close(self):
        self.http.shutdown()
        self.http.server_close()


class StreamTests(unittest.TestCase):
    def test_interrupted_stream_cannot_execute_tools(self):
        server=StreamServer([{'choices':[{'delta':{'tool_calls':[{'index':0,'id':'c','function':{'name':'write','arguments':'{}'}}]}}]}],done=False)
        try:
            with self.assertRaisesRegex(openrouter.ProviderError,'terminou antes'):openrouter.chat({'base_url':server.base_url,'api_key':'test'},{'id':'m'},[{'role':'user','content':'hi'}],params={'_on_delta':lambda t:None})
        finally:server.close()
    def test_invalid_tool_arguments_are_rejected(self):
        server=StreamServer([{'choices':[{'delta':{'tool_calls':[{'index':0,'id':'c','function':{'name':'write','arguments':'{"partial":'}}]}}]}])
        try:
            with self.assertRaisesRegex(openrouter.ProviderError,'incompletos'):openrouter.chat({'base_url':server.base_url,'api_key':'test'},{'id':'m'},[{'role':'user','content':'hi'}],params={'_on_delta':lambda t:None})
        finally:server.close()
    def test_text_stream_and_usage(self):
        server = StreamServer([
            {"choices": [{"delta": {"content": "Olá "}}]},
            {"choices": [{"delta": {"content": "mundo"}}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}]},
            {"choices": [], "usage": {"total_tokens": 7}},
        ])
        deltas = []
        try:
            provider = {"base_url": server.base_url, "api_key": "test"}
            result = openrouter.chat(provider, {"id": "m"}, [{"role": "user", "content": "oi"}], None, {"_on_delta": deltas.append})
        finally:
            server.close()
        self.assertEqual(result["content"], "Olá mundo")
        self.assertEqual(deltas, ["Olá ", "mundo"])
        self.assertEqual(result["usage"]["total_tokens"], 7)
        self.assertTrue(server.received[0]["stream"])

    def test_tool_call_fragments_are_accumulated(self):
        server = StreamServer([
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "call-1", "function": {"name": "demo", "arguments": '{"x":'}}
            ]}}]},
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "function": {"arguments": "1}"}}
            ]}}]},
        ])
        try:
            provider = {"base_url": server.base_url, "api_key": "test"}
            result = openrouter.chat(provider, {"id": "m"}, [{"role": "user", "content": "oi"}], None, {"_on_delta": lambda text: None})
        finally:
            server.close()
        self.assertEqual(result["content"], "")
        self.assertEqual(result["tool_calls"], [{"id": "call-1", "name": "demo", "arguments": {"x": 1}}])
        self.assertEqual(result["raw_message"]["tool_calls"][0]["function"]["name"], "demo")

    def test_cancel_returns_partial(self):
        server = StreamServer([
            {"choices": [{"delta": {"content": "parcial"}}]},
            {"choices": [{"delta": {"content": " resto"}}]},
        ])
        cancel = threading.Event()
        cancel.set()
        try:
            provider = {"base_url": server.base_url, "api_key": "test"}
            result = openrouter.chat(
                provider, {"id": "m"}, [{"role": "user", "content": "oi"}], None,
                {"_on_delta": lambda text: None, "_cancel": cancel},
            )
        finally:
            server.close()
        self.assertTrue(result["cancelled"])
        self.assertEqual(result["content"], "")


if __name__ == "__main__":
    unittest.main()
