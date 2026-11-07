"""The Claude Agent SDK hook events shipit lacked: PostToolUseFailure,
PermissionRequest and Notification.
"""

from __future__ import annotations

from typing import Any

from shipit_agent import Agent, FunctionTool
from shipit_agent.core.models import ToolCall
from shipit_agent.llms.base import LLMResponse
from shipit_agent.safety.hooks import AgentHooks
from shipit_agent.safety.permissions import PermissionDecision, PermissionResult


class _CallsOnce:
    def __init__(self, name: str, **arguments: Any) -> None:
        self.call = ToolCall(name=name, arguments=arguments)
        self.tool_messages: list[str] = []

    def complete(self, *, messages: Any, **_: Any) -> LLMResponse:
        self.tool_messages = [str(m.content) for m in messages if m.role == "tool"]
        if self.call is not None:
            call, self.call = self.call, None
            return LLMResponse(content="", tool_calls=[call])
        return LLMResponse(content="done")


def _note(text: str = "") -> str:
    """Write a note."""
    return f"noted:{text}"


def _broken(text: str = "") -> str:
    """Always fails."""
    raise ValueError("disk full")


NOTE = FunctionTool.from_callable(_note, name="note_create")
BROKEN = FunctionTool.from_callable(_broken, name="broken")


def _run(llm: _CallsOnce, hooks: AgentHooks, **options: Any) -> Any:
    return Agent(llm=llm, tools=[NOTE, BROKEN], hooks=hooks, **options).run("go")


# -- post_tool_failure --------------------------------------------------------


def test_a_failure_hook_sees_the_failed_call() -> None:
    seen: list[tuple[str, dict[str, Any], str]] = []
    hooks = AgentHooks()
    hooks.on_post_tool_failure(lambda name, arguments, error: seen.append((name, arguments, error)))
    _run(_CallsOnce("broken", text="x"), hooks)
    assert len(seen) == 1
    name, arguments, error = seen[0]
    assert (name, arguments) == ("broken", {"text": "x"})
    assert "disk full" in error


def test_a_failure_hook_can_add_context_for_the_model() -> None:
    hooks = AgentHooks()
    hooks.on_post_tool_failure(lambda *_: "Free space with `make clean`, then retry.")
    llm = _CallsOnce("broken")
    _run(llm, hooks)
    assert "make clean" in llm.tool_messages[0]
    assert "disk full" in llm.tool_messages[0]


def test_a_failure_hook_does_not_run_for_a_success() -> None:
    seen: list[str] = []
    hooks = AgentHooks()
    hooks.on_post_tool_failure(lambda name, *_: seen.append(name))
    _run(_CallsOnce("note_create", text="x"), hooks)
    assert seen == []


# -- permission_request ---------------------------------------------------------


ASKS = {"permissions": {"ask": ["note_create"]}}


def test_without_a_request_hook_an_asked_call_does_not_run() -> None:
    result = _run(_CallsOnce("note_create", text="x"), AgentHooks(), **ASKS)
    assert not any(str(r.output).startswith("noted:") for r in result.tool_results)


def test_a_request_hook_can_allow_the_call() -> None:
    seen: list[tuple[str, str]] = []
    hooks = AgentHooks()

    @hooks.on_permission_request
    def approve(name: str, arguments: dict[str, Any], reason: str) -> dict[str, str]:
        seen.append((name, reason))
        return {"decision": "allow"}

    result = _run(_CallsOnce("note_create", text="x"), hooks, **ASKS)
    assert "noted:x" in [str(r.output) for r in result.tool_results]
    assert seen[0][0] == "note_create" and "approval" in seen[0][1]


def test_a_request_hook_can_allow_with_rewritten_arguments() -> None:
    hooks = AgentHooks()
    hooks.on_permission_request(
        lambda *_: PermissionResult(PermissionDecision.ALLOW, updated_arguments={"text": "safe"})
    )
    result = _run(_CallsOnce("note_create", text="x"), hooks, **ASKS)
    assert "noted:safe" in [str(r.output) for r in result.tool_results]


def test_a_request_hook_can_deny_the_call() -> None:
    hooks = AgentHooks()
    hooks.on_permission_request(lambda *_: {"decision": "deny", "reason": "not today"})
    llm = _CallsOnce("note_create", text="x")
    result = _run(llm, hooks, **ASKS)
    assert not any(str(r.output).startswith("noted:") for r in result.tool_results)
    assert "not today" in llm.tool_messages[0]


def test_a_request_hook_is_not_asked_about_calls_that_need_no_approval() -> None:
    seen: list[str] = []
    hooks = AgentHooks()
    hooks.on_permission_request(lambda name, *_: seen.append(name))
    _run(_CallsOnce("note_create", text="x"), hooks)
    assert seen == []


# -- notification -----------------------------------------------------------------


def test_a_call_left_waiting_for_approval_notifies() -> None:
    notes: list[tuple[str, str]] = []
    hooks = AgentHooks()
    hooks.on_notification(lambda message, kind: notes.append((message, kind)))
    _run(_CallsOnce("note_create", text="x"), hooks, **ASKS)
    assert len(notes) == 1
    message, kind = notes[0]
    assert kind == "permission_prompt"
    assert "note_create" in message


def test_a_call_a_request_hook_settles_does_not_notify() -> None:
    notes: list[str] = []
    hooks = AgentHooks()
    hooks.on_permission_request(lambda *_: {"decision": "allow"})
    hooks.on_notification(lambda message, kind: notes.append(kind))
    _run(_CallsOnce("note_create", text="x"), hooks, **ASKS)
    assert notes == []


# -- post_tool_use ------------------------------------------------------------------


def test_a_post_tool_use_hook_sees_the_calls_arguments_and_result() -> None:
    seen: list[tuple[str, dict[str, Any], str]] = []
    hooks = AgentHooks()
    hooks.on_post_tool_use(lambda name, arguments, result: seen.append((name, arguments, result.output)))
    _run(_CallsOnce("note_create", text="x"), hooks)
    assert seen == [("note_create", {"text": "x"}, "noted:x")]


def test_a_post_tool_use_hook_can_replace_or_add_to_the_output() -> None:
    hooks = AgentHooks()
    hooks.on_post_tool_use(lambda *_: {"updated_output": "replaced"})
    hooks.on_post_tool_use(lambda *_: "and a note")
    llm = _CallsOnce("note_create", text="x")
    result = _run(llm, hooks)
    assert result.tool_results[0].output == "replaced\n\nand a note"
