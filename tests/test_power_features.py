"""Tests for all v1.1 power features.

Covers: retry policy defaults, graceful tool failure, parallel tool execution,
context window management, hooks/middleware, mid-run re-planning, selective
memory, structured output, and async runtime.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from shipit_agent import (
    Agent,
    AgentHooks,
    AsyncAgentRuntime,
    FunctionTool,
    RetryPolicy,
    RouterPolicy,
)
from shipit_agent.llms import LLMResponse, SimpleEchoLLM
from shipit_agent.llms.base import LLMResponse as BaseLLMResponse
from shipit_agent.models import Message, ToolCall, ToolResult
from shipit_agent.policies import RetryPolicy as RP
from shipit_agent.runtime import AgentRuntime
from shipit_agent.stores import InMemoryMemoryStore
from shipit_agent.tools import ToolContext, ToolOutput


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class SingleToolCallLLM:
    """LLM that calls a tool once, then responds."""
    def __init__(self, tool_name: str, tool_args: dict[str, Any] | None = None):
        self._tool_name = tool_name
        self._tool_args = tool_args or {}
        self._called = False

    def complete(self, *, messages, tools=None, system_prompt=None, metadata=None, response_format=None):
        if not self._called:
            self._called = True
            return LLMResponse(content="", tool_calls=[ToolCall(name=self._tool_name, arguments=self._tool_args)])
        return LLMResponse(content="done")


class MultiToolCallLLM:
    """LLM that calls multiple tools in one turn, then responds."""
    def __init__(self, calls: list[tuple[str, dict[str, Any]]]):
        self._calls = calls
        self._called = False

    def complete(self, *, messages, tools=None, system_prompt=None, metadata=None, response_format=None):
        if not self._called:
            self._called = True
            return LLMResponse(
                content="",
                tool_calls=[ToolCall(name=n, arguments=a) for n, a in self._calls],
            )
        return LLMResponse(content="all done")


class IteratingLLM:
    """LLM that calls a tool every turn for N iterations."""
    def __init__(self, tool_name: str, iterations: int):
        self._tool_name = tool_name
        self._count = 0
        self._iterations = iterations

    def complete(self, *, messages, tools=None, system_prompt=None, metadata=None, response_format=None):
        self._count += 1
        if self._count <= self._iterations:
            return LLMResponse(content="", tool_calls=[ToolCall(name=self._tool_name, arguments={})])
        return LLMResponse(content="done after iterations")


def _make_simple_tool(name: str, output: str = "ok") -> FunctionTool:
    def _fn(**kwargs: Any) -> str:
        return output
    return FunctionTool.from_callable(_fn, name=name)


# ---------------------------------------------------------------------------
# 1. RetryPolicy defaults
# ---------------------------------------------------------------------------


class TestRetryPolicyDefaults:
    def test_default_exceptions_are_network_errors(self) -> None:
        policy = RP()
        assert ConnectionError in policy.retry_on_exceptions
        assert TimeoutError in policy.retry_on_exceptions
        assert OSError in policy.retry_on_exceptions

    def test_runtime_error_not_retried_by_default(self) -> None:
        policy = RP()
        assert RuntimeError not in policy.retry_on_exceptions

    def test_custom_exceptions_override(self) -> None:
        policy = RP(retry_on_exceptions=(ValueError,))
        assert ValueError in policy.retry_on_exceptions
        assert ConnectionError not in policy.retry_on_exceptions


# ---------------------------------------------------------------------------
# 2. Graceful tool failure
# ---------------------------------------------------------------------------


class TestGracefulToolFailure:
    def test_tool_failure_does_not_crash_run(self) -> None:
        """When a tool fails after retries, the agent continues with an error message."""
        def failing_tool(**kwargs: Any) -> str:
            raise ConnectionError("connection refused")

        agent = Agent(
            llm=SingleToolCallLLM("fail_tool"),
            tools=[FunctionTool.from_callable(failing_tool, name="fail_tool")],
            retry_policy=RetryPolicy(max_tool_retries=0, retry_on_exceptions=(ConnectionError,)),
        )
        result = agent.run("do something")
        # The run should complete (not raise)
        assert result.output == "done"
        # Should have a tool_failed event
        assert any(e.type == "tool_failed" for e in result.events)
        # The error message should be in the messages
        error_msgs = [m for m in result.messages if m.role == "tool" and "Error running tool" in m.content]
        assert error_msgs

    def test_hallucinated_tool_produces_error_message(self) -> None:
        """Calling a non-existent tool produces an error message, not a crash."""
        agent = Agent(
            llm=SingleToolCallLLM("nonexistent_tool"),
            tools=[],
        )
        result = agent.run("call something")
        assert result.output == "done"
        error_msgs = [m for m in result.messages if m.role == "tool" and "not registered" in m.content]
        assert error_msgs


# ---------------------------------------------------------------------------
# 3. Parallel tool execution
# ---------------------------------------------------------------------------


class TestParallelToolExecution:
    def test_parallel_execution_produces_same_results(self) -> None:
        """Parallel mode should produce the same tool results as sequential."""
        calls = [("tool_a", {}), ("tool_b", {})]
        agent = Agent(
            llm=MultiToolCallLLM(calls),
            tools=[_make_simple_tool("tool_a", "result_a"), _make_simple_tool("tool_b", "result_b")],
            parallel_tool_execution=True,
        )
        result = agent.run("run both")
        assert result.output == "all done"
        outputs = {tr.name: tr.output for tr in result.tool_results}
        assert outputs == {"tool_a": "result_a", "tool_b": "result_b"}

    def test_parallel_preserves_message_order(self) -> None:
        """Tool result messages should appear in the same order as tool calls."""
        calls = [("t1", {}), ("t2", {}), ("t3", {})]
        agent = Agent(
            llm=MultiToolCallLLM(calls),
            tools=[_make_simple_tool("t1"), _make_simple_tool("t2"), _make_simple_tool("t3")],
            parallel_tool_execution=True,
        )
        result = agent.run("go")
        tool_msgs = [m for m in result.messages if m.role == "tool"]
        names = [m.name for m in tool_msgs]
        assert names == ["t1", "t2", "t3"]

    def test_sequential_execution_is_default(self) -> None:
        """Default mode should be sequential (parallel_tool_execution=False)."""
        agent = Agent(llm=SimpleEchoLLM())
        assert agent.parallel_tool_execution is False

    def test_single_tool_call_runs_sequentially_even_in_parallel_mode(self) -> None:
        """When only 1 tool is called, parallel mode still works fine."""
        agent = Agent(
            llm=SingleToolCallLLM("solo"),
            tools=[_make_simple_tool("solo", "solo_result")],
            parallel_tool_execution=True,
        )
        result = agent.run("one tool")
        assert result.tool_results[0].output == "solo_result"


# ---------------------------------------------------------------------------
# 4. Context window management
# ---------------------------------------------------------------------------


class TestContextWindowManagement:
    def test_usage_field_on_llm_response(self) -> None:
        """LLMResponse should have a usage dict."""
        resp = BaseLLMResponse(content="hello")
        assert resp.usage == {}

        resp2 = BaseLLMResponse(content="hello", usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15})
        assert resp2.usage["total_tokens"] == 15

    def test_usage_tracked_across_iterations(self) -> None:
        """Runtime should accumulate usage stats."""
        class UsageTrackingLLM:
            def __init__(self):
                self._calls = 0
            def complete(self, *, messages, tools=None, system_prompt=None, metadata=None, response_format=None):
                self._calls += 1
                return LLMResponse(
                    content="done" if self._calls > 1 else "",
                    tool_calls=[ToolCall(name="t", arguments={})] if self._calls == 1 else [],
                    usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
                )

        runtime = AgentRuntime(
            llm=UsageTrackingLLM(),
            prompt="test",
            tools=[_make_simple_tool("t")],
        )
        state, response = runtime.run("go")
        # Should have accumulated usage from 2 LLM calls
        completed_event = next(e for e in state.events if e.type == "run_completed")
        assert completed_event.payload["usage"]["total_tokens"] == 300

    def test_compaction_triggers_when_over_threshold(self) -> None:
        """Messages should be compacted when approaching context window."""
        runtime = AgentRuntime(
            llm=SimpleEchoLLM(),
            prompt="test",
            context_window_tokens=100,  # very small
        )
        # Create messages with lots of content — need >4 non-system exchanges
        messages = [
            Message(role="system", content="system prompt"),
            Message(role="user", content="x" * 200),
            Message(role="assistant", content="a" * 200),
            Message(role="tool", name="t1", content="y" * 200),
            Message(role="user", content="follow up"),
            Message(role="assistant", content="z" * 200),
            Message(role="tool", name="t2", content="w" * 200),
            Message(role="user", content="latest question"),
        ]
        compacted = runtime._compact_messages(messages)
        assert len(compacted) < len(messages)
        # Should have a compacted message
        compacted_msgs = [m for m in compacted if m.metadata.get("compacted")]
        assert compacted_msgs

    def test_no_compaction_when_under_threshold(self) -> None:
        """Messages should not be compacted when under the threshold."""
        runtime = AgentRuntime(
            llm=SimpleEchoLLM(),
            prompt="test",
            context_window_tokens=1000000,  # huge
        )
        messages = [
            Message(role="system", content="prompt"),
            Message(role="user", content="hi"),
        ]
        result = runtime._compact_messages(messages)
        assert result == messages

    def test_no_compaction_when_disabled(self) -> None:
        """No compaction when context_window_tokens=0."""
        runtime = AgentRuntime(
            llm=SimpleEchoLLM(),
            prompt="test",
            context_window_tokens=0,
        )
        messages = [Message(role="user", content="x" * 10000)]
        result = runtime._compact_messages(messages)
        assert result == messages


# ---------------------------------------------------------------------------
# 5. Hooks/middleware
# ---------------------------------------------------------------------------


class TestHooks:
    def test_hooks_before_and_after_llm(self) -> None:
        """Before/after LLM hooks are called."""
        log: list[str] = []
        hooks = AgentHooks()

        @hooks.on_before_llm
        def before(messages, tools):
            log.append("before_llm")

        @hooks.on_after_llm
        def after(response):
            log.append("after_llm")

        agent = Agent(llm=SimpleEchoLLM(), hooks=hooks)
        agent.run("hello")
        assert "before_llm" in log
        assert "after_llm" in log

    def test_hooks_before_and_after_tool(self) -> None:
        """Before/after tool hooks are called."""
        log: list[str] = []
        hooks = AgentHooks()

        @hooks.on_before_tool
        def before(name, args):
            log.append(f"before:{name}")

        @hooks.on_after_tool
        def after(name, result):
            log.append(f"after:{name}")

        agent = Agent(
            llm=SingleToolCallLLM("my_tool"),
            tools=[_make_simple_tool("my_tool")],
            hooks=hooks,
        )
        agent.run("use tool")
        assert "before:my_tool" in log
        assert "after:my_tool" in log

    def test_hooks_decorator_returns_function(self) -> None:
        """Decorators should return the original function."""
        hooks = AgentHooks()

        @hooks.on_before_llm
        def my_hook(messages, tools):
            pass

        assert callable(my_hook)
        assert my_hook in hooks.before_llm

    def test_no_hooks_does_not_crash(self) -> None:
        """Agent should work fine with hooks=None."""
        agent = Agent(llm=SimpleEchoLLM(), hooks=None)
        result = agent.run("hello")
        assert result.output


# ---------------------------------------------------------------------------
# 6. Mid-run re-planning
# ---------------------------------------------------------------------------


class TestMidRunRePlanning:
    def test_replan_triggers_at_interval(self) -> None:
        """Planner should re-run at the specified interval."""
        from shipit_agent import PlannerTool

        agent = Agent(
            llm=IteratingLLM("noop", 4),
            tools=[_make_simple_tool("noop"), PlannerTool()],
            max_iterations=6,
            replan_interval=2,
            router_policy=RouterPolicy(auto_plan=True, long_prompt_threshold=1),
        )
        result = agent.run("Build a complex system with multiple components")
        # Should have multiple planning events
        planning_events = [e for e in result.events if e.type == "planning_started"]
        # At least initial + one mid-run replan
        assert len(planning_events) >= 2

    def test_no_replan_when_interval_zero(self) -> None:
        """No re-planning when replan_interval=0."""
        from shipit_agent import PlannerTool

        agent = Agent(
            llm=IteratingLLM("noop", 2),
            tools=[_make_simple_tool("noop"), PlannerTool()],
            max_iterations=4,
            replan_interval=0,
            router_policy=RouterPolicy(auto_plan=True, long_prompt_threshold=1),
        )
        result = agent.run("Build a complex system")
        planning_events = [e for e in result.events if e.type == "planning_started"]
        # Only the initial plan
        assert len(planning_events) == 1


# ---------------------------------------------------------------------------
# 7. Selective memory storage
# ---------------------------------------------------------------------------


class TestSelectiveMemory:
    def test_non_persistent_results_not_stored(self) -> None:
        """Tool results without persist=True should not be stored in memory."""
        memory = InMemoryMemoryStore()
        agent = Agent(
            llm=SingleToolCallLLM("my_tool"),
            tools=[_make_simple_tool("my_tool", "some output")],
            memory_store=memory,
        )
        agent.run("do something")
        assert memory.search("some output") == []

    def test_persistent_results_stored(self) -> None:
        """Tool results with persist=True should be stored in memory."""
        memory = InMemoryMemoryStore()

        class PersistingTool:
            name = "persist_tool"
            description = "Tool that persists"
            prompt_instructions = ""
            def schema(self):
                return {"type": "function", "function": {"name": self.name, "description": self.description, "parameters": {"type": "object", "properties": {}}}}
            def run(self, context, **kwargs):
                return ToolOutput(text="important fact", metadata={"persist": True})

        agent = Agent(
            llm=SingleToolCallLLM("persist_tool"),
            tools=[PersistingTool()],
            memory_store=memory,
        )
        agent.run("save something")
        matches = memory.search("important")
        assert matches


# ---------------------------------------------------------------------------
# 8. Structured output support
# ---------------------------------------------------------------------------


class TestStructuredOutput:
    def test_response_format_accepted_by_simple_llm(self) -> None:
        """SimpleEchoLLM should accept response_format without error."""
        llm = SimpleEchoLLM()
        resp = llm.complete(
            messages=[Message(role="user", content="test")],
            response_format={"type": "json_object"},
        )
        assert resp.content

    def test_llm_response_has_usage_field(self) -> None:
        """LLMResponse should carry usage data."""
        resp = LLMResponse(content="hi", usage={"prompt_tokens": 10})
        assert resp.usage["prompt_tokens"] == 10


# ---------------------------------------------------------------------------
# 9. Async runtime
# ---------------------------------------------------------------------------


class TestAsyncRuntime:
    def test_async_run_basic(self) -> None:
        """AsyncAgentRuntime.run should produce the same result as sync."""
        runtime = AsyncAgentRuntime(llm=SimpleEchoLLM(), prompt="System")
        state, response = asyncio.run(runtime.run("Hello async"))
        assert "Hello async" in response.content

    def test_async_run_with_tools(self) -> None:
        """Async runtime should execute tool calls."""
        runtime = AsyncAgentRuntime(
            llm=SingleToolCallLLM("greet", {"name": "world"}),
            prompt="System",
            tools=[_make_simple_tool("greet", "hello world")],
        )
        state, response = asyncio.run(runtime.run("greet"))
        assert response.content == "done"
        assert state.tool_results[0].output == "hello world"

    def test_async_stream(self) -> None:
        """Async streaming should yield events."""
        runtime = AsyncAgentRuntime(llm=SimpleEchoLLM(), prompt="System")

        async def collect_events():
            events = []
            async for event in runtime.stream("Hello stream"):
                events.append(event)
            return events

        events = asyncio.run(collect_events())
        assert events
        assert events[0].type == "run_started"
        assert events[-1].type == "run_completed"

    def test_async_parallel_tools(self) -> None:
        """Async runtime should support parallel tool execution."""
        runtime = AsyncAgentRuntime(
            llm=MultiToolCallLLM([("a", {}), ("b", {})]),
            prompt="System",
            tools=[_make_simple_tool("a", "ra"), _make_simple_tool("b", "rb")],
            parallel_tool_execution=True,
        )
        state, response = asyncio.run(runtime.run("go"))
        outputs = {tr.name: tr.output for tr in state.tool_results}
        assert outputs == {"a": "ra", "b": "rb"}

    def test_async_graceful_tool_failure(self) -> None:
        """Async runtime should handle tool failures gracefully."""
        def failing(**kwargs):
            raise ConnectionError("fail")

        runtime = AsyncAgentRuntime(
            llm=SingleToolCallLLM("fail_tool"),
            prompt="System",
            tools=[FunctionTool.from_callable(failing, name="fail_tool")],
            retry_policy=RetryPolicy(max_tool_retries=0, retry_on_exceptions=(ConnectionError,)),
        )
        state, response = asyncio.run(runtime.run("fail"))
        assert response.content == "done"
        assert any(e.type == "tool_failed" for e in state.events)

    def test_async_hooks(self) -> None:
        """Async runtime should call hooks."""
        log: list[str] = []
        hooks = AgentHooks()
        hooks.on_before_llm(lambda msgs, tools: log.append("before"))
        hooks.on_after_llm(lambda resp: log.append("after"))

        runtime = AsyncAgentRuntime(llm=SimpleEchoLLM(), prompt="System", hooks=hooks)
        asyncio.run(runtime.run("hi"))
        assert "before" in log
        assert "after" in log
