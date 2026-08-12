"""Selection, indexing and loading rules for deferred tools.

Pure functions over registry tools and schema dicts — no runtime state,
no I/O. The runtime owns *when* these run; this module owns *what* they
decide, so both loops (sync and async) share one behaviour.
"""

from __future__ import annotations

from typing import Any, Iterable

# Shared-state keys visible to every tool through ``ToolContext.state``.
#: set[str] — names whose schemas are withheld until loaded.
DEFERRED_NAMES_KEY = "deferred_tool_names"
#: set[str] — names loaded this run (by tool_search or by being called).
LOADED_NAMES_KEY = "loaded_tool_names"
#: dict[str, dict] — full schema per tool name, for signature previews.
SCHEMAS_BY_NAME_KEY = "tool_schemas_by_name"

# The always-loaded core. Reuses code mode's split deliberately: the
# direct working set (files, shell, discovery, the human, the agent's own
# scaffolding) stays resident; connected resources (GitHub, Slack, SQL,
# MCP servers…) cost nothing until asked for.
from shipit_agent.codemode import CORE_TOOLS as DEFAULT_CORE_TOOLS  # noqa: E402


def _tool_name(tool: Any) -> str:
    return str(getattr(tool, "name", "") or "")


def _schema_name(schema: dict) -> str:
    return str(((schema.get("function") or {}).get("name")) or "")


def resolve_deferred_names(
    tools: Iterable[Any],
    config: Any,
    *,
    core: frozenset[str] = DEFAULT_CORE_TOOLS,
) -> set[str]:
    """Which registered tools should be deferred under *config*.

    ``config`` is the ``Agent.deferred_tools`` value: ``False``/``None``
    disables deferral; ``True`` defers everything outside *core*; an
    iterable of names defers exactly those (unknown names are ignored so a
    stale config cannot break a run). ``tool_search`` is never deferred —
    it is the loading mechanism itself.
    """
    names = {_tool_name(t) for t in tools} - {""}
    if not config:
        return set()
    if config is True:
        deferred = {n for n in names if n not in core}
    else:
        requested = {str(n) for n in config}
        deferred = names & requested
    deferred.discard("tool_search")
    return deferred


def deferred_index(tools: Iterable[Any], deferred: set[str]) -> str:
    """The system-prompt section listing deferred tools by name only.

    One name per tool, grouped by family — this is the whole prompt cost
    of a deferred integration, versus a full JSON schema on every step.
    """
    from shipit_agent.tools.helpers import tool_family

    if not deferred:
        return ""
    by_family: dict[str, list[str]] = {}
    for tool in tools:
        name = _tool_name(tool)
        if name in deferred:
            by_family.setdefault(tool_family(tool), []).append(name)
    lines = [
        "More tools exist beyond the ones defined above. They are listed "
        "here by name only; their full definitions are not loaded yet:",
        "",
    ]
    for family in sorted(by_family):
        names = ", ".join(sorted(by_family[family]))
        lines.append(f"- {family}: {names}")
    lines += [
        "",
        "To use one, call `tool_search` with what you are trying to do — "
        "matching tools are loaded and become directly callable on your "
        "next step. You may also call a listed tool directly by name if "
        "you already know it is the right one.",
    ]
    return "\n".join(lines)


def select_schemas(
    tool_schemas: list[dict],
    deferred: set[str] | None,
    loaded: set[str] | None,
) -> list[dict]:
    """The schemas one step advertises: core + anything loaded so far."""
    if not deferred:
        return list(tool_schemas)
    visible = loaded or set()
    return [
        schema
        for schema in tool_schemas
        if _schema_name(schema) not in deferred or _schema_name(schema) in visible
    ]


def signature_line(schema: dict | None) -> str:
    """A one-line callable signature from a wrapped function schema.

    ``send_message(channel: string, text: string, thread_ts?: string)`` —
    enough for the model to call the tool correctly on the very next step,
    without pasting the whole JSON schema into the transcript.
    """
    if not schema:
        return ""
    function = schema.get("function") or {}
    name = function.get("name") or "?"
    parameters = function.get("parameters") or {}
    properties = parameters.get("properties") or {}
    required = set(parameters.get("required") or [])
    parts = []
    for arg, spec in properties.items():
        arg_type = (spec or {}).get("type", "any")
        marker = "" if arg in required else "?"
        parts.append(f"{arg}{marker}: {arg_type}")
    return f"{name}({', '.join(parts)})"
