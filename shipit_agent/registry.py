from __future__ import annotations

from dataclasses import dataclass, field
from shipit_agent.exceptions import DuplicateToolError
from shipit_agent.mcp import MCPServer, RemoteMCPServer, discover_mcp_tools
from shipit_agent.tools import Tool


def normalize_tool_schema(schema: dict[str, object]) -> dict[str, object]:
    """Give an object parameter block the ``properties`` key OpenAI requires.

    A zero-argument tool may legally publish ``{"type": "object"}`` and stop —
    JSON Schema does not require ``properties``, and MCP servers do exactly
    this for tools that take nothing. OpenAI-compatible endpoints reject it:
    *"object schema missing properties"*. The request fails as a whole, so the
    symptom is not "one tool misbehaves" but an agent that calls nothing at
    all, on every turn, with no obvious cause.

    Seeding an empty ``properties`` changes nothing about what the tool
    accepts — it says explicitly what the omission already meant — and it is
    applied here, at the single point every schema passes through, so local
    tools and MCP tools are covered by one rule.

    Anything that is not an object parameter block is returned untouched: this
    normalises a known incompatibility, it does not rewrite tool declarations.
    """
    if not isinstance(schema, dict):
        return schema
    function = schema.get("function")
    body = function if isinstance(function, dict) else schema
    parameters = body.get("parameters")
    if not isinstance(parameters, dict):
        return schema
    if parameters.get("type", "object") != "object" or "properties" in parameters:
        return schema
    patched_parameters = {**parameters, "type": "object", "properties": {}}
    patched_body = {**body, "parameters": patched_parameters}
    if isinstance(function, dict):
        return {**schema, "function": patched_body}
    return patched_body


@dataclass(slots=True)
class ToolRegistry:
    tools: dict[str, Tool] = field(default_factory=dict)
    deferred_mcps: list[MCPServer] = field(default_factory=list)

    @classmethod
    def build(
        cls,
        *,
        tools: list[Tool] | None = None,
        mcps: list[MCPServer] | None = None,
        defer_mcps: bool = False,
    ) -> "ToolRegistry":
        registry = cls()
        for tool in tools or []:
            registry.register(tool)
        for mcp in mcps or []:
            # Hand-built MCPServer tools are already in memory and cost no
            # transport startup. Only remote catalogs need true deferred
            # discovery; local tools can be registered now and schema-hidden
            # later by progressive context filtering.
            if defer_mcps and isinstance(mcp, RemoteMCPServer):
                registry.deferred_mcps.append(mcp)
                continue
            for tool in discover_mcp_tools(mcp):
                # Keep server provenance on local MCPTool instances too.
                # Remote tools already provide this, but hand-built servers
                # otherwise became indistinguishable from custom tools.
                metadata = getattr(tool, "metadata", None)
                if isinstance(metadata, dict):
                    metadata.setdefault("server", mcp.name)
                registry.register(tool)
        return registry

    def discover_deferred_mcps(
        self, server_names: set[str] | None = None
    ) -> tuple[list[Tool], list[dict[str, str]]]:
        """Discover deferred MCP catalogs once and add them to this registry."""
        discovered: list[Tool] = []
        failures: list[dict[str, str]] = []
        pending = [
            mcp
            for mcp in self.deferred_mcps
            if server_names is None or mcp.name in server_names
        ]
        self.deferred_mcps = [mcp for mcp in self.deferred_mcps if mcp not in pending]
        for mcp in pending:
            try:
                tools = discover_mcp_tools(mcp)
                for tool in tools:
                    metadata = getattr(tool, "metadata", None)
                    if isinstance(metadata, dict):
                        metadata.setdefault("server", mcp.name)
                    self.register(tool)
                    discovered.append(tool)
            except Exception as exc:  # MCP failures must not hide local tools.
                failures.append({"server": mcp.name, "error": str(exc)})
        return discovered, failures

    def register(self, tool: Tool) -> None:
        if tool.name in self.tools:
            raise DuplicateToolError(f"Duplicate tool name: {tool.name}")
        self.tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self.tools.get(name)

    def values(self) -> list[Tool]:
        return list(self.tools.values())

    def schemas(self) -> list[dict[str, object]]:
        return [normalize_tool_schema(tool.schema()) for tool in self.values()]
