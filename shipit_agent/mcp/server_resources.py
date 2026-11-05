"""A remote MCP server's resources and prompts, and the tool that reads resources."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .tools import MCPTool
from .transport import MCPError


@dataclass(slots=True)
class MCPResource:
    """A resource exposed by an MCP server (a file, table, doc, …)."""

    uri: str
    name: str = ""
    description: str = ""
    mime_type: str = ""


@dataclass(slots=True)
class MCPPrompt:
    """A prompt template exposed by an MCP server."""

    name: str
    description: str = ""
    arguments: list[dict[str, Any]] = field(default_factory=list)


class ResourcesAndPromptsMixin:
    """A remote MCP server's resources and prompts, and the tool that reads resources."""

    # ── resources ─────────────────────────────────────────────────────
    def list_resources(self) -> list[MCPResource]:
        """Resources the server exposes. Empty if unsupported."""
        try:
            self.initialize()
            items = self._paginated_items("resources/list", "resources")
        except MCPError:
            return []  # server doesn't implement resources
        return [
            MCPResource(
                uri=str(item.get("uri", "")),
                name=str(item.get("name", "")),
                description=str(item.get("description", "")),
                mime_type=str(item.get("mimeType", "")),
            )
            for item in items
        ]

    def read_resource(self, uri: str) -> str:
        """Read one resource's content (text parts joined; blobs noted)."""
        self.initialize()
        result = self.transport.request("resources/read", {"uri": uri})
        parts: list[str] = []
        for item in result.get("contents", []):
            if "text" in item:
                parts.append(str(item["text"]))
            elif "blob" in item:
                parts.append(f"[binary content: {item.get('mimeType', 'unknown')}]")
        return "\n".join(parts)

    # ── prompts ───────────────────────────────────────────────────────
    def list_prompts(self) -> list[MCPPrompt]:
        """Prompt templates the server exposes. Empty if unsupported."""
        try:
            self.initialize()
            items = self._paginated_items("prompts/list", "prompts")
        except MCPError:
            return []  # server doesn't implement prompts
        return [
            MCPPrompt(
                name=str(item.get("name", "")),
                description=str(item.get("description", "")),
                arguments=list(item.get("arguments", [])),
            )
            for item in items
        ]

    def get_prompt(self, name: str, arguments: dict[str, Any] | None = None) -> str:
        """Render a prompt template to plain text (role-prefixed)."""
        self.initialize()
        result = self.transport.request(
            "prompts/get", {"name": name, "arguments": arguments or {}}
        )
        lines: list[str] = []
        for message in result.get("messages", []):
            content = message.get("content", "")
            if isinstance(content, dict):
                content = content.get("text", "")
            role = message.get("role", "user")
            lines.append(f"[{role}] {content}" if role != "user" else str(content))
        return "\n".join(lines)

    def resource_tool(self) -> MCPTool:
        """A tool that lets the model browse/read this server's resources.

        Call with no ``uri`` to list what's available; pass ``uri`` to read
        one. Attach it alongside the server's tools::

            server = connect_mcp("filesystem", args=["."])
            agent = Agent(llm=llm, mcps=[server],
                          tools=[server.resource_tool()])
        """

        def handler(context: Any = None, uri: str = "", **_ignored: Any) -> str:
            if uri:
                return self.read_resource(uri)
            resources = self.list_resources()
            if not resources:
                return f"MCP server '{self.name}' exposes no resources."
            return "\n".join(
                f"{r.uri} — {r.name or r.description or r.mime_type}" for r in resources
            )

        return MCPTool(
            name=f"{self.name}_resources",
            description=(
                f"Browse and read resources exposed by the '{self.name}' MCP "
                "server. Call without arguments to list resource URIs; pass "
                "`uri` to read one."
            ),
            handler=handler,
            input_schema={
                "type": "object",
                "properties": {
                    "uri": {
                        "type": "string",
                        "description": "Resource URI to read (omit to list all)",
                    }
                },
                "required": [],
            },
            metadata={"server": self.name},
        )
