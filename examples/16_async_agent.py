"""
16 — Async agent runtime (FastAPI / asyncio friendly).

``AsyncAgentRuntime`` mirrors the synchronous runtime but is awaitable, so you
can drive agents from async web frameworks without blocking the event loop.
It streams events via ``async for`` and guarantees MCP cleanup even on error.

Run:
    python examples/16_async_agent.py
"""

from __future__ import annotations

import asyncio

from shipit_agent import AsyncAgentRuntime, FunctionTool
from shipit_agent.llms.base import LLMResponse
from shipit_agent.models import ToolCall


class _ScriptedLLM:
    def __init__(self) -> None:
        self._done = False

    def complete(self, *, messages, tools=None, system_prompt=None, metadata=None):
        if not self._done:
            self._done = True
            return LLMResponse(
                content="",
                tool_calls=[ToolCall(name="uppercase", arguments={"text": "hello"})],
            )
        return LLMResponse(content="Done: HELLO")


async def main() -> None:
    upper = FunctionTool.from_callable(
        lambda text, **_: text.upper(), name="uppercase"
    )
    runtime = AsyncAgentRuntime(
        llm=_ScriptedLLM(),
        prompt="You are a helpful async agent.",
        tools=[upper],
        max_iterations=3,
    )

    print("─" * 60)
    print("  Async streaming run")
    print("─" * 60)
    async for event in runtime.stream("Uppercase the word hello"):
        if event.type in {"tool_called", "tool_completed", "run_completed"}:
            print(f"  [{event.type}] {event.message}")


if __name__ == "__main__":
    asyncio.run(main())
