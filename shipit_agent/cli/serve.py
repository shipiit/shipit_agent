"""`shipit serve` — expose a shipit Agent as an OpenAI-compatible API.

Any client that speaks ``/v1/chat/completions`` (SDKs, UIs, other agents)
can now call YOUR agent — tools, guardrails, roles and all — the same way
unsloth serves local models to coding agents. Stdlib-only (ThreadingHTTPServer),
optional Bearer auth, SSE streaming from the agent's live token/tool events.

    from shipit_agent.cli.serve import AgentServer

    server = AgentServer(agent, api_key="secret")   # api_key optional
    server.serve_forever(port=8399)

    # then, from any OpenAI SDK:
    #   client = OpenAI(base_url="http://127.0.0.1:8399/v1", api_key="secret")
    #   client.chat.completions.create(model="shipit", messages=[...])
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .serve_handler import make_handler


def _jsonable(value: Any) -> Any:
    """Coerce an event payload into something json.dumps will accept.

    Payloads carry arbitrary tool arguments, and one unserializable value must
    not be able to kill a stream mid-response.
    """
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


class AgentServer:
    """OpenAI-compatible HTTP wrapper around one shipit Agent."""

    def __init__(
        self,
        agent: Any,
        *,
        model_name: str = "shipit",
        api_key: str | None = None,
    ) -> None:
        self.agent = agent
        self.model_name = model_name
        self.api_key = api_key
        self._httpd: ThreadingHTTPServer | None = None

    # ------------------------------------------------------------------
    # Request handling
    # ------------------------------------------------------------------
    def _authorized(self, headers: Any) -> bool:
        if not self.api_key:
            return True
        auth = headers.get("Authorization", "")
        return auth == f"Bearer {self.api_key}"

    @staticmethod
    def _last_user_message(messages: list[dict[str, Any]]) -> str:
        for message in reversed(messages):
            if message.get("role") == "user":
                content = message.get("content", "")
                if isinstance(content, list):  # content-block form
                    content = " ".join(
                        str(b.get("text", "")) for b in content if isinstance(b, dict)
                    )
                return str(content)
        return ""

    def _completion_payload(self, text: str) -> dict[str, Any]:
        return {
            "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": self.model_name,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    def _chunk_payload(
        self,
        delta: dict[str, Any],
        finish: str | None = None,
        shipit: dict[str, Any] | None = None,
    ) -> str:
        body: dict[str, Any] = {
            "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": self.model_name,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
        if shipit is not None:
            # An additive key: OpenAI clients ignore what they don't know, so
            # this stays wire-compatible while giving a shipit-aware client
            # everything the terminal renderer sees.
            body["shipit"] = _jsonable(shipit)
        return f"data: {json.dumps(body)}\n\n"

    # ------------------------------------------------------------------
    def _make_handler(self) -> type[BaseHTTPRequestHandler]:
        return make_handler(self)

    # ------------------------------------------------------------------
    def start(self, *, host: str = "127.0.0.1", port: int = 8399) -> int:
        """Bind and start serving on a background thread; returns the port."""
        self._httpd = ThreadingHTTPServer((host, port), self._make_handler())
        thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        thread.start()
        return self._httpd.server_address[1]

    def serve_forever(self, *, host: str = "127.0.0.1", port: int = 8399) -> None:
        """Blocking serve (Ctrl+C to stop)."""
        self._httpd = ThreadingHTTPServer((host, port), self._make_handler())
        try:
            self._httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            self._httpd.server_close()

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
