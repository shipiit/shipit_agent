"""SDK agents ask before running a tool no rule covers, as the Claude Agent SDK does."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from shipit_agent import FunctionTool
from shipit_agent.core.models import ToolCall
from shipit_agent.llms.base import LLMResponse
from shipit_agent.safety.permissions import PermissionDecision, PermissionEngine
from shipit_agent.sdk import AgentOptions, PermissionResultAllow, UserMessage, build_agent, query

RAN: list[str] = []


def _note(text: str = "") -> str:
    """Write a note."""
    RAN.append(text)
    return f"noted:{text}"


NOTE = FunctionTool.from_callable(_note, name="note_create")


class _Once:
    model = "claude-sonnet-5-5"

    def __init__(self, name: str, arguments: dict[str, Any]) -> None:
        self.call: tuple[str, dict[str, Any]] | None = (name, arguments)

    def complete(self, **_: Any) -> LLMResponse:
        if self.call is not None:
            name, arguments = self.call
            self.call = None
            return LLMResponse(content="", tool_calls=[ToolCall(name=name, arguments=arguments, id="c1")])
        return LLMResponse(content="done")


def _run(call: tuple[str, dict[str, Any]], **options: Any) -> str:
    RAN.clear()
    options.setdefault("tools", [NOTE])

    async def go() -> list[Any]:
        return [m async for m in query(prompt="go", options=AgentOptions(llm=_Once(*call), **options))]

    messages = asyncio.run(go())
    return str(next(m for m in messages if isinstance(m, UserMessage)).content[0])


def test_an_unlisted_tool_is_not_run_without_approval() -> None:
    result = _run(("note_create", {"text": "x"}))
    assert RAN == []
    assert "approval" in result.lower()


def test_can_use_tool_approves_it() -> None:
    async def yes(name: str, arguments: dict[str, Any], context: Any) -> PermissionResultAllow:
        return PermissionResultAllow()

    _run(("note_create", {"text": "x"}), can_use_tool=yes)
    assert RAN == ["x"]


@pytest.mark.parametrize(
    "options",
    [{"allowed_tools": ["note_create"]}, {"permission_mode": "bypassPermissions"}],
)
def test_pre_approval_still_runs_it(options: dict[str, Any]) -> None:
    _run(("note_create", {"text": "x"}), **options)
    assert RAN == ["x"]


@pytest.mark.parametrize("mode", ["default", "acceptEdits", "dontAsk"])
def test_read_only_tools_run_without_asking(tmp_path: Path, mode: str) -> None:
    (tmp_path / "a.txt").write_text("hello")
    agent = build_agent(AgentOptions(llm=_Once("x", {}), cwd=tmp_path, permission_mode=mode))
    engine = agent.permissions
    assert isinstance(engine, PermissionEngine)
    assert engine.check("read_file", {"path": "a.txt"}).decision == PermissionDecision.ALLOW
    assert engine.check("note_create", {}).decision != PermissionDecision.ALLOW


def test_accept_edits_still_approves_edits(tmp_path: Path) -> None:
    engine = build_agent(AgentOptions(llm=_Once("x", {}), cwd=tmp_path, permission_mode="acceptEdits")).permissions
    assert engine.check("write_file", {"path": "a.txt", "content": ""}).decision == PermissionDecision.ALLOW
    assert engine.check("bash", {"command": "ls"}).decision != PermissionDecision.ALLOW


def test_a_caller_supplied_engine_is_kept(tmp_path: Path) -> None:
    mine = PermissionEngine()
    agent = build_agent(AgentOptions(llm=_Once("x", {}), cwd=tmp_path, agent_options={"permissions": mine}))
    assert agent.permissions is mine


def test_an_unknown_mode_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="permission_mode"):
        build_agent(AgentOptions(llm=_Once("x", {}), cwd=tmp_path, permission_mode="yolo"))


def _pre_allow(*_: Any) -> dict[str, Any]:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}}


def test_a_pre_tool_use_allow_approves_an_unlisted_tool() -> None:
    from shipit_agent.sdk import HookMatcher

    _run(("note_create", {"text": "x"}), hooks={"PreToolUse": [HookMatcher(None, [_pre_allow])]})
    assert RAN == ["x"]


def test_a_hook_allow_does_not_beat_a_deny_or_ask_rule() -> None:
    assert PermissionEngine(deny=["note_create"]).check("note_create", {}, pre_approved=True).denied
    engine = PermissionEngine(ask=["note_create"])
    assert engine.check("note_create", {}, pre_approved=True).needs_approval
    assert PermissionEngine(default_decision=PermissionDecision.ASK).check("x", {}, pre_approved=True).allowed
