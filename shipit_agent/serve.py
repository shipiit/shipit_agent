"""`shipit serve` — expose a shipit Agent as an OpenAI-compatible API.

Any client that speaks ``/v1/chat/completions`` (SDKs, UIs, other agents)
can now call YOUR agent — tools, guardrails, roles and all — the same way
unsloth serves local models to coding agents. Stdlib-only (ThreadingHTTPServer),
optional Bearer auth, SSE streaming from the agent's live token/tool events.

    from shipit_agent.serve import AgentServer

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


# Events forwarded alongside the OpenAI-shaped stream so a rich client can
# render the full transcript. Deliberately an allow-list: internal loop
# mechanics (step_started, llm_retry) are not the caller's business.
_SIDEBAND_EVENTS = frozenset({
    "tool_called", "tool_completed", "tool_failed", "tool_denied",
    "action_queued", "usage_tick", "context_compacted", "run_cancelled",
    "guardrail_triggered",
})


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
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: Any) -> None:  # quiet by default
                pass

            def _json(self, code: int, body: dict[str, Any]) -> None:
                data = json.dumps(body).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:
                if self.path == "/health":
                    self._json(200, {"status": "ok", "model": server.model_name})
                    return
                if self.path == "/v1/models":
                    if not server._authorized(self.headers):
                        self._json(401, {"error": {"message": "invalid api key"}})
                        return
                    self._json(
                        200,
                        {
                            "object": "list",
                            "data": [
                                {
                                    "id": server.model_name,
                                    "object": "model",
                                    "owned_by": "shipit-agent",
                                }
                            ],
                        },
                    )
                    return
                self._json(404, {"error": {"message": f"no route {self.path}"}})

            def do_POST(self) -> None:
                if self.path not in ("/v1/chat/completions", "/chat/completions"):
                    self._json(404, {"error": {"message": f"no route {self.path}"}})
                    return
                if not server._authorized(self.headers):
                    self._json(401, {"error": {"message": "invalid api key"}})
                    return
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    payload = json.loads(self.rfile.read(length) or b"{}")
                except (ValueError, json.JSONDecodeError):
                    self._json(400, {"error": {"message": "invalid JSON body"}})
                    return
                # Validate BEFORE doing any agent work — a malformed request
                # must never trigger an expensive run.
                messages = payload.get("messages")
                if not isinstance(messages, list) or not messages:
                    self._json(
                        400, {"error": {"message": "`messages` is required"}}
                    )
                    return
                prompt = server._last_user_message(messages)
                if not prompt:
                    self._json(
                        400, {"error": {"message": "no user message found"}}
                    )
                    return

                if payload.get("stream"):
                    self._stream(prompt)
                else:
                    try:
                        result = server.agent.run(prompt)
                        text = getattr(result, "output", str(result))
                    except Exception as exc:
                        self._json(500, {"error": {"message": str(exc)}})
                        return
                    self._json(200, server._completion_payload(text))

            def _stream(self, prompt: str) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()

                def write(chunk: str) -> None:
                    try:
                        self.wfile.write(chunk.encode("utf-8"))
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        raise _ClientGone from None

                try:
                    write(server._chunk_payload({"role": "assistant"}))
                    saw_delta = False
                    final = ""
                    for event in server.agent.stream(prompt):
                        etype = getattr(event, "type", "")
                        if etype == "text_delta":
                            saw_delta = True
                            write(server._chunk_payload(
                                {"content": event.payload.get("chunk", "")}))
                        elif etype == "run_completed":
                            final = str(event.payload.get("output", "") or "")
                        elif etype in _SIDEBAND_EVENTS:
                            # Work rows, queued approvals, running cost. A
                            # plain OpenAI client ignores the extra key; a
                            # shipit-aware one renders the same transcript the
                            # terminal does instead of only the prose.
                            write(server._chunk_payload(
                                {}, shipit={"type": etype, **dict(event.payload)}))
                    if not saw_delta and final:
                        write(server._chunk_payload({"content": final}))
                    write(server._chunk_payload({}, finish="stop"))
                    write("data: [DONE]\n\n")
                except _ClientGone:
                    pass  # client hung up mid-stream — nothing to clean
                except Exception as exc:
                    # In-band error frame, then terminate the stream cleanly.
                    try:
                        write(f"data: {json.dumps({'error': {'message': str(exc)}})}\n\n")
                        write("data: [DONE]\n\n")
                    except _ClientGone:
                        pass

        return Handler

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


class _ClientGone(Exception):
    pass
