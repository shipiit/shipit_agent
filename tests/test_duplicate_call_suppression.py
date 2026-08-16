"""Duplicate-call suppression — the dithering fix.

A weak model re-issues a read it already ran, burning a step and tokens on a
result it already has (one benchmark: 10 tool calls where 3 sufficed). The
runtime now skips an exact repeat of a READ-ONLY call — it does not re-execute,
and points the model at the result it already has. A mutating tool is never
suppressed (a repeat there may be a deliberate poll/retry), and a call with
different arguments always runs.
"""

from __future__ import annotations

from typing import Any

from shipit_agent.agent import Agent
from shipit_agent.llms.base import LLMResponse, ToolCall
from shipit_agent.tools.base import ToolContext, ToolOutput


class _CountingTool:
    """A read-only tool that records how many times it actually executed."""

    read_only = True

    def __init__(self, name: str = "lookup", read_only: bool = True) -> None:
        self.name = name
        self.read_only = read_only
        self.runs: list[dict] = []

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "look something up",
                "parameters": {
                    "type": "object",
                    "properties": {"q": {"type": "string"}},
                    "required": ["q"],
                },
            },
        }

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        self.runs.append(dict(kwargs))
        return ToolOutput(text=f"result for {kwargs.get('q')}", metadata={"ok": True})


class _ScriptedLLM:
    """Emits a pre-set sequence of tool calls, then a final answer."""

    def __init__(self, calls: list[tuple[str, dict]]) -> None:
        self._calls = calls
        self.i = 0

    def complete(self, *, messages, tools=None, **_kw) -> LLMResponse:
        if self.i < len(self._calls):
            name, args = self._calls[self.i]
            self.i += 1
            return LLMResponse(tool_calls=[ToolCall(name=name, arguments=args)])
        return LLMResponse(content="done")


def _agent(tool, calls):
    return Agent(llm=_ScriptedLLM(calls), tools=[tool], auto_use_skills=False)


def test_identical_readonly_call_runs_once():
    tool = _CountingTool()
    # The model calls lookup(q="x") twice in a row — classic dithering.
    result = _agent(tool, [("lookup", {"q": "x"}), ("lookup", {"q": "x"})]).run("go")
    assert len(tool.runs) == 1                       # second call suppressed
    assert any(e.type == "tool_skipped_duplicate" for e in result.events)


def test_different_arguments_are_not_suppressed():
    tool = _CountingTool()
    result = _agent(tool, [("lookup", {"q": "x"}), ("lookup", {"q": "y"})]).run("go")
    assert len(tool.runs) == 2                       # different args → both run
    assert not any(e.type == "tool_skipped_duplicate" for e in result.events)


def test_mutating_tool_repeat_is_not_suppressed():
    # A non-read-only tool called twice with identical args still runs twice —
    # a repeat there may be a deliberate poll or retry.
    tool = _CountingTool(read_only=False)
    result = _agent(tool, [("lookup", {"q": "x"}), ("lookup", {"q": "x"})]).run("go")
    assert len(tool.runs) == 2
    assert not any(e.type == "tool_skipped_duplicate" for e in result.events)


def test_suppressed_call_tells_the_model_to_reuse():
    tool = _CountingTool()
    result = _agent(tool, [("lookup", {"q": "x"}), ("lookup", {"q": "x"})]).run("go")
    # The tool message for the skipped call must steer the model, not error.
    notes = [
        m for m in result.messages
        if getattr(m, "metadata", {}).get("duplicate_suppressed")
    ]
    assert notes and "reuse it" in notes[0].content.lower()
    assert "not run again" in notes[0].content.lower()


# ── async loop parity ─────────────────────────────────────────────────────────


def _async_run(tool, script):
    import asyncio

    from shipit_agent.async_runtime import AsyncAgentRuntime

    runtime = AsyncAgentRuntime(
        llm=_ScriptedLLM(script), prompt="You are helpful.", tools=[tool],
        max_iterations=5,
    )
    return asyncio.run(runtime.run("go"))


def test_async_loop_also_suppresses_duplicate_readonly_call():
    tool = _CountingTool()
    state, _ = _async_run(tool, [("lookup", {"q": "x"}), ("lookup", {"q": "x"})])
    assert len(tool.runs) == 1                       # async path suppresses too
    assert any(e.type == "tool_skipped_duplicate" for e in state.events)


def test_async_loop_runs_distinct_calls():
    tool = _CountingTool()
    state, _ = _async_run(tool, [("lookup", {"q": "x"}), ("lookup", {"q": "y"})])
    assert len(tool.runs) == 2
    assert not any(e.type == "tool_skipped_duplicate" for e in state.events)
