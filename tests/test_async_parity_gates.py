"""Async loop parity: the argument gate and compaction actually RUN there.

The parity test asserts neither loop *overrides* a RuntimeCore decision —
but non-override is not invocation. These tests pin the invocations: an
empty structured call is refused by the async loop, and an async run past
the window compacts (once), with the summarizer's tokens counted.
"""

from __future__ import annotations

import asyncio

from shipit_agent.async_runtime import AsyncAgentRuntime
from shipit_agent.llms.base import LLMResponse
from shipit_agent.models import Message, ToolCall
from shipit_agent.runtime import AgentRuntime
from shipit_agent.tools.base import ToolOutput


class SearchTool:
    name = "search_echo"
    description = "Search the corpus."

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        }

    def __init__(self):
        self.calls = 0

    def run(self, context, **kwargs) -> ToolOutput:
        self.calls += 1
        return ToolOutput(text="the whole corpus", metadata={})


class ScriptedLLM:
    def __init__(self, script):
        self.script = list(script)

    def complete(self, *, messages, tools=None, system_prompt=None, metadata=None):
        text, calls = self.script.pop(0) if self.script else ("done", [])
        return LLMResponse(
            content=text,
            tool_calls=[ToolCall(name=n, arguments=dict(a)) for n, a in calls],
        )


def test_async_argument_gate_refuses_empty_call():
    tool = SearchTool()
    llm = ScriptedLLM(
        [
            ("searching", [("search_echo", {"query": ""})]),
            ("done", []),
        ]
    )
    runtime = AsyncAgentRuntime(
        llm=llm,
        prompt="You are helpful.",
        tools=[tool],
        max_iterations=3,
    )
    state, response = asyncio.run(runtime.run("find qilin"))

    assert tool.calls == 0, "an empty required call must never run the tool"
    rejected = [e for e in state.events if e.type == "tool_arguments_rejected"]
    assert rejected, "the refusal must be visible on the event stream"
    # The corrective message reaches the conversation so the model can fix it.
    tool_msgs = [m for m in state.messages if m.role == "tool"]
    assert any(
        (m.metadata or {}).get("error") == "missing_required_arguments"
        for m in tool_msgs
    )
    assert response.content == "done"


class CountingSummarizerLLM:
    """Echo LLM that counts summarizer invocations (purpose metadata)."""

    def __init__(self, script):
        self.script = list(script)
        self.summaries = 0

    def complete(self, *, messages, tools=None, system_prompt=None, metadata=None):
        if (metadata or {}).get("purpose") == "context_compaction":
            self.summaries += 1
            return LLMResponse(
                content="handoff summary", usage={"total_tokens": 7}
            )
        text, calls = self.script.pop(0) if self.script else ("done", [])
        return LLMResponse(
            content=text,
            tool_calls=[ToolCall(name=n, arguments=dict(a)) for n, a in calls],
        )


def _bulk_history(n: int = 6) -> list[Message]:
    return [
        Message(role="user" if i % 2 == 0 else "assistant", content="x" * 2000)
        for i in range(n)
    ]


def test_async_loop_compacts_when_over_window():
    llm = CountingSummarizerLLM([("step", []), ("done", [])])
    runtime = AsyncAgentRuntime(
        llm=llm,
        prompt="You are helpful.",
        history_messages=_bulk_history(),
        context_window_tokens=800,  # far below the ~3k tokens of history
        max_iterations=2,
    )
    state, _ = asyncio.run(runtime.run("hello"))
    compacted = [e for e in state.events if e.type == "context_compacted"]
    assert compacted, "async runs must compact like sync runs"


def test_compaction_reuses_checkpoint_instead_of_resummarizing():
    llm = CountingSummarizerLLM([(f"step {i}", []) for i in range(3)])
    runtime = AgentRuntime(
        llm=llm,
        prompt="You are helpful.",
        history_messages=_bulk_history(),
        context_window_tokens=800,
        max_iterations=3,
    )
    state, _ = runtime.run("hello")
    # The threshold is exceeded on every iteration (state.messages never
    # shrinks) — but the checkpoint is reused, so ONE summary is written.
    assert llm.summaries == 1, f"expected one summary, got {llm.summaries}"
    # And the summary's own tokens were counted.
    usage_events = [e for e in state.events if e.type == "usage_tick"]
    assert any(e.payload["usage"]["total_tokens"] >= 7 for e in usage_events)
