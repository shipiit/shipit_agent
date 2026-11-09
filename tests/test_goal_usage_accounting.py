"""A GoalAgent reports the tokens its steps used, so Autopilot's budget can count them.

Before, GoalResult carried no usage and Autopilot's token and dollar meters read
zero for every iteration: ``max_tokens`` and ``max_dollars`` could never trip.
"""

from __future__ import annotations

from typing import Any

from shipit_agent.autopilot import Autopilot, BudgetPolicy
from shipit_agent.deep import Goal, GoalAgent
from shipit_agent.llms import LLMResponse

STEP_USAGE = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}


class UsageLLM:
    """Replies in sequence, each reply billed at STEP_USAGE."""

    model = "claude-haiku-5-5"

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self._index = 0

    def complete(self, **_: Any) -> LLMResponse:
        text = self._responses[min(self._index, len(self._responses) - 1)]
        self._index += 1
        return LLMResponse(content=text, usage=dict(STEP_USAGE))


def _goal_llm() -> UsageLLM:
    return UsageLLM(['{"subtasks": ["one", "two"]}', "first step", '{"criteria_met": [false], "all_done": false}',
                     "second step", '{"criteria_met": [true], "all_done": true}'])


def test_goal_result_carries_the_usage_of_its_steps() -> None:
    result = GoalAgent(llm=_goal_llm(), goal=Goal(objective="x", success_criteria=["done"])).run()
    usage = result.metadata["usage"]
    assert result.steps_taken == 2
    assert usage["total_tokens"] >= 2 * STEP_USAGE["total_tokens"]
    assert usage["prompt_tokens"] + usage["completion_tokens"] == usage["total_tokens"]
    assert result.metadata["model"] == "claude-haiku-5-5"


def test_a_goal_with_no_steps_reports_zero_usage() -> None:
    llm = UsageLLM(['{"subtasks": []}', '{"criteria_met": [], "all_done": true}'])
    result = GoalAgent(llm=llm, goal=Goal(objective="x")).run()
    assert result.metadata["usage"]["total_tokens"] == 0


def test_autopilot_counts_tokens_and_dollars_from_its_goal_agent(tmp_path) -> None:
    autopilot = Autopilot(llm=_goal_llm(), goal=Goal(objective="x", success_criteria=["done"]),
                          checkpoint_dir=tmp_path, install_signal_handlers=False,
                          budget=BudgetPolicy(max_iterations=2))
    result = autopilot.run(run_id="usage")
    assert result.usage["tokens"] > 0
    assert result.usage["dollars"] > 0


def test_a_token_budget_now_halts_the_run(tmp_path) -> None:
    llm = UsageLLM(['{"subtasks": ["one"]}', "step", '{"criteria_met": [false], "all_done": false}'])
    autopilot = Autopilot(llm=llm, goal=Goal(objective="x", success_criteria=["never"]),
                          checkpoint_dir=tmp_path, install_signal_handlers=False,
                          budget=BudgetPolicy(max_iterations=50, max_tokens=150, max_dollars=None))
    result = autopilot.run(run_id="capped")
    assert result.iterations < 50
    assert "token" in (result.halt_reason or "").lower()
