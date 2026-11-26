"""What :class:`~shipit_agent.sdk.client.AgentClient` reports about a session.

Key names follow the Claude Agent SDK's responses (``totalTokens``,
``mcpServers``), so code that reads them works on either.
"""

from __future__ import annotations

import json
from typing import Any

__all__ = ["McpControls", "context_usage", "mcp_status"]


def context_usage(agent: Any) -> dict[str, Any]:
    """Estimated tokens in the context window, by category, without calling the model."""
    from shipit_agent.context.compaction import estimate_tokens, get_model_limits, messages_tokens

    model = str(getattr(agent.llm, "model", "") or "")
    limits = get_model_limits(model)
    schemas = [tool.schema() for tool in agent.tools if hasattr(tool, "schema")]
    record = agent.session_store.load(agent.session_id) if agent.session_store and agent.session_id else None
    categories = {
        "system_prompt": estimate_tokens(agent._effective_prompt("")),
        "tools": estimate_tokens(json.dumps(schemas, default=str)),
        "messages": messages_tokens(list(record.messages)) if record else 0,
    }
    total = sum(categories.values())
    return {
        "model": model,
        "categories": categories,
        "totalTokens": total,
        "maxTokens": limits.context_window,
        "percentage": round(100 * total / limits.context_window, 2) if limits.context_window else None,
        "isAutoCompactEnabled": True,
    }


def _name(server: Any) -> str:
    return str(getattr(server, "name", "mcp"))


class McpControls:
    """The MCP servers of one session: which are on, and restarting one.

    A server that is switched off stays known, so it can be switched back on;
    runs are only offered the tools of the servers that are on.
    """

    def __init__(self, agent: Any) -> None:
        self.agent = agent
        self.servers: list[Any] = list(agent.mcps)
        self.off: set[str] = set()

    def _sync(self) -> None:
        # A plugin may have added servers to the agent since the last call.
        known = {id(server) for server in self.servers}
        self.servers += [server for server in self.agent.mcps if id(server) not in known]

    def _find(self, name: str) -> Any:
        self._sync()
        for server in self.servers:
            if _name(server) == name:
                return server
        raise KeyError(f"no MCP server {name!r}")

    def toggle(self, name: str, enabled: bool) -> None:
        self._find(name)
        (self.off.discard if enabled else self.off.add)(name)
        self.agent.mcps = [server for server in self.servers if _name(server) not in self.off]

    def reconnect(self, name: str) -> None:
        """Close the server's connection and open it again; raises if it will not start."""
        server = self._find(name)
        for step in ("close", "invalidate_tools_cache"):
            method = getattr(server, step, None)
            if callable(method):
                method()
        server.discover_tools()

    def status(self) -> dict[str, Any]:
        """Each server's state (``connected``, ``failed`` or ``disabled``) and its tools."""
        self._sync()
        servers = []
        for server in self.servers:
            entry: dict[str, Any] = {"name": _name(server), "error": None, "tools": []}
            if entry["name"] in self.off:
                entry["status"] = "disabled"
            else:
                try:
                    entry["tools"] = [{"name": str(tool.name)} for tool in server.discover_tools()]
                    entry["status"] = "connected"
                except Exception as error:  # a server that will not start is the status, not a crash
                    entry["status"] = "failed"
                    entry["error"] = f"{type(error).__name__}: {error}"
            servers.append(entry)
        return {"mcpServers": servers}


def mcp_status(agent: Any) -> dict[str, Any]:
    """Each MCP server's state and tools; asking a server for its tools connects it."""
    return McpControls(agent).status()
