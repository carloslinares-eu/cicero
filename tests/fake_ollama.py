"""A tiny stand-in for the Ollama HTTP API, so the local-model code is tested without a GPU or downloads."""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class _QuietServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address) -> None:
        pass  # a client that hangs up mid-stream (a canceled download) isn't an error here


class FakeOllama:
    """Translates by upper-casing the paragraph it finds in the prompt; downloads in two steps."""

    def __init__(self) -> None:
        self.installed: set[str] = set()
        self.chats: list[dict] = []
        self.pulls: list[str] = []
        self.files: dict[str, bytes] = {}  # extra GET paths (fake release downloads)
        self.brief = {"summary": "Quarterly results of a fruit company.", "glossary": [
            {"term": "Apple", "translation": "Manzana"}]}
        self.answer_override: Callable[[dict], str] | None = None  # to simulate odd answers
        self._server = _QuietServer(("127.0.0.1", 0), self._handler())
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        fake = self

        # noinspection PyPep8Naming
        class Handler(BaseHTTPRequestHandler):  # the do_GET/do_POST/do_DELETE names are http.server's
            def log_message(self, format: str, *args) -> None:  # noqa: A002 - http.server's own signature
                pass  # keep test output quiet

            def _send(self, payload, status: int = 200) -> None:
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _body(self) -> dict:
                length = int(self.headers.get("Content-Length") or 0)
                return json.loads(self.rfile.read(length) or b"{}")

            def do_GET(self) -> None:
                if self.path == "/api/version":
                    self._send({"version": "0.40.12"})
                elif self.path == "/api/tags":
                    self._send({"models": [{"name": name, "model": name} for name in sorted(fake.installed)]})
                elif self.path == "/api/ps":
                    self._send({"models": []})
                elif self.path in fake.files:
                    self._file(fake.files[self.path])
                else:
                    self._send({"error": "not found"}, 404)

            def _file(self, data: bytes) -> None:
                start = 0
                match = re.match(r"bytes=(\d+)-", self.headers.get("Range") or "")
                if match:
                    start = int(match.group(1))
                    if start >= len(data):
                        self.send_response(416)
                        self.end_headers()
                        return
                    self.send_response(206)
                else:
                    self.send_response(200)
                self.send_header("Content-Length", str(len(data) - start))
                self.end_headers()
                self.wfile.write(data[start:])

            def do_POST(self) -> None:
                body = self._body()
                known = body.get("model") in fake.installed
                if self.path == "/api/pull":
                    self._pull(body["model"])
                elif self.path in ("/api/generate", "/api/chat") and not known:
                    if self.path == "/api/chat":
                        fake.chats.append(body)
                    self._send({"error": f"model '{body['model']}' not found"}, 404)
                elif self.path == "/api/generate":
                    self._send({"done": True})
                elif self.path == "/api/chat":
                    fake.chats.append(body)
                    self._send({"message": {"role": "assistant", "content": fake.answer(body)}})
                else:
                    self._send({"error": "not found"}, 404)

            def do_DELETE(self) -> None:
                fake.installed.discard(self._body()["model"])
                self._send({})

            def _pull(self, name: str) -> None:
                fake.pulls.append(name)
                if "missing" in name:
                    events = [{"status": "pulling manifest"}, {"error": "pull model manifest: file does not exist"}]
                else:
                    events = [{"status": "pulling manifest"},
                              {"status": "pulling aaa", "digest": "sha256:aaa", "total": 1000, "completed": 400},
                              {"status": "pulling bbb", "digest": "sha256:bbb", "total": 10, "completed": 10},
                              {"status": "pulling aaa", "digest": "sha256:aaa", "total": 1000, "completed": 1000},
                              {"status": "success"}]
                    fake.installed.add(name)
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.end_headers()
                for event in events:
                    self.wfile.write(json.dumps(event).encode() + b"\n")

        return Handler

    def answer(self, request: dict) -> str:
        if self.answer_override is not None:
            return self.answer_override(request)
        if request.get("format"):
            return json.dumps(self.brief)
        content = request["messages"][-1]["content"]
        if "[Source Text]\n" in content:
            text = content.rsplit("[Source Text]\n", 1)[1]
        elif "\n\n" in content:
            text = content.rsplit("\n\n", 1)[1]
        else:
            text = content
        return re.sub(r"(<[^>]+>)|([^<]+)", lambda m: m.group(1) or m.group(2).upper(), text)
