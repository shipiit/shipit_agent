"""The tools an agent always has, like Claude Code's: the rest load on demand.

With many tools registered, a small fixed core stays resident: read, write
and edit files, search them, run commands, search and fetch the web, keep a
todo list, ask the user, and find the other tools. Which tools are core is
an explicit, ordered choice, not an accident of registration order.
"""

from __future__ import annotations

from shipit_agent.agent_setup.builtins import get_builtin_tools
from shipit_agent.deferral.core import RESIDENT_LIMIT, resolve_deferred_names

CLAUDE_CODE_CORE = {
    "read_file",
    "write_file",
    "edit_file",
    "glob_files",
    "grep_files",
    "bash",
    "web_search",
    "open_url",
    "todo",
    "ask_user",
}


def _resident(tools):
    deferred = resolve_deferred_names(tools, "auto")
    return {t.name for t in tools if t.name not in deferred}


def test_the_builtin_agent_keeps_the_claude_code_core_resident() -> None:
    resident = _resident(get_builtin_tools(project_root="/tmp"))
    assert CLAUDE_CODE_CORE <= resident
    assert "tool_search" in resident


def test_the_resident_set_stays_small() -> None:
    resident = _resident(get_builtin_tools(project_root="/tmp"))
    assert len(resident - {"tool_search"}) <= RESIDENT_LIMIT


def test_registration_order_does_not_change_the_core() -> None:
    tools = get_builtin_tools(project_root="/tmp")
    assert _resident(tools) == _resident(list(reversed(tools)))


def test_a_tool_can_ask_to_stay_resident() -> None:
    tools = get_builtin_tools(project_root="/tmp")
    jira = next(t for t in tools if t.name == "jira")
    jira.discovery_priority = 10
    try:
        assert "jira" in _resident(tools)
    finally:
        del jira.discovery_priority
