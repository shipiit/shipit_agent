"""What :class:`~shipit_agent.sdk.client.AgentClient` reports about a session.

Key names follow the Claude Agent SDK's responses (``totalTokens``,
``mcpServers``), so code that reads them works on either.
"""

from __future__ import annotations

import json
from typing import Any

__all__ = ["context_usage", "mcp_status"]


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


def mcp_status(agent: Any) -> dict[str, Any]:
    """Each MCP server's state and tools; asking a server for its tools connects it."""
    servers = []
    for server in agent.mcps:
        entry: dict[str, Any] = {"name": str(getattr(server, "name", "mcp")), "error": None, "tools": []}
        try:
            entry["tools"] = [{"name": str(tool.name)} for tool in server.discover_tools()]
            entry["status"] = "connected"
        except Exception as error:  # a server that will not start is the status, not a crash
            entry["status"] = "failed"
            entry["error"] = f"{type(error).__name__}: {error}"
        servers.append(entry)
    return {"mcpServers": servers}
