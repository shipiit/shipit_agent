"""Async callbacks run on the caller's event loop, and a failing one denies.

The usual async can_use_tool waits for an approval that another task on
the app's own loop delivers. Run on a private loop, that wait deadlocked
or raised, and a raising callback let the call through.
"""

from __future__ import annotations

import asyncio
from typing import Any

from shipit_agent import FunctionTool
from shipit_agent.core.models import ToolCall
from shipit_agent.llms.base import LLMResponse
from shipit_agent.sdk import (
    AgentOptions,
    HookMatcher,
    PermissionResultAllow,
    ResultMessage,
    UserMessage,
    create_sdk_mcp_server,
    query,
    tool,
)


class _CallsOnce:
    model = "claude-sonnet-5-5"

    def __init__(self, name: str, **arguments: Any) -> None:
        self.call: ToolCall | None = ToolCall(name=name, arguments=arguments, id="c1")

    def complete(self, **_: Any) -> LLMResponse:
        if self.call is not None:
            call, self.call = self.call, None
            return LLMResponse(content="", tool_calls=[call])
        return LLMResponse(content="done")


def _note(text: str = "") -> str:
    """Write a note."""
    return f"noted:{text}"


ASK = {"agent_options": {"permissions": {"ask": ["note_create"]}}}


async def _drain(options: AgentOptions) -> list[Any]:
    return [m async for m in query(prompt="go", options=options)]


def _first_block(messages: list[Any]) -> Any:
    return next(m for m in messages if isinstance(m, UserMessage)).content[0]


def test_can_use_tool_can_wait_for_an_approval_from_the_callers_loop() -> None:
    async def main() -> list[Any]:
        approved = asyncio.Event()

        async def can_use_tool(name: str, input_data: dict[str, Any], context: Any) -> Any:
            await approved.wait()  # bound to the caller's loop
            return PermissionResultAllow()

        async def click_approve() -> None:
            await asyncio.sleep(0.05)
            approved.set()

        clicker = asyncio.create_task(click_approve())
        options = AgentOptions(llm=_CallsOnce("note_create", text="x"),
                               tools=[FunctionTool.from_callable(_note, name="note_create")],
                               can_use_tool=can_use_tool, **ASK)
        messages = await asyncio.wait_for(_drain(options), timeout=10)
        await clicker
        return messages

    messages = asyncio.run(main())
    assert _first_block(messages).content == "noted:x"


def test_a_can_use_tool_that_raises_denies_the_call() -> None:
    async def can_use_tool(*_: Any) -> Any:
        raise RuntimeError("approval service is down")

    options = AgentOptions(llm=_CallsOnce("note_create", text="x"),
                           tools=[FunctionTool.from_callable(_note, name="note_create")],
                           can_use_tool=can_use_tool, permission_mode="bypassPermissions", **ASK)
    block = _first_block(asyncio.run(asyncio.wait_for(_drain(options), timeout=10)))
    assert block.is_error and "approval service is down" in block.content


def test_hooks_and_tools_can_await_the_callers_loop_too() -> None:
    async def main() -> list[Any]:
        ready = asyncio.Event()

        async def pre_tool(*_: Any) -> dict[str, Any]:
            await ready.wait()
            return {}

        @tool("ping", "Ping", {})
        async def ping(args: dict[str, Any]) -> dict[str, Any]:
            await ready.wait()
            return {"content": [{"type": "text", "text": "pong"}]}

        loop = asyncio.get_running_loop()
        loop.call_later(0.05, ready.set)
        options = AgentOptions(llm=_CallsOnce("util__ping"), tools=[],
                               mcp_servers={"util": create_sdk_mcp_server("util", tools=[ping])},
                               hooks={"PreToolUse": [HookMatcher(None, [pre_tool])]})
        return await asyncio.wait_for(_drain(options), timeout=10)

    messages = asyncio.run(main())
    assert _first_block(messages).content == "pong"
    assert isinstance(messages[-1], ResultMessage) and messages[-1].subtype == "success"
