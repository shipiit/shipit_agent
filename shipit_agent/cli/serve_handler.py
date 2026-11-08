"""The HTTP request handler behind `shipit serve`: health, models and chat completions."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .serve import AgentServer

# Events forwarded alongside the OpenAI-shaped stream so a rich client can
# render the full transcript. Deliberately an allow-list: internal loop
# mechanics (step_started, llm_retry) are not the caller's business.
_SIDEBAND_EVENTS = frozenset({
    "tool_called", "tool_completed", "tool_failed", "tool_denied",
    "action_queued", "usage_tick", "context_compaction_started",
    "context_compacted", "run_cancelled",
    "guardrail_triggered",
})


class _ClientGone(Exception):
    pass


def make_handler(server: AgentServer) -> type[BaseHTTPRequestHandler]:
    """A request handler class bound to ``server``."""
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
                from shipit_agent.observability.streaming import STREAM_GENERATION

                self._json(200, {
                    "status": "ok",
                    "model": server.model_name,
                    # A changed generation means this process restarted and
                    # any in-flight provisional state a client holds is
                    # stale. Exposed here so a client can check without
                    # opening a stream.
                    "stream_generation": STREAM_GENERATION,
                })
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

        def _run_sse(self) -> None:
            """The full transcript as Server-Sent Events.

            The OpenAI-shaped endpoint gives a chat client prose. This
            gives a *transcript* client everything the terminal renderer
            sees — work rows, queued approvals, running cost — each frame
            labelled canonical or provisional so a reconnect knows what to
            keep and what to throw away.
            """
            from shipit_agent.observability.streaming import hello_frame, sse

            if not server._authorized(self.headers):
                self._json(401, {"error": {"message": "invalid api key"}})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
            except (ValueError, OSError):
                self._json(400, {"error": {"message": "invalid JSON body"}})
                return

            prompt = str(body.get("prompt") or body.get("input") or "")
            if not prompt:
                self._json(400, {"error": {"message": "`prompt` is required"}})
                return

            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            # One request is one run is one stream. Closing at the end
            # gives the client a real EOF instead of a socket that never
            # finishes — and there is nothing to reuse the connection for.
            self.send_header("Connection", "close")
            self.close_connection = True
            # Without this an intermediate proxy will buffer the whole
            # response and deliver it at the end, which is the one thing
            # a stream must not do.
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()

            def write(chunk: str) -> None:
                self.wfile.write(chunk.encode("utf-8"))
                self.wfile.flush()

            try:
                # Hello first, before anything else, so a reconnecting
                # client can compare generations before deciding what to
                # do with the state it already holds.
                write(sse(hello_frame()))
                sequence = 0
                for event in server.agent.stream(prompt):
                    sequence += 1
                    write(sse(event, sequence=sequence))
                write("event: done\ndata: [DONE]\n\n")
            except (BrokenPipeError, ConnectionResetError):
                pass  # the client hung up; nothing to clean up
            except Exception as exc:  # noqa: BLE001
                try:
                    write(
                        "event: error\ndata: "
                        + json.dumps({"error": str(exc)})
                        + "\n\n"
                    )
                except OSError:
                    pass

        def do_POST(self) -> None:
            if self.path in ("/v1/stream", "/stream"):
                self._run_sse()
                return
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
