from __future__ import annotations

import logging
from dataclasses import dataclass, field

from shipit_agent.exceptions import DuplicateToolError
from shipit_agent.mcp import MCPServer, _sanitize_tool_name, discover_mcp_tools
from shipit_agent.tools import Tool

logger = logging.getLogger(__name__)

#: Cap on concurrent MCP discovery handshakes.
_MCP_DISCOVER_MAX_WORKERS = 16


def _discover_mcp_parallel(
    mcps: list[MCPServer],
) -> list[tuple[MCPServer, list]]:
    """Discover every server's tools concurrently, returned in input order.

    Parallelises only the slow part (each server's connect handshake); the
    caller registers the results serially. A server that fails to connect
    re-raises exactly as the old serial path did — ``future.result()`` surfaces
    it when its turn comes, so error behaviour is unchanged, only faster.
    """
    if not mcps:
        return []
    if len(mcps) == 1:
        return [(mcps[0], list(discover_mcp_tools(mcps[0])))]

    from concurrent.futures import ThreadPoolExecutor

    workers = min(_MCP_DISCOVER_MAX_WORKERS, len(mcps))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="mcp-discover") as pool:
        futures = [pool.submit(discover_mcp_tools, mcp) for mcp in mcps]
        return [(mcp, list(future.result())) for mcp, future in zip(mcps, futures)]


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
