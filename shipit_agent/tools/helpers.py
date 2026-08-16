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
        "multi_edit",
        "bash_job",
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
        "present_plan",
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
        "image_generate",
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


#: How to use tools, stated *inside* the tool section rather than in the
#: base prompt.
#:
#: Placement is not cosmetic. The same instruction is followed far more
#: reliably when it sits next to the tools it governs than when it sits a few
#: paragraphs earlier under a general heading — an effect large enough that a
#: rule can be near-universally obeyed in one position and routinely ignored
#: in the other. These rules previously lived in the base agent prompt, and
#: the depth rule in particular was being ignored: given fifteen search hits
#: and a request for detail, the model opened one and answered from it.
#:
#: The section is emitted only when tools are actually attached, so a model
#: with no tools is never told how to call them.
TOOL_SECTION_HEADER = """
# Tools

How to use them:
- Read tool descriptions and guidance carefully before calling them.
- Use the smallest correct tool for the job.
- Call several tools in ONE response when they do not depend on each other.
  Reading three files, or searching two sources, is one turn with three
  calls — not three turns. Every turn re-sends the whole conversation, so
  splitting independent work across turns costs the user real money and
  time for nothing.
- Call them one at a time only when a call needs the previous result.
- **A search is the beginning of the work, not the end of it.** When a search
  returns several relevant items and the question asked for detail, depth or
  "more", open the most relevant ones — several in ONE response, not one and
  then a conclusion. One item out of fifteen is a sample, and an answer
  written from it is a guess presented as a finding.
- Before you answer, ask whether you looked at enough to be right. If the
  answer rests on one result out of many, say so plainly or go back and read
  the others. Confident summaries from partial evidence are the failure mode
  that matters most here.
- **Ask for what you need, not for everything.** Always pass the query, filter
  or range the question calls for. A call with no arguments asks a tool for
  its entire contents — it is slow, it costs the user, and an answer written
  from it is about everything rather than about the question.
- Never repeat a call you have already made with the same arguments. Its
  result is already in this conversation — read it again rather than
  fetching it again. If a result was not what you wanted, change the
  arguments; calling again unchanged returns the same thing.
- Say what you are about to do, in one short sentence, in the SAME response as
  the tool call. This is a public progress update, not private chain-of-thought.
  Never stop after merely announcing a tool: call it in that response.
- If you need more information or another tool part-way through, call it —
  stopping early with a partial answer is worse than taking another turn.
- When information may be outdated, prefer web and external tools over stale
  assumptions.
- When a task needs files, artifacts, or code execution, use the relevant
  tools instead of simulating output.
""".strip()


#: The boilerplate MCP tool guidance. With 100 MCP tools attached, printing
#: it per tool is 100 copies of the same sentence in every request — exactly
#: the duplication this prompt already eliminates for descriptions. Tools
#: whose server (or author) wrote REAL guidance still get their line.
_GENERIC_MCP_GUIDANCE = frozenset(
    {
        "Use this MCP tool when the remote capability is the right fit for the task.",
        "Use this MCP tool when the remote server provides the best capability for the task.",
        "Use this when the attached MCP server exposes the capability you need.",
    }
)


def build_tools_prompt(
    tools: list[Tool],
    *,
    connections: Iterable[Any] = (),
    mcps: Iterable[Any] = (),
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
        TOOL_SECTION_HEADER,
        "",
        f"Available capabilities ({len(tools)} tools across {len(grouped)} families):",
        "Use tool_search when the best tool is unclear. Check connections before "
        "the first connector call; attached MCP tools are direct capabilities.",
    ]
    for family, entries in grouped.items():
        lines.append(f"\n## {family.title()}")
        for tool, capability in entries:
            tags = ["read-only" if capability["read_only"] else "action"]
            if capability["server"]:
                tags.append(f"mcp={capability['server']}")
            if capability["connection_id"]:
                connection = capability["connection_id"]
                state = capability["connection_state"] or "unknown"
                tags.append(f"connection={connection}:{state}")
            # The description is deliberately NOT repeated here. Every tool's
            # description is already in the JSON schema the provider requires,
            # and that copy is the one the model selects on. Printing it again
            # bought nothing and cost real money: measured on a 43-tool agent,
            # 15,286 characters — about 3,800 tokens — re-sent on every step
            # of every turn, for a second copy of text already in the request.
            #
            # What stays is what the schema has no room for: which family the
            # tool belongs to, whether it only reads, and where it comes from.
            lines.append(f"- {tool.name} [{', '.join(tags)}]")
            prompt = getattr(tool, "prompt", "").strip()
            prompt_instructions = getattr(tool, "prompt_instructions", "").strip()
            if prompt and prompt not in _GENERIC_MCP_GUIDANCE:
                lines.append(f"  Guidance: {prompt}")
            elif (
                prompt_instructions
                and prompt_instructions not in _GENERIC_MCP_GUIDANCE
            ):
                lines.append(f"  Guidance: {prompt_instructions}")

    # One block per MCP server that sent `instructions` in its handshake —
    # the server author's own usage guidance, said once, instead of a
    # boilerplate line repeated under every one of its tools.
    for mcp in mcps or ():
        instructions = str(getattr(mcp, "instructions", "") or "").strip()
        if instructions:
            name = getattr(mcp, "name", "mcp")
            lines.append(f"\n## MCP server: {name}")
            lines.append(instructions)
    return "\n".join(lines)
