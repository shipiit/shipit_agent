"""
13 — Parallel tool execution with isolated per-tool state.

When the model requests several independent tools in one turn, SHIPIT can run
them concurrently (``parallel_tool_execution=True``). Each tool gets its own
isolated copy of the shared state, and the results are merged back in the
original order — so two tools that both append to ``context.state`` can't
corrupt each other.

This script uses a small scripted LLM so it runs offline with no API keys.

Run:
    python examples/13_parallel_tools.py
"""

from __future__ import annotations

import time

from shipit_agent import Agent, FunctionTool
from shipit_agent.llms.base import LLMResponse
from shipit_agent.models import ToolCall


class _ScriptedLLM:
    """Requests three tools at once on the first turn, then summarises."""

    def __init__(self) -> None:
        self._done = False

    def complete(self, *, messages, tools=None, system_prompt=None, metadata=None):
        if not self._done:
            self._done = True
            return LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(name="weather", arguments={"city": "Tokyo"}),
                    ToolCall(name="weather", arguments={"city": "Paris"}),
                    ToolCall(name="weather", arguments={"city": "Cairo"}),
                ],
            )
        return LLMResponse(content="Fetched weather for all three cities.")


def _slow_weather(context, city: str, **_ignored) -> str:
    # Simulate a 0.3s network call; concurrently these finish in ~0.3s total
    # instead of ~0.9s sequentially.
    time.sleep(0.3)
    context.state.setdefault("cities_seen", []).append(city)
    return f"{city}: 22C, clear"


def main() -> None:
    weather = FunctionTool.from_callable(_slow_weather, name="weather")

    agent = Agent(
        llm=_ScriptedLLM(),
        tools=[weather],
        parallel_tool_execution=True,
        max_iterations=3,
        auto_use_skills=False,
    )

    started = time.monotonic()
    result = agent.run("What's the weather in Tokyo, Paris and Cairo?")
    elapsed = time.monotonic() - started

    print("─" * 60)
    print("  Parallel tool execution demo")
    print("─" * 60)
    for item in result.tool_results:
        print(f"  • {item.output}")
    print(f"\n  3 × 0.3s tools finished in {elapsed:.2f}s (concurrent)")
    print(f"  Final answer: {result.output}")


if __name__ == "__main__":
    main()
