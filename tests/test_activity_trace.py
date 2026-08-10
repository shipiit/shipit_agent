"""Tests for the activity-trace renderer, event timing, and MCP error wrapping."""

from __future__ import annotations

from typing import Any

from shipit_agent import Agent, FunctionTool, format_activity, format_event_line
from shipit_agent.llms.base import LLMResponse, ToolCall
from shipit_agent.mcp import MCPError, MCPRemoteTool
from shipit_agent.models import AgentEvent
from shipit_agent.tools.base import ToolContext


class ToolThenAnswerLLM:
    """First call → a tool call; second call → a final answer."""

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, *, messages, tools=None, **_kwargs) -> LLMResponse:
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(
                tool_calls=[ToolCall(name="add", arguments={"a": 2, "b": 3})]
            )
        return LLMResponse(content="The sum is 5.")


def add(a: int, b: int, **_ignored) -> str:
    return str(a + b)


def _run_agent():
    agent = Agent(
        llm=ToolThenAnswerLLM(),
        tools=[FunctionTool.from_callable(add)],
        auto_use_skills=False,
    )
    return agent.run("What is 2+3?")


class TestEventTiming:
    def test_events_have_timestamps(self) -> None:
        result = _run_agent()
        assert result.events
        assert all(e.timestamp > 0 for e in result.events)

    def test_tool_completed_carries_tool_and_duration(self) -> None:
        result = _run_agent()
        done = [e for e in result.events if e.type == "tool_completed"]
        assert done
        assert done[0].payload["tool"] == "add"
        assert isinstance(done[0].payload["duration_ms"], float)
        assert done[0].payload["duration_ms"] >= 0

    def test_event_to_dict_includes_timestamp(self) -> None:
        event = AgentEvent(type="run_started", message="go")
        assert "timestamp" in event.to_dict()

    def test_event_print_preserves_the_complete_diagnostic_payload(self) -> None:
        event = AgentEvent(
            type="agent_observation",
            message="generic",
            payload={"summary": "Read app.py.", "large": "x" * 10_000},
        )
        rendered = str(event)
        assert "AgentEvent(type='agent_observation'" in rendered
        assert "message='generic'" in rendered
        assert "payload={'summary': 'Read app.py.'" in rendered
        assert "'large': '" + "x" * 100 in rendered
        assert "timestamp=" in rendered

    def test_delta_raw_repr_preserves_its_chunk(self) -> None:
        event = AgentEvent(
            type="text_delta",
            message="",
            payload={"chunk": "Retry eligibility depends on status."},
        )
        assert event.display_message == "Retry eligibility depends on status."
        assert "message=''" in repr(event)
        assert "'chunk': 'Retry eligibility depends on status.'" in repr(event)

    def test_stream_events_print_complete_tool_output_and_telemetry(self) -> None:
        completed = next(
            event for event in _run_agent().events if event.type == "tool_completed"
        )
        rendered = str(completed)

        assert "AgentEvent(type='tool_completed'" in rendered
        assert "'output': '5'" in rendered
        assert "'output_chars': 1" in rendered
        assert "'model_output_chars': 1" in rendered
        assert "timestamp=" in rendered


class TestFormatActivity:
    def test_renders_tool_card_with_args_status_duration(self) -> None:
        result = _run_agent()
        trace = format_activity(result)
        assert "⚙ add(" in trace
        assert "a=2" in trace and "b=3" in trace
        assert "✓" in trace
        assert "ms" in trace or "s" in trace
        assert "└ 5" in trace  # output preview
        assert "✔ run completed · 1 tool call" in trace

    def test_failed_tool_rendered_with_error(self) -> None:
        events = [
            AgentEvent(
                type="tool_called",
                message="",
                payload={"tool": "boom", "arguments": {"x": 1}, "iteration": 0},
            ),
            AgentEvent(
                type="tool_failed",
                message="",
                payload={
                    "tool": "boom",
                    "error": "kaput",
                    "duration_ms": 12.0,
                    "iteration": 0,
                },
            ),
        ]
        trace = format_activity(events)
        assert "⚙ boom(" in trace and "✗" in trace
        assert "error: kaput" in trace
        assert "(1 failed)" in trace

    def test_long_output_clipped(self) -> None:
        events = [
            AgentEvent(type="tool_called", message="", payload={"tool": "t"}),
            AgentEvent(
                type="tool_completed",
                message="",
                payload={"tool": "t", "output": "x" * 5000},
            ),
        ]
        trace = format_activity(events)
        assert "…" in trace
        assert len(trace) < 1000


class TestFormatEventLine:
    def test_live_lines(self) -> None:
        called = AgentEvent(
            type="tool_called",
            message="",
            payload={"tool": "bash", "arguments": {"command": "ls"}},
        )
        line = format_event_line(called)
        assert line is not None and "bash" in line and "…" in line
        # non-user-facing events return None
        assert format_event_line(AgentEvent(type="run_started", message="")) is None

    def test_renders_decisions_and_observations(self) -> None:
        decision = AgentEvent(
            type="agent_decision",
            message="I will inspect the retry implementation.",
            payload={"generated_by_model": True},
        )
        observation = AgentEvent(
            type="agent_observation",
            message="Read retry.py — 81 lines.",
            payload={"generated_by_model": False},
        )

        assert format_event_line(decision) == (
            "agent_decision     I will inspect the retry implementation."
        )
        assert format_event_line(observation) == (
            "agent_observation  Read retry.py — 81 lines."
        )

    def test_renders_selected_skills_and_injected_tools(self) -> None:
        event = AgentEvent(
            type="skills_selected",
            message="Skills selected: debugging",
            payload={
                "skill_ids": ["debugging"],
                "injected_tools": ["read_file", "bash"],
            },
        )

        assert format_event_line(event) == (
            "skills  debugging (tools: read_file, bash)"
        )


class TestMCPErrorWrapping:
    def test_transport_failure_becomes_tool_output(self) -> None:
        class FailingTransport:
            def request(self, method: str, params: Any = None) -> dict:
                raise MCPError("server exploded")

            def close(self) -> None:
                pass

        tool = MCPRemoteTool(
            server_name="srv",
            transport=FailingTransport(),
            name="remote_thing",
            description="",
        )
        out = tool.run(ToolContext(prompt="", system_prompt="", state={}))
        assert "failed: server exploded" in out.text
        assert out.metadata["ok"] is False

    def test_aliases_exported(self) -> None:
        from shipit_agent import MCPStdioTransport, PersistentMCPSession
        from shipit_agent.mcp import (
            MCPSubprocessTransport,
            PersistentMCPSubprocessTransport,
        )

        assert MCPStdioTransport is MCPSubprocessTransport
        assert PersistentMCPSession is PersistentMCPSubprocessTransport
