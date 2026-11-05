"""SDK-style hooks (``HookMatcher``) and ``can_use_tool`` on shipit's loop."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from shipit_agent import FunctionTool
from shipit_agent.core.models import ToolCall
from shipit_agent.llms.base import LLMResponse
from shipit_agent.sdk import (
    AgentOptions,
    HookMatcher,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    UserMessage,
    build_agent,
    query,
)


class _Calls:
    model = "claude-sonnet-5-5"

    def __init__(self, *calls: tuple[str, dict[str, Any]]) -> None:
        self.calls = list(calls)
        self.prompts: list[str] = []
        self.answers = 0

    def complete(self, *, messages: Any, **_: Any) -> LLMResponse:
        self.prompts.append(str(next(m.content for m in reversed(messages) if m.role == "user")))
        if self.calls:
            name, arguments = self.calls.pop(0)
            return LLMResponse(content="", tool_calls=[ToolCall(name=name, arguments=arguments, id="c1")])
        self.answers += 1
        return LLMResponse(content=f"answer {self.answers}")


def _note(text: str = "") -> str:
    """Write a note."""
    return f"noted:{text}"


NOTE = FunctionTool.from_callable(_note, name="note_create")


def _run(llm: _Calls, **options: Any) -> list[Any]:
    options.setdefault("tools", [NOTE])

    async def run() -> list[Any]:
        return [m async for m in query(prompt="go", options=AgentOptions(llm=llm, **options))]

    return asyncio.run(run())


def _first_result(messages: list[Any]) -> Any:
    return next(m for m in messages if isinstance(m, UserMessage)).content[0]


def _pre(decision: str, **extra: Any) -> dict[str, Any]:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision, **extra}}


# -- hooks ------------------------------------------------------------------------


def test_a_pre_tool_use_hook_sees_sdk_shaped_input_and_can_deny() -> None:
    seen: list[dict[str, Any]] = []

    async def guard(input_data: dict[str, Any], tool_use_id: Any, context: Any) -> dict[str, Any]:
        seen.append(input_data)
        return _pre("deny", permissionDecisionReason="notes are read-only today")

    messages = _run(_Calls(("note_create", {"text": "x"})), hooks={"PreToolUse": [HookMatcher("note_create", [guard])]})
    block = _first_result(messages)
    assert block.is_error and "read-only today" in block.content
    data = seen[0]
    assert (data["hook_event_name"], data["tool_name"], data["tool_input"]) == ("PreToolUse", "note_create", {"text": "x"})
    assert {"session_id", "cwd", "permission_mode", "transcript_path"} <= set(data)


def test_a_pre_tool_use_hook_can_rewrite_the_input() -> None:
    hook = HookMatcher(None, [lambda *_: _pre("allow", updatedInput={"text": "safe"})])
    block = _first_result(_run(_Calls(("note_create", {"text": "x"})), hooks={"PreToolUse": [hook]}))
    assert block.content == "noted:safe"


def test_a_matcher_skips_other_tools() -> None:
    calls: list[str] = []
    hook = HookMatcher("Bash|Write", [lambda data, *_: calls.append(data["tool_name"]) or {}])
    _run(_Calls(("note_create", {"text": "x"})), hooks={"PreToolUse": [hook]})
    assert calls == []


def test_a_matcher_takes_sdk_tool_names() -> None:
    calls: list[str] = []
    hook = HookMatcher("Bash", [lambda data, *_: calls.append(data["tool_name"]) or {}])
    _run(_Calls(("bash", {"command": "echo hi"})), tools=[_FakeBash()], hooks={"PreToolUse": [hook]})
    assert calls == ["bash"]


def test_post_tool_use_can_add_context_and_replace_output() -> None:
    def post(data: dict[str, Any], tool_use_id: Any, context: Any) -> dict[str, Any]:
        assert data["tool_response"] == "noted:x" and data["tool_input"] == {"text": "x"}
        return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": "clean",
                                       "additionalContext": "Saved to the shared board."}}

    block = _first_result(_run(_Calls(("note_create", {"text": "x"})), hooks={"PostToolUse": [HookMatcher(None, [post])]}))
    assert block.content == "clean\n\nSaved to the shared board."


def test_user_prompt_submit_can_add_context_or_block() -> None:
    added = HookMatcher(None, [lambda *_: {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                                                  "additionalContext": "Today is Friday."}}])
    llm = _Calls()
    _run(llm, hooks={"UserPromptSubmit": [added]})
    assert "Today is Friday." in llm.prompts[0]

    blocked = HookMatcher(None, [lambda *_: {"decision": "block", "reason": "outside office hours"}])
    llm = _Calls()
    result = _run(llm, hooks={"UserPromptSubmit": [blocked]})[-1]
    assert llm.prompts == []
    assert "outside office hours" in (result.result or "")


def test_a_stop_hook_can_keep_the_agent_going() -> None:
    answers: list[int] = []

    def stop(*_: Any) -> dict[str, Any]:
        answers.append(1)
        return {"decision": "block", "reason": "Run the tests first."} if len(answers) == 1 else {}

    llm = _Calls()
    result = _run(llm, hooks={"Stop": [HookMatcher(None, [stop])]})[-1]
    assert llm.answers == 2 and result.result == "answer 2"


def test_a_hook_that_times_out_blocks_only_when_set_to() -> None:
    def slow(*_: Any) -> dict[str, Any]:
        time.sleep(2)
        return {}

    _run(_Calls())  # warm imports, so the timings below measure the hook alone
    started = time.monotonic()
    blocking = HookMatcher(None, [slow], timeout=0.05, on_failure="block")
    assert _first_result(_run(_Calls(("note_create", {"text": "x"})), hooks={"PreToolUse": [blocking]})).is_error
    # The timeout bounds the wait: the run does not sit out the 2 s callback.
    assert time.monotonic() - started < 1.5
    started = time.monotonic()
    lenient = HookMatcher(None, [slow], timeout=0.05)
    assert _first_result(_run(_Calls(("note_create", {"text": "x"})), hooks={"PreToolUse": [lenient]})).content == "noted:x"
    assert time.monotonic() - started < 1.5


def test_an_unknown_hook_event_is_refused() -> None:
    with pytest.raises(ValueError, match="BeforeEverything"):
        build_agent(AgentOptions(llm=_Calls(), tools=[], hooks={"BeforeEverything": [HookMatcher()]}))


# -- can_use_tool -----------------------------------------------------------------


ASK = {"agent_options": {"permissions": {"ask": ["note_create"]}}}


def test_can_use_tool_is_asked_about_calls_that_need_approval() -> None:
    seen: list[tuple[str, dict[str, Any]]] = []

    async def can_use_tool(name: str, input_data: dict[str, Any], context: Any) -> Any:
        seen.append((name, input_data))
        return PermissionResultAllow()

    block = _first_result(_run(_Calls(("note_create", {"text": "x"})), can_use_tool=can_use_tool, **ASK))
    assert seen == [("note_create", {"text": "x"})] and block.content == "noted:x"


def test_can_use_tool_can_deny_or_rewrite() -> None:
    def deny(*_: Any) -> Any:
        return PermissionResultDeny(message="Not in production.")

    block = _first_result(_run(_Calls(("note_create", {"text": "x"})), can_use_tool=deny, **ASK))
    assert block.is_error and "Not in production." in block.content

    def rewrite(name: str, input_data: dict[str, Any], context: Any) -> Any:
        return PermissionResultAllow(updated_input={"text": "redacted"})

    block = _first_result(_run(_Calls(("note_create", {"text": "x"})), can_use_tool=rewrite, **ASK))
    assert block.content == "noted:redacted"


def test_can_use_tool_accepts_the_dict_form() -> None:
    block = _first_result(_run(_Calls(("note_create", {"text": "x"})),
                               can_use_tool=lambda *_: {"behavior": "deny", "message": "no"}, **ASK))
    assert block.is_error


def test_an_add_rules_update_approves_the_call_for_the_session() -> None:
    asked: list[str] = []

    def allow_always(name: str, *_: Any) -> Any:
        asked.append(name)
        return PermissionResultAllow(updated_permissions=[{"type": "addRules", "behavior": "allow"}])

    llm = _Calls(("note_create", {"text": "x"}), ("note_create", {"text": "x"}))
    messages = _run(llm, can_use_tool=allow_always, **ASK)
    assert asked == ["note_create"]
    assert isinstance(messages[-1], ResultMessage) and messages[-1].permission_denials == []


class _FakeBash:
    """A bash-named tool that never touches a shell."""

    name = "bash"
    description = "Run a command."
    prompt_instructions = ""

    def schema(self) -> dict[str, Any]:
        return {"type": "function", "function": {"name": "bash", "description": "Run a command.",
                "parameters": {"type": "object", "properties": {"command": {"type": "string"}}}}}

    def run(self, context: Any, **_: Any) -> Any:
        from shipit_agent.tools.base import ToolOutput

        return ToolOutput(text="ran")
