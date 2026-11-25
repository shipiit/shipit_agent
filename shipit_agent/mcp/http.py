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
        request_id = next(self._id_counter)
        payload = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": request_id,
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
        return _result_for(_load_json(body), request_id)

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
        request_id = next(self._id_counter)
        payload = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": request_id,
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
            content_type = (response.headers.get("Content-Type") or "").lower()
            body = response.read().decode("utf-8")
        if "text/event-stream" in content_type:
            parsed = self._parse_sse(body, request_id)
        else:
            parsed = _load_json(body)
        result = _result_for(parsed, request_id)
        if session_id:
            # Only a reply that answers this request may move the session.
            self._session_id = session_id
        return result

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
    def _parse_sse(body: str, request_id: int | None = None) -> dict[str, Any]:
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
            # Notifications have no id; replies to other requests have another one.
            if not isinstance(parsed, dict) or ("result" not in parsed and "error" not in parsed):
                continue
            if request_id is None or _same_id(parsed.get("id"), request_id):
                return parsed
        raise MCPError("No JSON-RPC response found in SSE stream.")


def _load_json(body: str) -> Any:
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise MCPError(f"MCP server sent a body that is not JSON: {exc}") from exc


def _same_id(value: Any, request_id: int) -> bool:
    # ``True == 1`` in Python, and "1" is not 1: the id must be this exact integer.
    return type(value) is int and value == request_id


def _result_for(parsed: Any, request_id: int) -> dict[str, Any]:
    """The ``result`` of the reply to *request_id*; anything else is an :class:`MCPError`."""
    if not isinstance(parsed, dict):
        raise MCPError("MCP server sent a reply that is not a JSON-RPC object.")
    if not _same_id(parsed.get("id"), request_id):
        raise MCPError(f"MCP response id {parsed.get('id')!r} does not match request id {request_id}.")
    if "error" in parsed:
        raise MCPError(str(parsed["error"]))
    result = parsed.get("result")
    if not isinstance(result, dict):
        raise MCPError("MCP reply has no result object.")
    return result
