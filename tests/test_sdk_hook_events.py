"""``include_hook_events``: each hook callback's start and result in the message stream."""

from __future__ import annotations

import asyncio
from typing import Any

from shipit_agent import FunctionTool
from shipit_agent.core.models import ToolCall
from shipit_agent.llms.base import LLMResponse
from shipit_agent.sdk import (
    AgentClient,
    AgentOptions,
    HookMatcher,
    ResultMessage,
    SystemMessage,
    ToolResultBlock,
    UserMessage,
    query,
)


def _echo(text: str = "") -> str:
    """Echo the text."""
    return text


class _Model:
    model = "claude-sonnet-5-5"

    def __init__(self) -> None:
        self.turn = 0

    def complete(self, **_: Any) -> LLMResponse:
        self.turn += 1
        if self.turn == 1:
            return LLMResponse(content="", tool_calls=[ToolCall(name="echo", arguments={"text": "x"}, id="c1")])
        return LLMResponse(content="done")


def audit(payload: dict[str, Any], tool_use_id: Any, context: Any) -> dict[str, Any]:
    return {"systemMessage": f"saw {payload['tool_name']}"}


def broken(payload: dict[str, Any], tool_use_id: Any, context: Any) -> dict[str, Any]:
    raise RuntimeError("hook crashed")


def _options(**extra: Any) -> AgentOptions:
    return AgentOptions(
        llm=_Model(), tools=[FunctionTool.from_callable(_echo, name="echo")], allowed_tools=["echo"],
        hooks={"PreToolUse": [HookMatcher(matcher="echo", hooks=[audit, broken])]}, **extra,
    )


def _hook_messages(messages: list[Any]) -> list[SystemMessage]:
    return [m for m in messages if isinstance(m, SystemMessage) and m.subtype.startswith("hook_")]


def _check(messages: list[Any]) -> None:
    hooks = _hook_messages(messages)
    assert [(m.subtype, m.data["hook_name"]) for m in hooks] == [
        ("hook_started", "audit"), ("hook_response", "audit"),
        ("hook_started", "broken"), ("hook_response", "broken"),
    ]
    started, done = hooks[0].data, hooks[1].data
    assert started["hook_event"] == "PreToolUse" and started["hook_id"] == done["hook_id"] and started["uuid"]
    assert done["outcome"] == "success" and "saw echo" in done["output"]
    assert hooks[3].data["outcome"] == "error" and "hook crashed" in hooks[3].data["stderr"]
    # Each hook message comes before the result of the call it ran for, and before the end.
    positions = [i for i, m in enumerate(messages) if m in hooks]
    tool_result = next(
        i for i, m in enumerate(messages)
        if isinstance(m, UserMessage) and isinstance(m.content, list) and isinstance(m.content[0], ToolResultBlock)
    )
    assert max(positions) < tool_result
    assert isinstance(messages[-1], ResultMessage) and messages[-1].subtype == "success"


def test_hook_events_stream_through_query() -> None:
    async def go() -> list[Any]:
        return [m async for m in query(prompt="go", options=_options(include_hook_events=True))]

    _check(asyncio.run(go()))


def test_hook_events_stream_through_the_client() -> None:
    async def go() -> list[Any]:
        async with AgentClient(_options(include_hook_events=True)) as client:
            await client.query("go")
            return [m async for m in client.receive_response()]

    _check(asyncio.run(go()))


def test_without_the_option_no_hook_messages_appear_but_hooks_still_run() -> None:
    async def go() -> list[Any]:
        return [m async for m in query(prompt="go", options=_options())]

    messages = asyncio.run(go())
    assert _hook_messages(messages) == []
    assert isinstance(messages[-1], ResultMessage) and messages[-1].subtype == "success"


def test_a_stop_hook_is_reported_before_the_result() -> None:
    def stopped(payload: dict[str, Any], tool_use_id: Any, context: Any) -> dict[str, Any]:
        return {}

    options = AgentOptions(llm=_Model(), tools=[FunctionTool.from_callable(_echo, name="echo")], allowed_tools=["echo"],
                           hooks={"Stop": [HookMatcher(hooks=[stopped])]}, include_hook_events=True)

    async def go() -> list[Any]:
        return [m async for m in query(prompt="go", options=options)]

    messages = asyncio.run(go())
    hooks = _hook_messages(messages)
    assert [m.data["hook_event"] for m in hooks] == ["Stop", "Stop"]
    assert messages.index(hooks[-1]) < len(messages) - 1 and isinstance(messages[-1], ResultMessage)
