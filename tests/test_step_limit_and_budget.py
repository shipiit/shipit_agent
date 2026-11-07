"""No step limit by default; ``max_iterations`` and ``max_budget_usd`` are opt-in caps.

A run ends when the model answers without calling a tool. A long task is not
cut off at an arbitrary step count; a caller who wants a ceiling sets one, in
steps or in dollars.
"""

from __future__ import annotations

from typing import Any

import pytest

from shipit_agent import Agent, AsyncAgentRuntime, FunctionTool
from shipit_agent.core.models import ToolCall
from shipit_agent.core.runtime import AgentRuntime
from shipit_agent.llms.base import LLMResponse


def _lookup(query: str = "") -> str:
    """Look something up."""
    return f"result for {query}"


class _Steps:
    """Calls the tool *steps* times with fresh arguments, then answers."""

    model = "claude-sonnet-4-6"

    def __init__(self, steps: int, *, usage: dict[str, int] | None = None) -> None:
        self.steps = steps
        self.calls = 0
        self.usage = usage

    def complete(self, **_: Any) -> LLMResponse:
        self.calls += 1
        if self.calls > self.steps:
            return LLMResponse(content="Finished.", usage=dict(self.usage or {}))
        return LLMResponse(
            content="",
            tool_calls=[ToolCall(name="lookup", arguments={"query": f"q{self.calls}"})],
            usage=dict(self.usage or {}),
        )


def _agent(llm: Any, **options: Any) -> Agent:
    return Agent(
        llm=llm, tools=[FunctionTool.from_callable(_lookup, name="lookup")], **options
    )


def _summary(result: Any) -> dict[str, Any]:
    return result.metadata["run_summary"]


class TestNoStepLimitByDefault:
    def test_agent_and_runtimes_default_to_none(self) -> None:
        assert _agent(_Steps(0)).max_iterations is None
        assert AgentRuntime(llm=_Steps(0), prompt="p").step_limit is None
        assert AsyncAgentRuntime(llm=_Steps(0), prompt="p").step_limit is None

    def test_a_long_task_runs_to_its_answer(self) -> None:
        llm = _Steps(40)
        result = _agent(llm).run("go")
        assert result.output == "Finished."
        assert llm.calls == 41
        assert _summary(result)["completion_status"] == "finished"

    def test_with_skills_the_default_stays_unlimited(self) -> None:
        agent = _agent(_Steps(0))
        assert agent._effective_max_iterations([object()]) is None


class TestOptInStepLimit:
    def test_a_set_limit_is_respected(self) -> None:
        llm = _Steps(40)
        result = _agent(llm, max_iterations=5).run("go")
        assert llm.calls <= 6
        assert _summary(result)["incomplete_reason"] == "max_iterations"

    def test_the_runtime_reports_its_limit(self) -> None:
        assert AgentRuntime(llm=_Steps(0), prompt="p", max_iterations=7).step_limit == 7


class TestBudget:
    _USAGE = {"prompt_tokens": 100_000, "completion_tokens": 10_000, "total_tokens": 110_000}

    def test_spending_past_the_budget_stops_between_steps(self) -> None:
        llm = _Steps(40, usage=self._USAGE)
        result = _agent(llm, max_budget_usd=1.0).run("go")
        summary = _summary(result)
        assert summary["incomplete_reason"] == "max_budget_usd"
        assert summary["completion_status"] == "incomplete"
        assert 1.0 <= summary["estimated_cost_usd"] < 2.0
        assert "budget" in result.output
        assert llm.calls < 41

    def test_a_budget_not_reached_changes_nothing(self) -> None:
        llm = _Steps(2, usage=self._USAGE)
        result = _agent(llm, max_budget_usd=100.0).run("go")
        assert result.output == "Finished."
        assert _summary(result)["incomplete_reason"] is None

    def test_an_unpriced_model_stops_rather_than_spend_unchecked(self) -> None:
        llm = _Steps(5, usage=self._USAGE)
        llm.model = "a-model-with-no-price"
        result = _agent(llm, max_budget_usd=1.0).run("go")
        assert _summary(result)["incomplete_reason"] == "budget_cost_unavailable"
        assert llm.calls == 1

    @pytest.mark.parametrize("bad", [0, -1.0, "5", True])
    def test_a_budget_must_be_a_positive_number(self, bad: Any) -> None:
        with pytest.raises(ValueError):
            _agent(_Steps(0), max_budget_usd=bad)

    @pytest.mark.parametrize("bad", [0, -3, 2.5, True])
    def test_a_step_limit_must_be_a_positive_integer(self, bad: Any) -> None:
        with pytest.raises(ValueError):
            _agent(_Steps(0), max_iterations=bad)
