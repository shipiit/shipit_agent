"""MCP servers: the in-process kind, and a remote one reached through a transport."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from shipit_agent.tools.base import ToolContext

from .server_discovery import ToolDiscoveryMixin
from .server_resources import ResourcesAndPromptsMixin
from .tools import MCPRemoteTool, MCPTool
from .transport import MCP_PROTOCOL_VERSION, MCPError, MCPTransport


@dataclass(slots=True)
class MCPServer:
    """A named group of MCP tools that can be attached to an agent."""

    name: str
    tools: list[MCPTool | MCPRemoteTool] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def register(self, tool: MCPTool | MCPRemoteTool) -> "MCPServer":
        self.tools.append(tool)
        return self

    def register_many(self, tools: list[MCPTool | MCPRemoteTool]) -> "MCPServer":
        self.tools.extend(tools)
        return self

    def discover_tools(self) -> list[MCPTool | MCPRemoteTool]:
        return list(self.tools)


@dataclass(slots=True)
class RemoteMCPServer(ResourcesAndPromptsMixin, ToolDiscoveryMixin, MCPServer):
    """An MCP server reached through a transport.

    Discovers the server's tools (filtered by ``allowed_tools`` and
    ``blocked_tools``) and makes them callable by an agent.
    """

    transport: MCPTransport | None = None
    protocol_version: str = MCP_PROTOCOL_VERSION
    allowed_tools: set[str] | None = None
    blocked_tools: set[str] = field(default_factory=set)
    tool_filter: Callable[[dict[str, Any]], bool] | None = None
    include_server_in_tool_names: bool = False
    tool_meta_resolver: (
        Callable[[ToolContext, str, dict[str, Any]], dict[str, Any] | None] | None
    ) = None
    server_capabilities: dict[str, Any] = field(default_factory=dict)
    server_info: dict[str, Any] = field(default_factory=dict)
    #: The server's own usage guidance from the `initialize` handshake.
    instructions: str = ""
    #: Opt-in warm start: persist the tool schema to disk and, on a later run,
    #: rebuild the tools from that cache without spawning the process until a
    #: tool is actually called. Off by default — it moves connect-time errors to
    #: first-call time, so a caller asks for it explicitly.
    #:
    #: Trade-off worth knowing: within one ``cache_ttl`` window a tool removed
    #: server-side stays offered from the cache; calling it returns a normal MCP
    #: error (handled, not a crash), and the next cold discovery after the TTL
    #: drops it. Shorten ``cache_ttl`` if a server's toolset changes often.
    cache: bool = False
    #: Warm-start freshness window (seconds). A cache older than this is a miss.
    cache_ttl: float = 24 * 60 * 60
    _discovered: bool = False
    _initialized: bool = False
    _handshook_generation: int = 0
    #: True when tools were built from the cache and the process has not been
    #: spawned yet — the flag that keeps every-turn re-discovery from eagerly
    #: initializing before the first real tool call.
    _lazy_pending: bool = False

    def initialize(self) -> None:
        if self.transport is None:
            raise MCPError("RemoteMCPServer requires a transport.")
        # A transport that respawned its process (crash mid-run) bumps its
        # generation; the new process has never seen `initialize`, and most
        # servers reject or misbehave on `tools/call` without the handshake.
        generation = getattr(self.transport, "generation", None)
        if self._initialized and generation not in (None, 0):
            if generation != self._handshook_generation:
                self._initialized = False
        if self._initialized:
            return
        result = self.transport.request(
            "initialize",
            {
                "protocolVersion": self.protocol_version,
                "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                "clientInfo": {"name": "shipit_agent", "version": "1.0.0"},
            },
        )
        self.protocol_version = str(
            result.get("protocolVersion") or self.protocol_version
        )
        self.server_capabilities = dict(result.get("capabilities", {}))
        self.server_info = dict(result.get("serverInfo", {}))
        # The spec's `instructions` field is the server telling the model
        # how to use it — dropping it wasted the server author's one channel.
        self.instructions = str(result.get("instructions") or "")
        notify = getattr(self.transport, "notify", None)
        if callable(notify):
            notify("notifications/initialized", {})
        self._initialized = True
        self._handshook_generation = getattr(self.transport, "generation", 0)

    def _tool_allowed(self, item: dict[str, Any]) -> bool:
        name = str(item.get("name", ""))
        if self.allowed_tools is not None and name not in self.allowed_tools:
            return False
        if name in self.blocked_tools:
            return False
        return self.tool_filter(item) if self.tool_filter is not None else True

    def _paginated_items(self, method: str, key: str) -> list[dict[str, Any]]:
        """Collect every MCP cursor page and reject looping server cursors."""
        if self.transport is None:
            raise MCPError("RemoteMCPServer requires a transport.")
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        seen: set[str] = set()
        while True:
            params = {"cursor": cursor} if cursor is not None else {}
            result = self.transport.request(method, params)
            items.extend(item for item in result.get(key, []) if isinstance(item, dict))
            next_cursor = result.get("nextCursor")
            if next_cursor in (None, ""):
                return items
            next_cursor = str(next_cursor)
            if next_cursor in seen:
                raise MCPError(
                    f"MCP server '{self.name}' repeated cursor {next_cursor!r} "
                    f"while handling {method}."
                )
            seen.add(next_cursor)
            cursor = next_cursor

    def invalidate_tools_cache(self) -> None:
        """Force live tool discovery on the next registry construction."""
        if self.cache:
            from shipit_agent import mcp_schema_cache

            mcp_schema_cache.invalidate(self.name, self._cache_fingerprint())
        self.tools = []
        self._discovered = False
        self._lazy_pending = False

    def _ensure_ready(self) -> None:
        """Run the handshake before the first cached tool call; clean up on fail.

        Passed to every :class:`MCPRemoteTool` as its ``ensure_ready``. On a
        cache-warm server this is where the process finally spawns. If it fails
        we close the transport (matching the live-discovery path) so a
        half-spawned subprocess never leaks, then re-raise for ``run`` to surface.
        """
        try:
            self.initialize()
        except Exception:
            self.close()
            raise
        self._lazy_pending = False

    def close(self) -> None:
        if self.transport is not None and hasattr(self.transport, "close"):
            self.transport.close()
        # Closing ends the MCP protocol session even when the transport object
        # is reusable. Keep discovered schemas, but handshake again next turn.
        self._initialized = False
        # `close_mcps()` runs at the end of EVERY turn. For a cache-registered
        # server, return to the lazy state so the next turn re-registers its
        # tools from memory without respawning — an unused server then costs
        # nothing, turn after turn, which is the entire point of the cache.
        # (A plain server stays eager, exactly as before.)
        if self.cache and self._discovered:
            self._lazy_pending = True


def discover_mcp_tools(server: MCPServer) -> list[MCPTool | MCPRemoteTool]:
    """The tools *server* offers."""
    return server.discover_tools()
