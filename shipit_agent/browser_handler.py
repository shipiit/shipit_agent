"""The browser bridge's HTTP request handler: sessions, models, chat streaming and Workspace proposals."""

from __future__ import annotations

import hmac
import json
import threading
import uuid
from contextlib import closing
from http.server import BaseHTTPRequestHandler

from shipit_agent.browser_attachments import append_documents, decode_uploads
from shipit_agent.serve import _jsonable
from shipit_agent.stores import InMemorySessionStore

from .browser_bridge import BROWSER_PROMPT, BrowserBridge, browser_prompt


def make_handler(bridge: BrowserBridge):
    """The request handler class bound to *bridge*."""
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass  # Never log page text, prompts, or tokens.

        def reply(self, status, payload):
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def authorized(self):
            origin = self.headers.get("Origin", "")
            if origin and not origin.startswith("chrome-extension://"):
                self.reply(403, {"error": "Browser origins are not allowed"})
                return False
            if not hmac.compare_digest(
                self.headers.get("Authorization", ""), "Bearer " + bridge.api_key
            ):
                self.reply(401, {"error": "Invalid bridge token"})
                return False
            return True

        def do_POST(self):
            if not self.authorized():
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 18 * 1024 * 1024:
                    raise ValueError("Request too large or empty")
                self.connection.settimeout(30)
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError("Expected an object")
            except (ValueError, OSError):
                self.reply(400, {"error": "Invalid request body"})
                return
            if self.path == "/config":
                self.reply(
                    200,
                    {
                        "models": [
                            {
                                "id": key,
                                "label": value["label"],
                                "vision": value.get("vision", False),
                            }
                            for key, value in bridge.models.items()
                        ],
                        "default_model": bridge.default_model,
                        "workspace_connected": bool(
                            bridge.workspace_client
                            and bridge.workspace_client.connected
                        ),
                        "max_attachment_mb": 4,
                    },
                )
                return
            if self.path == "/sessions":
                with bridge.lock:
                    if len(bridge.sessions) >= bridge.max_sessions:
                        self.reply(
                            429,
                            {
                                "error": "Close an existing chat before creating another"
                            },
                        )
                        return
                    sid = uuid.uuid4().hex
                    agent = bridge.agent.clone(
                        history=[],
                        session_id=None,
                        session_store=InMemorySessionStore(),
                        prompt=(bridge.agent.prompt or "") + "\n" + BROWSER_PROMPT,
                    )
                    bridge.sessions[sid] = (
                        agent.chat_session(session_id=sid),
                        threading.Lock(),
                    )
                    if bridge.workspace_client:
                        from shipit_agent.browser_workspace import WorkspaceTool

                        tool = WorkspaceTool(bridge.workspace_client)
                        agent.tools = [*agent.tools, tool]
                        bridge.workspace_tools[sid] = tool
                self.reply(201, {"session_id": sid})
                return
            if self.path not in ("/chat", "/sessions/delete", "/workspace/apply"):
                self.reply(404, {"error": "Unknown route"})
                return
            sid = body.get("session_id")
            with bridge.lock:
                entry = bridge.sessions.get(sid) if isinstance(sid, str) else None
                if entry is None:
                    self.reply(404, {"error": "Chat expired; start a new chat"})
                    return
                chat, lock = entry
                if not lock.acquire(blocking=False):
                    self.reply(409, {"error": "This chat is still running"})
                    return
                if self.path == "/sessions/delete":
                    del bridge.sessions[sid]
                    bridge.workspace_tools.pop(sid, None)
                    lock.release()
                    self.reply(200, {"deleted": True})
                    return
            try:
                if self.path == "/workspace/apply":
                    tool = bridge.workspace_tools.get(sid)
                    try:
                        if tool is None or type(body.get("approve")) is not bool:
                            raise ValueError(
                                "Workspace is unavailable or approval is invalid"
                            )
                        result = tool.apply(
                            body.get("proposal_id"), body["approve"]
                        )
                        from shipit_agent.models import Message

                        record = chat.session_store.load(sid)
                        if record:
                            record.messages.append(
                                Message(
                                    role="user",
                                    content="Workspace action result: "
                                    + json.dumps(result),
                                )
                            )
                            chat.session_store.save(record)
                        self.reply(200, result)
                    except (ValueError, OSError) as exc:
                        self.reply(400, {"error": str(exc)})
                    return
                try:
                    prompt = browser_prompt(body)
                    images, documents = decode_uploads(body.get("attachments"))
                    prompt = append_documents(prompt, documents)
                    model_id = body.get("model", bridge.default_model)
                    if not isinstance(model_id, str):
                        raise ValueError("Choose a configured model")
                    model = bridge.models.get(model_id)
                    if model is None:
                        raise ValueError("Choose a configured model")
                    if images and not model.get("vision"):
                        raise ValueError(
                            "This model is not configured for image input"
                        )
                    chat.agent = chat.agent.clone(llm=model["llm"])
                except ValueError as exc:
                    self.reply(400, {"error": str(exc)})
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True

                def emit(value):
                    self.wfile.write(
                        ("data: " + json.dumps(_jsonable(value)) + "\n\n").encode()
                    )
                    self.wfile.flush()

                try:
                    with closing(chat.stream(prompt, images=images)) as events:
                        for event in events:
                            if event.type in {
                                "text_delta",
                                "run_completed",
                                "tool_called",
                                "tool_completed",
                                "tool_failed",
                                "tool_denied",
                                "context_compaction_started",
                                "context_compacted",
                                "usage_tick",
                                "run_cancelled",
                                "error",
                            }:
                                emit({"type": event.type, "payload": event.payload})
                    workspace = bridge.workspace_tools.get(sid)
                    if workspace:
                        emit(
                            {
                                "type": "workspace_proposals",
                                "payload": {
                                    "proposals": workspace.public_proposals()
                                },
                            }
                        )
                    emit({"type": "done"})
                except (BrokenPipeError, ConnectionResetError):
                    pass
                except Exception:
                    try:
                        emit(
                            {
                                "type": "error",
                                "payload": {
                                    "message": "Agent run failed; check the local provider configuration"
                                },
                            }
                        )
                    except OSError:
                        pass
            finally:
                lock.release()
    return Handler
