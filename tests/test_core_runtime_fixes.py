"""Regression tests for the core runtime bug fixes.

Covers:
- BUG-1  text_delta_callback backward compatibility (no TypeError on old adapters)
- BUG-2  multi-turn sessions don't stack duplicate system prompts
- CORE-1  MCP transports are closed even when the run raises
- CORE-2  parallel tools get isolated state that merges back correctly
- CORE-3  no duplicate final assistant message when the model narrates + calls a tool
- CORE-4  the iteration-cap summary turn's token usage is accounted for
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from shipit_agent import Agent, AsyncAgentRuntime, FunctionTool
from shipit_agent.llms.base import LLMResponse, accepts_text_delta_callback
from shipit_agent.models import ToolCall
from shipit_agent.runtime import (
    AgentRuntime,
    _isolated_tool_state,
    _merge_tool_state,
)


# ---------------------------------------------------------------------------
# Mock LLMs
# ---------------------------------------------------------------------------


class OldSignatureLLM:
    """Adapter written against the PRE-1.0.9 protocol (no text_delta_callback)."""

    def complete(self, *, messages, tools=None, system_prompt=None, metadata=None):
        return LLMResponse(content="ok")


class KwargsLLM:
    """Adapter that swallows everything via **kwargs."""

    def __init__(self) -> None:
        self.saw_callback = False

    def complete(self, *, messages, tools=None, system_prompt=None, **kwargs):
        self.saw_callback = "text_delta_callback" in kwargs
        return LLMResponse(content="ok")


class StreamingLLM:
    """Adapter that explicitly accepts and invokes text_delta_callback."""

    def complete(
        self,
        *,
        messages,
        tools=None,
        system_prompt=None,
        metadata=None,
        text_delta_callback=None,
    ):
        if text_delta_callback is not None:
            text_delta_callback("hel")
            text_delta_callback("lo")
        return LLMResponse(content="hello")


class NarratingFinalLLM:
    """Returns BOTH prose content and a tool call on every turn.

    With max_iterations=1 this exercises the "model narrated on the final
    iteration" path that previously duplicated the assistant message.
    """

    def complete(self, *, messages, tools=None, system_prompt=None, metadata=None):
        return LLMResponse(
            content="here is my narration",
            tool_calls=[ToolCall(name="noop", arguments={})],
        )


class CapThenSummaryLLM:
    """Calls a tool with empty content until the tools=[] summary turn.

    On the summary turn (tools is empty) it returns prose + usage, so we can
    assert the summary turn's tokens are accounted for.
    """

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, *, messages, tools=None, system_prompt=None, metadata=None):
        self.calls += 1
        if tools:
            return LLMResponse(
                content="",
                tool_calls=[ToolCall(name="noop", arguments={})],
                usage={"prompt_tokens": 10, "completion_tokens": 0, "total_tokens": 10},
            )
        # Summary turn (tools=[])
        return LLMResponse(
            content="final summary",
            usage={"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12},
        )


def _noop_tool() -> FunctionTool:
    return FunctionTool.from_callable(lambda **kw: "noop-result", name="noop")


def _artifact_tool(name: str, value: str) -> FunctionTool:
    def _fn(context, **kwargs: Any) -> str:
        context.state.setdefault("artifacts", []).append(value)
        return f"recorded {value}"

    return FunctionTool.from_callable(_fn, name=name)


# ---------------------------------------------------------------------------
# BUG-1 — text_delta_callback backward compatibility
# ---------------------------------------------------------------------------


class TestTextDeltaBackwardCompat:
    def test_helper_detects_support(self) -> None:
        assert accepts_text_delta_callback(StreamingLLM().complete) is True
        assert accepts_text_delta_callback(KwargsLLM().complete) is True  # **kwargs
        assert accepts_text_delta_callback(OldSignatureLLM().complete) is False

    def test_old_signature_adapter_does_not_raise(self) -> None:
        # Previously raised: TypeError: unexpected keyword 'text_delta_callback'
        result = Agent(llm=OldSignatureLLM(), auto_use_skills=False).run("hi")
        assert result.output == "ok"

    def test_kwargs_adapter_receives_callback(self) -> None:
        llm = KwargsLLM()
        Agent(llm=llm, auto_use_skills=False).run("hi")
        assert llm.saw_callback is True

    def test_streaming_adapter_emits_text_delta_events(self) -> None:
        agent = Agent(llm=StreamingLLM(), auto_use_skills=False)
        events = list(agent.stream("hi"))
        deltas = [e for e in events if e.type == "text_delta"]
        assert "".join(e.payload.get("chunk", "") for e in deltas) == "hello"

    def test_stream_emits_terminal_failure_event_before_raising(self) -> None:
        class BrokenLLM:
            def complete(self, **kwargs):
                raise ConnectionError("provider unavailable")

        stream = Agent(llm=BrokenLLM(), auto_use_skills=False).stream("hi")
        events = []
        with pytest.raises(ConnectionError, match="provider unavailable"):
            while True:
                events.append(next(stream))

        failed = [event for event in events if event.type == "run_failed"]
        assert len(failed) == 1
        assert failed[0].payload == {
            "error_type": "ConnectionError",
            "error": "provider unavailable",
            "retryable": True,
        }


# ---------------------------------------------------------------------------
# BUG-2 — multi-turn sessions don't stack system prompts
# ---------------------------------------------------------------------------


class TestSessionSystemPromptDedup:
    def test_chat_session_keeps_single_system_message(self) -> None:
        agent = Agent(llm=OldSignatureLLM(), auto_use_skills=False)
        session = agent.chat_session(session_id="multi-turn")
        for turn in ("first", "second", "third"):
            session.send(turn)
        history = session.history()
        system_messages = [m for m in history if m.role == "system"]
        assert len(system_messages) == 1
        assert history[0].role == "system"

    def test_message_count_grows_linearly_not_quadratically(self) -> None:
        # Without the fix each turn re-appended the full prior history, so the
        # message list grew super-linearly. One system + (user+assistant) per
        # turn => 1 + 2*N.
        agent = Agent(llm=OldSignatureLLM(), auto_use_skills=False)
        session = agent.chat_session(session_id="growth")
        for turn in range(4):
            session.send(f"turn {turn}")
        history = session.history()
        assert len(history) == 1 + 2 * 4


# ---------------------------------------------------------------------------
# CORE-3 — no duplicate final assistant message
# ---------------------------------------------------------------------------


class TestNoDuplicateFinalMessage:
    def test_narrating_final_iteration_not_duplicated(self) -> None:
        agent = Agent(
            llm=NarratingFinalLLM(),
            tools=[_noop_tool()],
            max_iterations=1,
            auto_use_skills=False,
        )
        result = agent.run("do it")
        narration_msgs = [
            m
            for m in result.messages
            if m.role == "assistant" and m.content == "here is my narration"
        ]
        # Exactly one assistant message carries the narration text.
        assert len(narration_msgs) == 1


# ---------------------------------------------------------------------------
# CORE-4 — summary turn usage is accounted for
# ---------------------------------------------------------------------------


class TestSummaryTurnUsageTracked:
    def test_summary_turn_tokens_counted(self) -> None:
        agent = Agent(
            llm=CapThenSummaryLLM(),
            tools=[_noop_tool()],
            max_iterations=1,
            auto_use_skills=False,
        )
        result = agent.run("go")
        completed = [e for e in result.events if e.type == "run_completed"]
        assert completed
        usage = completed[-1].payload["usage"]
        # 10 (iteration) + 12 (summary turn) must both be counted.
        assert usage["total_tokens"] == 22
        assert result.output == "final summary"


# ---------------------------------------------------------------------------
# CORE-1 — MCP transports closed even on error
# ---------------------------------------------------------------------------


class _FakeMCP:
    def __init__(self) -> None:
        self.name = "fake-mcp"
        self.closed = False

    def discover_tools(self):
        return []

    def close(self) -> None:
        self.closed = True


class _ExplodingLLM:
    def complete(self, *, messages, tools=None, system_prompt=None, metadata=None):
        raise RuntimeError("boom")


class TestMCPCleanupOnError:
    def test_mcp_closed_when_run_raises(self) -> None:
        mcp = _FakeMCP()
        runtime = AgentRuntime(
            llm=_ExplodingLLM(),
            prompt="p",
            tools=[],
            mcps=[mcp],
        )
        with pytest.raises(RuntimeError):
            runtime.run("hi")
        assert mcp.closed is True

    def test_mcp_closed_on_success(self) -> None:
        mcp = _FakeMCP()
        runtime = AgentRuntime(llm=OldSignatureLLM(), prompt="p", mcps=[mcp])
        runtime.run("hi")
        assert mcp.closed is True


# ---------------------------------------------------------------------------
# CORE-2 — parallel tool state isolation + merge
# ---------------------------------------------------------------------------


class TestParallelStateIsolation:
    def test_isolated_state_shares_services_copies_data(self) -> None:
        sentinel_store = object()
        shared = {"memory_store": sentinel_store, "artifacts": ["a"]}
        iso = _isolated_tool_state(shared)
        # service object shared by reference
        assert iso["memory_store"] is sentinel_store
        # data deep-copied (mutating the copy doesn't touch the original)
        iso["artifacts"].append("b")
        assert shared["artifacts"] == ["a"]

    def test_merge_extends_lists_without_duplicates(self) -> None:
        target = {"artifacts": ["a"]}
        _merge_tool_state(target, {"artifacts": ["a", "b"]})
        _merge_tool_state(target, {"artifacts": ["a", "c"]})
        assert target["artifacts"] == ["a", "b", "c"]

    def test_parallel_tools_both_record_artifacts(self) -> None:
        class TwoToolLLM:
            def __init__(self) -> None:
                self.called = False

            def complete(self, *, messages, tools=None, system_prompt=None, metadata=None):
                if not self.called:
                    self.called = True
                    return LLMResponse(
                        content="",
                        tool_calls=[
                            ToolCall(name="art_a", arguments={}),
                            ToolCall(name="art_b", arguments={}),
                        ],
                    )
                return LLMResponse(content="done")

        agent = Agent(
            llm=TwoToolLLM(),
            tools=[_artifact_tool("art_a", "A"), _artifact_tool("art_b", "B")],
            parallel_tool_execution=True,
            max_iterations=3,
            auto_use_skills=False,
        )
        # Both parallel tools ran and both results came back in order.
        result = agent.run("do both")
        outputs = [r.output for r in result.tool_results]
        assert "recorded A" in outputs
        assert "recorded B" in outputs


# ---------------------------------------------------------------------------
# Async runtime parity
# ---------------------------------------------------------------------------


class TestAsyncParity:
    def test_async_old_signature_adapter_runs(self) -> None:
        runtime = AsyncAgentRuntime(llm=OldSignatureLLM(), prompt="p")
        state, response = asyncio.run(runtime.run("hi"))
        assert response.content == "ok"

    def test_async_single_system_message_across_turns(self) -> None:
        from shipit_agent.stores import InMemorySessionStore

        store = InMemorySessionStore()
        for _ in range(3):
            runtime = AsyncAgentRuntime(
                llm=OldSignatureLLM(),
                prompt="p",
                session_store=store,
                session_id="async-multi",
            )
            asyncio.run(runtime.run("hi"))
        record = store.load("async-multi")
        system_messages = [m for m in record.messages if m.role == "system"]
        assert len(system_messages) == 1
