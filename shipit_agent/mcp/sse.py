"""MCP over the HTTP+SSE transport: a GET event stream, and POSTs for messages.

The older of MCP's two HTTP transports, and the one the Claude Agent SDK
calls ``{"type": "sse"}``. The client opens a long-lived GET stream; the
server's first ``endpoint`` event names the URL to POST JSON-RPC messages
to, and every response arrives back on the stream as a ``message`` event,
matched to its request by id. A reader thread owns the stream.
"""

from __future__ import annotations

import http.client
import json
import queue
import socket
import threading
from itertools import count
from typing import Any
from urllib.parse import urljoin, urlsplit

from .transport import MCPError


class MCPSSETransport:
    """Talk to an MCP server over HTTP+SSE."""

    def __init__(self, url: str, *, headers: dict[str, str] | None = None, timeout: float = 20.0) -> None:
        self.url = url
        self.headers = dict(headers or {})
        self.timeout = timeout
        self._ids = count(1)
        self._lock = threading.Lock()
        self._waiting: dict[int, queue.Queue[dict[str, Any]]] = {}
        self._endpoint: str | None = None
        self._ready = threading.Event()
        self._failure: str | None = None
        self._connection: http.client.HTTPConnection | None = None
        self._stream: http.client.HTTPResponse | None = None
        self._reader: threading.Thread | None = None

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        msg_id = next(self._ids)
        answer: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        with self._lock:
            self._waiting[msg_id] = answer
        try:
            self._post({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}})
            try:
                message = answer.get(timeout=self.timeout)
            except queue.Empty:
                raise MCPError(f"MCP server at {self.url} did not answer {method} in {self.timeout:.0f}s") from None
        finally:
            with self._lock:
                self._waiting.pop(msg_id, None)
        if "error" in message:
            raise MCPError(str(message["error"]))
        return dict(message.get("result") or {})

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._post({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def close(self) -> None:
        """Shut the stream's socket first: a plain close would wait for the reader's read to time out."""
        connection, self._connection = self._connection, None
        if connection is None:
            return
        if connection.sock is not None:
            try:
                connection.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        connection.close()

    def _post(self, message: dict[str, Any]) -> None:
        connection, path = self._connection_for(self._connect())
        try:
            connection.request("POST", path, body=json.dumps(message).encode("utf-8"),
                               headers={"content-type": "application/json", **self.headers})
            response = connection.getresponse()
            response.read()
            if response.status >= 400:
                raise MCPError(f"MCP server at {self.url} rejected a message with HTTP {response.status}")
        finally:
            connection.close()

    def _connection_for(self, url: str) -> tuple[http.client.HTTPConnection, str]:
        """A connection to *url* and the path to request; only http and https."""
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https"):
            raise MCPError(f"MCP SSE needs an http or https URL, not {url!r}")
        kind = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
        path = parts.path or "/"
        return kind(parts.netloc, timeout=self.timeout), f"{path}?{parts.query}" if parts.query else path

    def _connect(self) -> str:
        """Open the event stream once, and wait for the server to name its endpoint."""
        with self._lock:
            if self._reader is None:
                self._stream = self._open_stream()
                self._reader = threading.Thread(target=self._read, name="mcp-sse", daemon=True)
                self._reader.start()
        if not self._ready.wait(self.timeout) or self._endpoint is None:
            raise MCPError(self._failure or f"MCP server at {self.url} sent no endpoint")
        return self._endpoint

    def _open_stream(self) -> http.client.HTTPResponse:
        self._connection, path = self._connection_for(self.url)
        self._connection.request("GET", path, headers={"accept": "text/event-stream", **self.headers})
        response = self._connection.getresponse()
        if response.status != 200:
            raise MCPError(f"MCP server at {self.url} answered the event stream with HTTP {response.status}")
        return response

    def _read(self) -> None:
        event, data = "message", []
        stream = self._stream
        if stream is None:
            return
        try:
            for raw in stream:
                line = raw.decode("utf-8").rstrip("\r\n")
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    data.append(line[5:].lstrip())
                elif not line and data:
                    self._dispatch(event, "\n".join(data))
                    event, data = "message", []
            self._fail("the MCP event stream closed")
        except (OSError, ValueError) as exc:
            self._fail(f"the MCP event stream failed: {exc}")

    def _dispatch(self, event: str, data: str) -> None:
        if event == "endpoint":
            self._endpoint = urljoin(self.url, data)
            self._ready.set()
            return
        if event != "message":
            return
        message = json.loads(data)
        with self._lock:
            waiter = self._waiting.get(message.get("id"))
        if waiter is not None:
            waiter.put(message)

    def _fail(self, reason: str) -> None:
        """Answer every request still waiting, so none of them hangs."""
        self._failure = reason
        self._ready.set()
        with self._lock:
            waiting = list(self._waiting.values())
        for waiter in waiting:
            if waiter.empty():
                waiter.put({"error": reason})
