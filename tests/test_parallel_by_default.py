"""Read-only tool calls from one response run in parallel by default.

Writes and anything not known to be read-only keep running one at a time,
in order, because a later call may depend on an earlier one's effect.
Concurrency is measured by overlap, not by elapsed time, so the tests hold
on a loaded machine.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from shipit_agent import Agent
from shipit_agent.core.models import ToolCall
from shipit_agent.core.runtime import AgentRuntime
from shipit_agent.llms.base import LLMResponse
from shipit_agent.tools.base import ToolOutput


class _Overlap:
    """Counts how many tools are running at once."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.running = 0
        self.peak = 0
        self.order: list[str] = []

    def tool(self, name: str, *, read_only: bool) -> Any:
        overlap = self

        class _Tool:
            description = name
            prompt_instructions = ""

            def __init__(self) -> None:
                self.name = name
                self.read_only = read_only

            def schema(self) -> dict[str, Any]:
                return {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": name,
                        "parameters": {"type": "object", "properties": {}},
                    },
                }

            def run(self, context: Any, **_: Any) -> ToolOutput:
                with overlap.lock:
                    overlap.running += 1
                    overlap.peak = max(overlap.peak, overlap.running)
                    overlap.order.append(name)
                time.sleep(0.15)
                with overlap.lock:
                    overlap.running -= 1
                return ToolOutput(text=f"{name} done")

        return _Tool()


class _CallsAllThenAnswers:
    def __init__(self, names: list[str]) -> None:
        self.names = names
        self.turn = 0

    def complete(self, **_: Any) -> LLMResponse:
        self.turn += 1
        if self.turn == 1:
            return LLMResponse(
                content="",
                tool_calls=[ToolCall(name=n, arguments={}) for n in self.names],
            )
        return LLMResponse(content="done")


def test_read_only_calls_overlap_by_default() -> None:
    overlap = _Overlap()
    tools = [overlap.tool(n, read_only=True) for n in ("a", "b", "c")]
    agent = Agent(llm=_CallsAllThenAnswers(["a", "b", "c"]), tools=tools)

    result = agent.run("read")

    assert agent.parallel_tool_execution is True
    assert overlap.peak >= 2
    assert [r.name for r in result.tool_results] == ["a", "b", "c"]


def test_a_group_with_a_write_runs_in_order() -> None:
    overlap = _Overlap()
    tools = [
        overlap.tool("read_a", read_only=True),
        overlap.tool("write_b", read_only=False),
        overlap.tool("read_c", read_only=True),
    ]
    agent = Agent(
        llm=_CallsAllThenAnswers(["read_a", "write_b", "read_c"]), tools=tools
    )

    agent.run("mixed")

    assert overlap.peak == 1
    assert overlap.order == ["read_a", "write_b", "read_c"]


def test_the_runtime_default_matches_the_agent() -> None:
    runtime = AgentRuntime(llm=_CallsAllThenAnswers([]), prompt="p")
    assert runtime.parallel_tool_execution is True


def test_parallel_can_still_be_turned_off() -> None:
    overlap = _Overlap()
    tools = [overlap.tool(n, read_only=True) for n in ("a", "b")]
    agent = Agent(
        llm=_CallsAllThenAnswers(["a", "b"]), tools=tools, parallel_tool_execution=False
    )

    agent.run("read")

    assert overlap.peak == 1
