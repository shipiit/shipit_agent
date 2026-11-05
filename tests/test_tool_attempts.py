"""A tool call's attempts: retries, the failure the model reads, and live output."""

from __future__ import annotations

from typing import Any

from shipit_agent import Agent, FunctionTool, Guardrails
from shipit_agent.core.models import ToolCall
from shipit_agent.core.policies import RetryPolicy
from shipit_agent.llms import LLMResponse


class _OneCallLLM:
    """Calls *tool_name* once, then answers."""

    def __init__(self, tool_name: str) -> None:
        self.tool_name = tool_name
        self.called = False

    def complete(self, **_: Any) -> LLMResponse:
        if not self.called:
            self.called = True
            return LLMResponse(
                content="", tool_calls=[ToolCall(name=self.tool_name, arguments={})]
            )
        return LLMResponse(content="finished")


def _always_raises(error: Exception) -> tuple[FunctionTool, dict[str, int]]:
    """A tool that raises *error* on every call, and its call counter."""
    calls = {"count": 0}

    def broken() -> str:
        calls["count"] += 1
        raise error

    return FunctionTool.from_callable(broken, name="broken"), calls


def _events(result: Any, kind: str) -> list[Any]:
    return [event for event in result.events if event.type == kind]


def test_retries_run_out_and_the_model_reads_the_error() -> None:
    tool, calls = _always_raises(RuntimeError("upstream down"))
    agent = Agent(
        llm=_OneCallLLM("broken"),
        tools=[tool],
        retry_policy=RetryPolicy(
            max_tool_retries=2, retry_on_exceptions=(RuntimeError,)
        ),
    )

    result = agent.run("go")

    assert calls["count"] == 3
    assert [event.payload["attempt"] for event in _events(result, "tool_retry")] == [
        1,
        2,
    ]
    final = result.tool_results[-1]
    assert final.is_error
    assert final.output == "Error running tool 'broken': upstream down"
    assert final.metadata == {"error": "upstream down"}
    assert result.output == "finished"


def test_the_error_chunk_carries_the_last_attempt_number() -> None:
    agent = Agent(
        llm=_OneCallLLM("broken"),
        tools=[_always_raises(RuntimeError("upstream down"))[0]],
        retry_policy=RetryPolicy(
            max_tool_retries=1, retry_on_exceptions=(RuntimeError,)
        ),
    )

    result = agent.run("go")

    started = [
        event.payload["attempt"] for event in _events(result, "tool_output_started")
    ]
    assert started == [1, 2]
    deltas = _events(result, "tool_output_delta")
    assert [delta.payload["chunk"] for delta in deltas] == [
        "Error running tool 'broken': upstream down"
    ]
    assert deltas[0].payload["attempt"] == 2
    assert deltas[0].payload["sequence"] == 1


def test_an_unexpected_exception_is_not_retried_and_names_its_type() -> None:
    tool, calls = _always_raises(ValueError("bad input"))
    agent = Agent(
        llm=_OneCallLLM("broken"),
        tools=[tool],
        retry_policy=RetryPolicy(
            max_tool_retries=3, retry_on_exceptions=(ConnectionError,)
        ),
    )

    result = agent.run("go")

    assert calls["count"] == 1
    assert _events(result, "tool_retry") == []
    final = result.tool_results[-1]
    assert final.is_error
    assert final.metadata == {"error": "bad input", "error_type": "ValueError"}
    deltas = _events(result, "tool_output_delta")
    assert deltas[0].payload["chunk_metadata"]["error_type"] == "ValueError"


def test_with_guardrails_a_failure_is_published_once_after_checking() -> None:
    agent = Agent(
        llm=_OneCallLLM("broken"),
        tools=[_always_raises(ValueError("bad input"))[0]],
        guardrails=Guardrails(),
    )

    result = agent.run("go")

    assert _events(result, "tool_output_started")[0].payload["buffered"] is True
    deltas = _events(result, "tool_output_delta")
    assert len(deltas) == 1
    assert deltas[0].payload["chunk_metadata"] == {"buffered": True}
    assert result.tool_results[-1].is_error
