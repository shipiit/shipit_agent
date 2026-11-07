"""The transport interface every MCP connection implements, and the error it raises."""

from __future__ import annotations

from typing import Any, Protocol

MCP_PROTOCOL_VERSION = "2025-11-25"


_MAX_TOOL_NAME_LENGTH = 64


#: Per-request ceiling for MCP servers. A wedged server without one hangs
#: the whole run forever — cancel() only takes effect between steps.
_MCP_DEFAULT_TIMEOUT = 60.0


class MCPTransport(Protocol):
    """How a client sends JSON-RPC requests and notifications to an MCP server."""

    def request(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None: ...

    def close(self) -> None: ...


class MCPError(RuntimeError):
    """An MCP server returned an error, timed out, or could not be reached."""

    pass
