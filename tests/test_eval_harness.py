from __future__ import annotations

import json

from shipit_agent.evals import SuiteResult, Task, TaskResult, compare, run_task
from shipit_agent.llms.base import LLMResponse
from shipit_agent.models import AgentEvent, ToolResult


class Result:
    output = "grounded answer"
    tool_results = [ToolResult(name="read_file", output="evidence")]
    events = [
        AgentEvent(
            type="run_completed",
            message="complete",
            payload={"usage": {"prompt_tokens": 10, "total_tokens": 15}},
        )
    ]


class FakeAgent:
    def run(self, _prompt):
        return Result()


class Judge:
    def complete(self, **_kwargs):
        return LLMResponse(
            content=json.dumps(
                {
                    "accuracy": 1,
                    "grounding": 1,
                    "completeness": 0.8,
                    "honesty": 1,
                    "efficiency": 0.9,
                    "passed": True,
                    "reason": "grounded",
                }
            )
        )


def test_run_task_records_quality_cost_and_tools() -> None:
    result = run_task(
        lambda: FakeAgent(),
        Task("case", "prompt", "expected", max_tool_calls=0),
        judge_llm=Judge(),
    )
    assert result.passed is True
    assert result.tools_used == ["read_file"]
    assert result.tokens["total_tokens"] == 15
    assert result.over_budget is True
    assert result.mean_score == 0.94


def test_compare_keeps_quality_and_cost_together() -> None:
    def item(label: str, score: float, calls: int, tokens: int) -> SuiteResult:
        return SuiteResult(
            label,
            [
                TaskResult(
                    task_id="case",
                    passed=score >= 0.7,
                    scores={"accuracy": score},
                    output="",
                    duration_s=0,
                    tool_calls=calls,
                    failed_calls=0,
                    tokens={"total_tokens": tokens},
                    tools_used=[],
                    over_budget=False,
                )
            ],
        )

    delta = compare(item("before", 0.5, 4, 100), item("after", 0.8, 2, 80))
    assert delta["pass_rate_delta"] == 1.0
    assert delta["total_tool_call_delta"] == -2
    assert delta["total_token_delta"] == -20


def test_judge_failure_is_reported_without_losing_run_metrics() -> None:
    class BadJudge:
        def complete(self, **_kwargs):
            return LLMResponse(content="not json")

    result = run_task(
        lambda: FakeAgent(),
        Task("case", "prompt", "expected"),
        judge_llm=BadJudge(),
    )
    assert result.passed is False
    assert result.tool_calls == 1
    assert result.reason.startswith("judge failed:")
