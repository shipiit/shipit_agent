from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from shipit_agent.tools import Tool
from shipit_agent.tools.contracts import contract_for


_TOOL_FAMILIES: dict[str, set[str]] = {
    "web & browsing": {"web_search", "open_url", "playwright_browse"},
    "files & code": {
        "bash",
        "edit_file",
        "glob_files",
        "grep_files",
        "notebook_edit",
        "read_file",
        "run_code",
        "write_file",
        "workspace_files",
        "git_ops",
    },
    "apps": {
        "create_app",
        "describe_binding",
        "list_blueprints",
        "set_app_binding",
        "use_app",
    },
    "planning & reasoning": {
        "decision_matrix",
        "decompose_problem",
        "plan_task",
        "synthesize_evidence",
        "todo",
        "verify_output",
    },
    "interaction": {
        "ask_user",
        "ask_user_async",
        "connections",
        "give_up",
        "human_review",
    },
    "artifacts & content": {
        "build_artifact",
        "build_document",
        "build_prompt",
        "deep_research",
        "download_file",
        "pdf",
        "render_dashboard",
        "vision",
    },
    "data": {"sql"},
    "memory & discovery": {"memory", "tool_search"},
    "delegation": {"sub_agent"},
}


def _connection_lookup(connections: Iterable[Any]) -> dict[str, Any]:
    return {
        str(getattr(connection, "id", "") or ""): connection
        for connection in connections
        if getattr(connection, "id", None)
    }


def tool_family(tool: Tool) -> str:
    """Return a stable capability family for built-in and dynamic tools."""
    if getattr(tool, "credential_key", None):
        return "connectors"
    metadata = dict(getattr(tool, "metadata", {}) or {})
    if getattr(tool, "server_name", None) or metadata.get("server"):
        return "mcp"
    name = str(getattr(tool, "name", "") or "")
    for family, names in _TOOL_FAMILIES.items():
        if name in names:
            return family
    return "custom"


def describe_tool_capability(
    tool: Tool,
    *,
    connections: Iterable[Any] = (),
) -> dict[str, Any]:
    """Describe one tool in a form shared by prompts and tool discovery."""
    name = str(getattr(tool, "name", "") or "")
    metadata = dict(getattr(tool, "metadata", {}) or {})
    connection_id = str(getattr(tool, "credential_key", "") or "")
    server = str(getattr(tool, "server_name", "") or metadata.get("server") or "")
    connection = _connection_lookup(connections).get(connection_id or server)
    state = getattr(connection, "state", "") if connection is not None else ""
    if hasattr(state, "value"):
        state = state.value

    return {
        "name": name,
        "description": str(getattr(tool, "description", "") or ""),
        "prompt_instructions": str(getattr(tool, "prompt_instructions", "") or ""),
        "category": tool_family(tool),
        "read_only": contract_for(name, tool).read_only,
        "connection_id": connection_id,
        "connection_state": str(state or ""),
        "server": server,
    }


def build_tools_prompt(
    tools: list[Tool],
    *,
    connections: Iterable[Any] = (),
) -> str:
    if not tools:
        return ""

    capabilities = [
        describe_tool_capability(tool, connections=connections) for tool in tools
    ]
    grouped: dict[str, list[tuple[Tool, dict[str, Any]]]] = defaultdict(list)
    for tool, capability in zip(tools, capabilities, strict=True):
        grouped[capability["category"]].append((tool, capability))

    lines = [
        f"Available capabilities ({len(tools)} tools across {len(grouped)} families):",
        "Use tool_search when the best tool is unclear. Check connections before "
        "the first connector call; attached MCP tools are direct capabilities.",
    ]
    for family, entries in grouped.items():
        lines.append(f"\n{family.title()}:")
        for tool, capability in entries:
            tags = ["read-only" if capability["read_only"] else "action"]
            if capability["server"]:
                tags.append(f"mcp={capability['server']}")
            if capability["connection_id"]:
                connection = capability["connection_id"]
                state = capability["connection_state"] or "unknown"
                tags.append(f"connection={connection}:{state}")
            lines.append(
                f"- {tool.name}: {tool.description} " f"[capability: {', '.join(tags)}]"
            )
            prompt = getattr(tool, "prompt", "").strip()
            prompt_instructions = getattr(tool, "prompt_instructions", "").strip()
            if prompt:
                lines.append(f"  Guidance: {prompt}")
            elif prompt_instructions:
                lines.append(f"  Guidance: {prompt_instructions}")
    return "\n".join(lines)
