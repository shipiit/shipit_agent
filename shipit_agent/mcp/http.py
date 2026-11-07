"""MCP over HTTP: plain JSON-RPC posts, and the Streamable HTTP transport."""

from __future__ import annotations

import json
from itertools import count
from typing import Any
from urllib import request

from .transport import MCPError


class MCPHTTPTransport:
    """Talk to an MCP server over HTTP with JSON-RPC POST requests."""

    def __init__(
        self,
        endpoint: str,
        *,
        headers: dict[str, str] | None = None,
        timeout: float = 20.0,
        bearer_token: str | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.headers = dict(headers or {})
        if bearer_token:
            self.headers.setdefault("authorization", f"Bearer {bearer_token}")
        self.timeout = timeout
        self._id_counter = count(1)

    def request(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        payload = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": next(self._id_counter),
                "method": method,
                "params": params or {},
            }
        ).encode("utf-8")
        req = request.Request(
            self.endpoint,
            data=payload,
            headers={"content-type": "application/json", **self.headers},
            method="POST",
        )
        with request.urlopen(req, timeout=self.timeout) as response:  # nosec B310
            body = response.read().decode("utf-8")
        parsed = json.loads(body) if body else {}
        if "error" in parsed:
            raise MCPError(str(parsed["error"]))
        return dict(parsed.get("result", {}))

    def close(self) -> None:
        return None

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        payload = json.dumps(
            {
                "jsonrpc": "2.0",
                "method": method,
                "params": params or {},
            }
        ).encode("utf-8")
        req = request.Request(
            self.endpoint,
            data=payload,
            headers={"content-type": "application/json", **self.headers},
            method="POST",
        )
        with request.urlopen(req, timeout=self.timeout):  # nosec B310
            pass


class MCPStreamableHTTPTransport(MCPHTTPTransport):
    """Streamable-HTTP MCP transport (the 2025 spec revision).

    POSTs JSON-RPC like :class:`MCPHTTPTransport`, but also handles servers
    that answer with ``text/event-stream`` — the JSON-RPC response arrives
    as SSE ``data:`` lines. Also carries the ``Mcp-Session-Id`` header the
    spec uses for session affinity. Pass ``bearer_token=`` for servers
    behind OAuth/bearer auth.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._session_id: str | None = None

    def request(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        payload = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": next(self._id_counter),
                "method": method,
                "params": params or {},
            }
        ).encode("utf-8")
        headers = {
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
            **self.headers,
        }
        if self._session_id:
            headers["mcp-session-id"] = self._session_id
        req = request.Request(
            self.endpoint, data=payload, headers=headers, method="POST"
        )
        with request.urlopen(req, timeout=self.timeout) as response:  # nosec B310
            session_id = response.headers.get("Mcp-Session-Id")
            if session_id:
                self._session_id = session_id
            content_type = (response.headers.get("Content-Type") or "").lower()
            body = response.read().decode("utf-8")
        if "text/event-stream" in content_type:
            parsed = self._parse_sse(body)
        else:
            parsed = json.loads(body) if body else {}
        if "error" in parsed:
            raise MCPError(str(parsed["error"]))
        return dict(parsed.get("result", {}))

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        """Send a session-affine JSON-RPC notification."""
        payload = json.dumps(
            {
                "jsonrpc": "2.0",
                "method": method,
                "params": params or {},
            }
        ).encode("utf-8")
        headers = {
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
            **self.headers,
        }
        if self._session_id:
            headers["mcp-session-id"] = self._session_id
        req = request.Request(
            self.endpoint, data=payload, headers=headers, method="POST"
        )
        with request.urlopen(req, timeout=self.timeout):  # nosec B310
            pass

    def close(self) -> None:
        """Ask a stateful server to terminate its MCP session."""
        session_id, self._session_id = self._session_id, None
        if not session_id:
            return
        req = request.Request(
            self.endpoint,
            headers={"mcp-session-id": session_id, **self.headers},
            method="DELETE",
        )
        try:
            with request.urlopen(req, timeout=self.timeout):  # nosec B310
                pass
        except OSError:
            # Session deletion is optional and close must remain idempotent.
            return

    @staticmethod
    def _parse_sse(body: str) -> dict[str, Any]:
        """Extract the JSON-RPC response from SSE `data:` lines."""
        # HTTP servers commonly use CRLF framing. Splitting the raw body on
        # ``\n\n`` merges every CRLF event into one invalid JSON blob, which
        # made long-running MCP calls fail while short JSON responses worked.
        normalized = body.replace("\r\n", "\n").replace("\r", "\n")
        for chunk in normalized.split("\n\n"):
            data_lines = [
                line[5:].strip()
                for line in chunk.splitlines()
                if line.startswith("data:")
            ]
            if not data_lines:
                continue
            try:
                parsed = json.loads("\n".join(data_lines))
            except json.JSONDecodeError:
                continue
            # The response to our request carries an id (notifications don't).
            if isinstance(parsed, dict) and ("result" in parsed or "error" in parsed):
                return parsed
        raise MCPError("No JSON-RPC response found in SSE stream.")
