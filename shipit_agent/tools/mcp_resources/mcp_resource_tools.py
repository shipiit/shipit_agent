"""List and read the resources of the run's MCP servers (files, tables, documents).

The servers are the ones switched on for this run, read from the shared tool
state at call time, so a server switched off between turns is not reachable.
Both tools answer in the Claude Agent SDK's shapes, as JSON.
"""

from __future__ import annotations

import json
from typing import Any

from shipit_agent.tools.base import ToolContext, ToolOutput

#: The shared-state key that holds the run's MCP servers.
SERVERS_KEY = "mcp_servers"


def _servers(context: ToolContext) -> list[Any]:
    return list(context.state.get(SERVERS_KEY) or [])


def _name(server: Any) -> str:
    return str(getattr(server, "name", "mcp"))


def _known(servers: list[Any]) -> str:
    return ", ".join(_name(server) for server in servers) or "none are connected"


def _function(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required},
    }}


class ListMcpResourcesTool:
    """Every resource the run's MCP servers offer, optionally from one server."""

    name = "list_mcp_resources"
    description = "List the resources (files, tables, documents) the connected MCP servers offer."
    prompt_instructions = "List MCP resources before reading one, to learn its server and uri."
    read_only = True

    def schema(self) -> dict[str, Any]:
        return _function(self.name, self.description,
                         {"server": {"type": "string", "description": "Only this server's resources"}}, [])

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        servers = _servers(context)
        wanted = str(kwargs.get("server") or "").strip()
        if wanted:
            matching = [server for server in servers if _name(server) == wanted]
            if not matching:
                return ToolOutput.error(f"There is no MCP server {wanted!r}. Servers: {_known(servers)}.")
            servers = matching
        listed = []
        for server in servers:
            lister = getattr(server, "list_resources", None)
            if not callable(lister):
                continue
            for resource in lister():
                listed.append({
                    "uri": resource.uri,
                    "name": resource.name,
                    "mimeType": resource.mime_type or None,
                    "description": resource.description or None,
                    "server": _name(server),
                })
        return ToolOutput(text=json.dumps(listed), metadata={"resources": len(listed)})


class ReadMcpResourceTool:
    """One resource's content, from the server that offers it."""

    name = "read_mcp_resource"
    description = "Read a resource from an MCP server, by the server's name and the resource's uri."
    prompt_instructions = "Use list_mcp_resources first to find the server and uri to read."
    read_only = True

    def schema(self) -> dict[str, Any]:
        return _function(self.name, self.description, {
            "server": {"type": "string", "description": "The MCP server's name"},
            "uri": {"type": "string", "description": "The resource's uri"},
        }, ["server", "uri"])

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        name = str(kwargs.get("server") or "").strip()
        uri = str(kwargs.get("uri") or "").strip()
        servers = _servers(context)
        if not name or not uri:
            return ToolOutput.error("Pass both `server` and `uri`; list_mcp_resources shows them.")
        server = next((s for s in servers if _name(s) == name), None)
        if server is None:
            return ToolOutput.error(f"There is no MCP server {name!r}. Servers: {_known(servers)}.")
        transport = getattr(server, "transport", None)
        if transport is None or not callable(getattr(server, "list_resources", None)):
            return ToolOutput.error(f"The MCP server {name!r} does not offer resources.")
        try:
            initialize = getattr(server, "initialize", None)
            if callable(initialize):
                initialize()
            result = transport.request("resources/read", {"uri": uri})
        except Exception as error:  # a failed read is the model's to act on, not a crash
            body = {"contents": [], "error": f"{type(error).__name__}: {error}"}
            return ToolOutput.error(json.dumps(body))
        contents = []
        for item in result.get("contents") or []:
            if not isinstance(item, dict):
                continue
            mime_type = item.get("mimeType")
            text = item.get("text")
            if text is None and "blob" in item:
                text = f"[binary {mime_type or 'unknown'} content not shown]"
            contents.append({"uri": str(item.get("uri") or uri), "mimeType": mime_type, "text": text, "blobSavedTo": None})
        return ToolOutput(text=json.dumps({"contents": contents, "error": None}))
