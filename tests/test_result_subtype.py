"""A run's result says how it ended, as the Claude Agent SDK's result subtypes do.

``result.subtype`` is ``success``, ``error_max_turns``,
``error_max_budget_usd``, ``error_max_budget_tokens`` or
``error_during_execution``; ``result.is_error`` is True for all but the
first. A caller branches on it instead of parsing reason strings.
"""

from __future__ import annotations

from typing import Any

import pytest

from shipit_agent import Agent, FunctionTool
from shipit_agent.core.models import AgentResult, ToolCall, result_subtype
from shipit_agent.llms.base import LLMResponse


def _lookup(query: str = "") -> str:
    """Look up."""
    return "x"


class _Calls:
    model = "claude-sonnet-4-6"

    def __init__(self, *, then: str = "", usage: dict[str, int] | None = None) -> None:
        self.then = then
        self.usage = usage or {}
        self.n = 0

    def complete(self, *, tools: Any = None, **_: Any) -> LLMResponse:
        self.n += 1
        if self.then and self.n > 1:
            return LLMResponse(content=self.then, usage=dict(self.usage))
        return LLMResponse(
            content="",
            tool_calls=[ToolCall(name="lookup", arguments={"query": str(self.n)})],
            usage=dict(self.usage),
        )


def _agent(llm: Any, **options: Any) -> Agent:
    return Agent(
        llm=llm, tools=[FunctionTool.from_callable(_lookup, name="lookup")], **options
    )


def test_a_finished_run_is_a_success() -> None:
    result = _agent(_Calls(then="done")).run("go")
    assert result.subtype == "success"
    assert result.is_error is False
    assert result.metadata["run_summary"]["subtype"] == "success"


def test_the_step_limit_is_error_max_turns() -> None:
    result = _agent(_Calls(), max_iterations=2).run("go")
    assert result.subtype == "error_max_turns"
    assert result.is_error is True


def test_the_cost_budget_is_error_max_budget_usd() -> None:
    usage = {
        "prompt_tokens": 100_000,
        "completion_tokens": 10_000,
        "total_tokens": 110_000,
    }
    result = _agent(_Calls(usage=usage), max_budget_usd=0.5).run("go")
    assert result.subtype == "error_max_budget_usd"


@pytest.mark.parametrize(
    ("reason", "subtype"),
    [
        (None, "success"),
        ("max_iterations", "error_max_turns"),
        ("max_budget_usd", "error_max_budget_usd"),
        ("budget_cost_unavailable", "error_max_budget_usd"),
        ("task_token_budget", "error_max_budget_tokens"),
        ("session_token_budget", "error_max_budget_tokens"),
        ("task_budget_usage_unavailable", "error_max_budget_tokens"),
        ("empty_response", "error_during_execution"),
        ("degenerate_repetition", "error_during_execution"),
        ("something_new", "error_during_execution"),
    ],
)
def test_each_reason_maps_to_a_subtype(reason: str | None, subtype: str) -> None:
    status = "finished" if reason is None else "incomplete"
    assert (
        result_subtype({"incomplete_reason": reason, "completion_status": status})
        == subtype
    )


def test_giving_up_or_running_out_of_output_is_an_execution_error() -> None:
    assert (
        result_subtype({"completion_status": "incomplete", "gave_up": True})
        == "error_during_execution"
    )
    assert (
        result_subtype({"completion_status": "incomplete", "finish_reason": "length"})
        == "error_during_execution"
    )


def test_a_result_without_a_summary_is_a_success() -> None:
    assert AgentResult(output="hi").subtype == "success"
