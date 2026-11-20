"""Servidor HTTP falso compatível com /chat/completions para testar adaptadores por socket real.

O comportamento é escolhido pelo nome do modelo pedido, por exemplo `model="rate"` devolve 429.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


@dataclass
class FakeOpenAIServer:
    base_url: str
    requests: list[dict[str, Any]] = field(default_factory=list)
    _server: ThreadingHTTPServer | None = None

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()


def _ok_body(model: str, usage: Any = "default", text: str = "OK") -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": "chatcmpl-test",
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}}],
    }
    if usage == "default":
        body["usage"] = {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}
    elif usage is not None:
        body["usage"] = usage
    return body


class _Handler(BaseHTTPRequestHandler):
    server: Any  # ThreadingHTTPServer com atributo `fake`

    def log_message(self, format: str, *args: Any) -> None:  # silencia o log por omissão
        return

    def do_POST(self) -> None:  # noqa: N802 (nome imposto por BaseHTTPRequestHandler)
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        body = json.loads(raw or b"{}")
        model = str(body.get("model", ""))
        self.server.fake.requests.append(
            {"path": self.path, "headers": dict(self.headers), "body": body}
        )
        status, payload = _scenario(model)
        if model == "timeout":
            time.sleep(2)
        if isinstance(payload, bytes):
            data = payload
        else:
            data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _scenario(model: str) -> tuple[int, Any]:
    if model == "rate":
        return 429, {"error": "rate limited"}
    if model == "server":
        return 500, {"error": "boom"}
    if model == "auth":
        return 401, {"error": "bad key"}
    if model == "notfound":
        return 404, {"error": "no such model"}
    if model == "badreq":
        return 400, {"error": "bad request"}
    if model == "badjson":
        return 200, b"<html>not json</html>"
    if model == "emptychoices":
        return 200, {"choices": [], "model": model}
    if model == "nousage":
        return 200, _ok_body(model, usage=None)
    if model == "wrongmodel":
        return 200, _ok_body("another-model")
    if model == "reasoning":
        usage = {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "completion_tokens_details": {"reasoning_tokens": 40},
            "prompt_tokens_details": {"cached_tokens": 20},
        }
        return 200, _ok_body(model, usage=usage)
    if model == "timeout":
        return 200, _ok_body(model)
    if model == "jsonok":
        return 200, _ok_body(model, text='{"ok": true}')
    if model == "jsonlie":
        return 200, _ok_body(model, text="Claro! Aqui está a resposta.")
    return 200, _ok_body(model)


def start_fake_openai_server() -> FakeOpenAIServer:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    httpd.daemon_threads = True
    fake = FakeOpenAIServer(base_url=f"http://127.0.0.1:{httpd.server_address[1]}/v1")
    httpd.fake = fake  # type: ignore[attr-defined]
    fake._server = httpd
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return fake
