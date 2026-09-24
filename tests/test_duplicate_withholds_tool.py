"""A tool the model keeps repeating is withheld, not the whole toolset.

Seen live: a model called the same search with the same arguments fourteen
times, ignoring every "already ran" note, and never reached the tool that
would have finished the job. Switching straight to text-only stops the loop
but also takes away the tool the user actually asked for (building the
report), so the answer comes back as prose. The first all-repeat step now
withholds only the repeated tools; text-only is the fallback for a model that
repeats again after that.
"""

from __future__ import annotations

import asyncio
from typing import Any

from shipit_agent.agent import Agent
from shipit_agent.async_runtime import AsyncAgentRuntime
from shipit_agent.llms.base import LLMResponse, ToolCall
from shipit_agent.tools.base import ToolContext, ToolOutput


class _Tool:
    def __init__(self, name: str, *, read_only: bool = True, note: bool = False) -> None:
        self.name = name
        self.read_only = read_only
        self.note = note
        self.runs = 0

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.name,
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        }

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        self.runs += 1
        if self.note and self.runs > 1:
            # A wrapper that refuses its own repeats says so in metadata.
            return ToolOutput(text="[already called]", metadata={"duplicate_suppressed": True})
        return ToolOutput(text=f"{self.name} result")


class _Looping:
    """Repeats one call a fixed number of times, then calls `then` if offered."""

    def __init__(self, call: str, repeats: int, then: str = "") -> None:
        self.call, self.repeats, self.then = call, repeats, then
        self.offered: list[set[str]] = []

    def complete(self, *, messages, tools=None, **_kw) -> LLMResponse:
        names = {(t.get("function") or {}).get("name") for t in (tools or [])}
        self.offered.append(names)
        step = len(self.offered)
        if step <= self.repeats:
            return LLMResponse(tool_calls=[ToolCall(name=self.call, arguments={})])
        if self.then and self.then in names:
            return LLMResponse(tool_calls=[ToolCall(name=self.then, arguments={})])
        return LLMResponse(content="done")


def _run(llm, *tools):
    return Agent(llm=llm, tools=list(tools), auto_use_skills=False, max_iterations=8).run("go")


def test_a_repeated_tool_is_withheld_and_the_others_stay():
    search, build = _Tool("search"), _Tool("build")
    llm = _Looping("search", repeats=2, then="build")
    _run(llm, search, build)
    assert search.runs == 1
    assert "search" not in llm.offered[2]
    assert "build" in llm.offered[2]
    assert build.runs == 1


def test_repeating_after_the_tool_was_withheld_falls_back_to_text():
    search = _Tool("search")
    llm = _Looping("search", repeats=3)
    _run(llm, search)
    assert search.runs == 1
    assert llm.offered[3] == set()


def test_a_tool_that_refuses_its_own_repeat_is_withheld_too():
    search, build = _Tool("search", read_only=False, note=True), _Tool("build")
    llm = _Looping("search", repeats=2, then="build")
    _run(llm, search, build)
    assert "search" not in llm.offered[2]
    assert build.runs == 1


def test_a_first_call_is_never_withheld():
    search = _Tool("search")
    llm = _Looping("search", repeats=1)
    _run(llm, search)
    assert "search" in llm.offered[1]


def test_async_loop_withholds_the_repeated_tool():
    search, build = _Tool("search"), _Tool("build")
    llm = _Looping("search", repeats=2, then="build")
    runtime = AsyncAgentRuntime(llm=llm, prompt="p", tools=[search, build], max_iterations=8)
    asyncio.run(runtime.run("go"))
    assert "search" not in llm.offered[2]
    assert build.runs == 1
