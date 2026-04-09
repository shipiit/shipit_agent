from __future__ import annotations

from typing import Any

from shipit_agent.builtins import get_builtin_tools
from shipit_agent.registry import ToolRegistry
from shipit_agent.mcp import MCPServer
from shipit_agent.tools import Tool


def construct_tool_registry(
    *,
    tools: list[Tool] | None = None,
    include_builtins: bool = False,
    llm=None,
    mcps: list[MCPServer] | None = None,
    workspace_root: str = ".shipit_workspace",
    web_search_provider: str = "duckduckgo",
    web_search_api_key: str | None = None,
    web_search_config: dict[str, Any] | None = None,
) -> ToolRegistry:
    resolved_tools = list(tools or [])
    if include_builtins:
        resolved_tools = [
            *get_builtin_tools(
                llm=llm,
                workspace_root=workspace_root,
                web_search_provider=web_search_provider,
                web_search_api_key=web_search_api_key,
                web_search_config=web_search_config,
            ),
            *resolved_tools,
        ]
    return ToolRegistry.build(tools=resolved_tools, mcps=mcps)


def build_tool_schemas(registry: ToolRegistry) -> list[dict[str, Any]]:
    return registry.schemas()
