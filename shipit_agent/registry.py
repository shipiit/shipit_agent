from __future__ import annotations

import logging
from dataclasses import dataclass, field

from shipit_agent.exceptions import DuplicateToolError
from shipit_agent.mcp import MCPServer, _sanitize_tool_name, discover_mcp_tools
from shipit_agent.tools import Tool

logger = logging.getLogger(__name__)

#: Cap on concurrent MCP discovery handshakes.
_MCP_DISCOVER_MAX_WORKERS = 16


def _safe_discover(mcp: MCPServer) -> list:
    """Discover one server's tools, or an empty list if it is unreachable.

    A dead server — a sleeping laptop, an expired token, a container still
    starting — used to re-raise and fail the WHOLE run at construction, taking
    every unrelated tool with it. One connector being down is not a reason the
    agent cannot run at all, so its failure is isolated: logged, and its tools
    simply absent. (An unreachable server with a *cached* schema is surfaced as
    an :class:`UnavailableTool` stub by the caller that holds the cache; with
    nothing cached there is no honest tool list to advertise, so it is empty.)
    """
    try:
        return list(discover_mcp_tools(mcp))
    except Exception as exc:  # noqa: BLE001 — one dead server must not fail the run
        logger.warning(
            "MCP server %r discovery failed (%s: %s); its tools are unavailable "
            "this run", getattr(mcp, "name", "?"), type(exc).__name__, exc)
        return []


def _discover_mcp_parallel(
    mcps: list[MCPServer],
) -> list[tuple[MCPServer, list]]:
    """Discover every server's tools concurrently, returned in input order.

    Parallelises only the slow part (each server's connect handshake); the
    caller registers the results serially. A server that fails to connect is
    isolated (see :func:`_safe_discover`) rather than taking the run down.
    """
    if not mcps:
        return []
    if len(mcps) == 1:
        return [(mcps[0], _safe_discover(mcps[0]))]

    from concurrent.futures import ThreadPoolExecutor

    workers = min(_MCP_DISCOVER_MAX_WORKERS, len(mcps))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="mcp-discover") as pool:
        futures = [pool.submit(_safe_discover, mcp) for mcp in mcps]
        return [(mcp, future.result()) for mcp, future in zip(mcps, futures)]


class UnavailableTool:
    """Stand-in for a tool whose MCP server is unreachable this run.

    When a server's schema is cached but the server is down, dropping its tools
    silently makes the model reach for a name that "vanished". A stub is more
    honest: it advertises itself as unavailable in its own description (which the
    model reads before ever calling it), and if called anyway it explains the
    situation and says not to retry — rather than a hard error the model treats
    as its own mistake. It is read-only, so no approval gate fires on a
    guaranteed no-op, and it accepts any arguments because the real schema is,
    by definition, unknown.
    """

    read_only = True
    prompt_instructions = ""

    def __init__(self, name: str, server: str, error: str = "") -> None:
        self.name = name
        self.server = server
        self.error = error
        self.description = (
            f"[UNAVAILABLE] '{name}' — its server '{server}' is unreachable "
            f"this run. Do not call it; it cannot run."
        )
        self.metadata: dict = {"server": server, "unavailable": True}

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {"type": "object", "properties": {}},
            },
        }

    def run(self, context, **kwargs):
        from shipit_agent.tools.base import ToolOutput

        detail = f" ({self.error})" if self.error else ""
        return ToolOutput(
            text=(
                f"Tool '{self.name}' from server '{self.server}' is currently "
                f"UNAVAILABLE{detail}. Do not retry it this run; use another "
                f"approach."
            ),
            metadata={"error": "mcp_unavailable", "server": self.server},
        )


@dataclass(slots=True)
class ToolRegistry:
    tools: dict[str, Tool] = field(default_factory=dict)

    @classmethod
    def build(
        cls,
        *,
        tools: list[Tool] | None = None,
        mcps: list[MCPServer] | None = None,
    ) -> "ToolRegistry":
        registry = cls()
        for tool in tools or []:
            registry.register(tool)
        # Discover all MCP servers concurrently — each connect is a network
        # handshake (stdio spawn / HTTP round-trip), so 20 servers done serially
        # is 20× the latency of doing them at once. Registration below stays
        # ordered and single-threaded, so collision handling is unchanged.
        for mcp, discovered in _discover_mcp_parallel(mcps or []):
            for tool in discovered:
                # Keep server provenance on local MCPTool instances too.
                # Remote tools already provide this, but hand-built servers
                # otherwise became indistinguishable from custom tools.
                metadata = getattr(tool, "metadata", None)
                if isinstance(metadata, dict):
                    metadata.setdefault("server", mcp.name)
                # Two servers exposing the same tool name is a config fact,
                # not a bug the user can fix at run start — the later tool is
                # re-exposed as `{server}__{name}` instead of crashing the
                # run. Hand-written duplicates still raise: those ARE bugs.
                if tool.name in registry.tools:
                    renamed = _sanitize_tool_name(f"{mcp.name}__{tool.name}")
                    logger.warning(
                        "MCP tool name collision: %r exists; exposing %s's as %r",
                        tool.name,
                        mcp.name,
                        renamed,
                    )
                    tool.name = renamed
                registry.register(tool)
        return registry

    def register(self, tool: Tool) -> None:
        if tool.name in self.tools:
            raise DuplicateToolError(f"Duplicate tool name: {tool.name}")
        self.tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self.tools.get(name)

    def values(self) -> list[Tool]:
        return list(self.tools.values())

    def schemas(self) -> list[dict[str, object]]:
        return [tool.schema() for tool in self.values()]
