from __future__ import annotations

from dataclasses import dataclass, field

from shipit_agent.exceptions import DuplicateToolError
from shipit_agent.mcp import MCPServer, discover_mcp_tools
from shipit_agent.tools import Tool


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
