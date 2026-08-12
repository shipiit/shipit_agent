from __future__ import annotations

import logging
from dataclasses import dataclass, field

from shipit_agent.exceptions import DuplicateToolError
from shipit_agent.mcp import MCPServer, _sanitize_tool_name, discover_mcp_tools
from shipit_agent.tools import Tool

logger = logging.getLogger(__name__)


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
        for mcp in mcps or []:
            for tool in discover_mcp_tools(mcp):
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
