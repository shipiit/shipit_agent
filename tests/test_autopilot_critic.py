"""Tests for the reflection/critic loop + its Autopilot integration."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from shipit_agent.autopilot import (
    Autopilot, BudgetPolicy, Critic, CriticVerdict, AutopilotResult,
)
from shipit_agent.autopilot.critic import inject_suggestions_into_prompt
from shipit_agent.deep.goal_agent import Goal


@dataclass
class _Resp:
    content: str = ""


class _JsonLLM:
    """Stub LLM whose complete() returns a preset string each call."""

    def __init__(self, replies: list[str]) -> None:
        self.replies = replies
        self.calls = 0

    def complete(self, messages: list[Any]) -> _Resp:
        i = min(self.calls, len(self.replies) - 1)
        self.calls += 1
        return _Resp(content=self.replies[i])


# ─────────────────────── Critic unit ───────────────────────


class TestCriticUnit:
    def test_parses_clean_json(self) -> None:
        llm = _JsonLLM([json.dumps({
            "criteria_met": [True, False, True],
            "confidence": 0.8,
            "suggestions": ["do X"],
            "reasoning": "because",
        })])
        c = Critic(llm=llm)
        v = c.review(objective="o", criteria=["a","b","c"], output="...")
        assert v.criteria_met == [True, False, True]
        assert v.confidence == 0.8
        assert v.suggestions == ["do X"]

    def test_pads_short_criteria_to_length(self) -> None:
        llm = _JsonLLM([json.dumps({"criteria_met": [True], "confidence": 0.9})])
        v = Critic(llm=llm).review(objective="o", criteria=["a","b","c"], output="...")
        assert v.criteria_met == [True, False, False]

    def test_trims_long_criteria_to_length(self) -> None:
        llm = _JsonLLM([json.dumps({"criteria_met": [True, True, True, True], "confidence": 0.9})])
        v = Critic(llm=llm).review(objective="o", criteria=["a","b"], output="...")
        assert v.criteria_met == [True, True]

    def test_tolerates_fenced_json(self) -> None:
        fenced = "```json\n" + json.dumps({
            "criteria_met": [True], "confidence": 0.9, "suggestions": [], "reasoning": ""
        }) + "\n```"
        v = Critic(llm=_JsonLLM([fenced])).review(objective="o", criteria=["a"], output="...")
        assert v.criteria_met == [True]

    def test_garbage_returns_zero_confidence_empty_verdict(self) -> None:
        v = Critic(llm=_JsonLLM(["total garbage, no json here"])).review(
            objective="o", criteria=["a","b"], output="..."
        )
        assert v.confidence == 0.0
        assert v.criteria_met == [False, False]

    def test_confidence_clamped_to_unit_interval(self) -> None:
        llm = _JsonLLM([json.dumps({"criteria_met": [True], "confidence": 5.0})])
        v = Critic(llm=llm).review(objective="o", criteria=["a"], output="...")
        assert v.confidence == 1.0

    def test_should_terminate_gate(self) -> None:
        c = Critic(confidence_threshold=0.8)
        assert c.should_terminate(CriticVerdict(criteria_met=[True], confidence=0.9)) is True
        assert c.should_terminate(CriticVerdict(criteria_met=[True], confidence=0.5)) is False
        assert c.should_terminate(CriticVerdict(criteria_met=[False], confidence=1.0)) is False

    def test_max_suggestions_capped(self) -> None:
        llm = _JsonLLM([json.dumps({
            "criteria_met": [False], "confidence": 0.9,
            "suggestions": [f"s{i}" for i in range(50)], "reasoning": "",
        })])
        v = Critic(llm=llm, max_suggestions=3).review(objective="o", criteria=["a"], output="...")
        assert v.suggestions == ["s0", "s1", "s2"]

    def test_llm_exception_returns_skipped_verdict(self) -> None:
        class _Boom:
            def complete(self, messages): raise RuntimeError("down")
        v = Critic(llm=_Boom()).review(objective="o", criteria=["a"], output="...")
        assert v.confidence == 0.0
        assert "skipped" in v.reasoning

    def test_inject_suggestions_into_prompt(self) -> None:
        base = "You are helpful."
        out = inject_suggestions_into_prompt(
            base, CriticVerdict(suggestions=["add tests", "reduce scope"]),
        )
        assert "add tests" in out and "reduce scope" in out
        # No change when there are no suggestions.
        assert inject_suggestions_into_prompt(base, CriticVerdict()) == base


# ─────────────────────── Autopilot integration ───────────────────────


@dataclass
class _FakeResult:
    output: str = "iter-output"
    goal_status: str = "in_progress"
    criteria_met: list[bool] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=lambda: {"usage": {"total_tokens": 10}})


class _ShortAgent:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = outputs
        self.n = 0
    def run(self) -> _FakeResult:
        i = min(self.n, len(self.outputs) - 1)
        self.n += 1
        return _FakeResult(output=self.outputs[i], criteria_met=[False])


class TestAutopilotCriticIntegration:
    def test_critic_confirmation_terminates_early(self, tmp_path: Path) -> None:
        """If the critic confidently says all criteria met, Autopilot stops
        even when the inner agent has NOT itself flipped the flags.

        Note: when the critic flips the criteria_met vector to all-True,
        Autopilot's canonical "all criteria satisfied" break fires FIRST —
        the critic-specific halt path is a safety net for cases where the
        critic is 'should terminate = True' without the vector hitting 1.0.
        Either halt outcome counts as a successful critic short-circuit.
        """
        llm = _JsonLLM([json.dumps({
            "criteria_met": [True, True], "confidence": 0.9,
            "suggestions": [], "reasoning": "looks good",
        })])
        autopilot = Autopilot(
            llm=None,
            goal=Goal(objective="x", success_criteria=["a", "b"]),
            checkpoint_dir=tmp_path,
            budget=BudgetPolicy(max_iterations=10, max_seconds=30),
            agent_factory=lambda **_: _ShortAgent(["hello"]),
            critic=Critic(llm=llm, confidence_threshold=0.8),
        )
        result = autopilot.run(run_id="critic-1")
        assert result.status == "completed"
        assert "satisfied" in result.halt_reason.lower() or "critic" in result.halt_reason.lower()
        # Verdict preserved for downstream consumers.
        assert result.critic_verdict.get("confidence") == 0.9
        # The critic flipped the flags — inner agent returned [False].
        assert result.criteria_met == [True, True]

    def test_low_confidence_does_not_terminate(self, tmp_path: Path) -> None:
        llm = _JsonLLM([json.dumps({
            "criteria_met": [True], "confidence": 0.3,
            "suggestions": ["tighten the wording"], "reasoning": "iffy",
        })])
        autopilot = Autopilot(
            llm=None,
            goal=Goal(objective="x", success_criteria=["a"]),
            checkpoint_dir=tmp_path,
            budget=BudgetPolicy(max_iterations=2, max_seconds=30),
            agent_factory=lambda **_: _ShortAgent(["out1", "out2"]),
            critic=Critic(llm=llm, confidence_threshold=0.8),
        )
        result = autopilot.run(run_id="critic-2")
        assert result.iterations >= 2
        assert "critic" not in result.halt_reason.lower()

    def test_stream_emits_critic_events(self, tmp_path: Path) -> None:
        llm = _JsonLLM([json.dumps({
            "criteria_met": [True], "confidence": 0.9,
            "suggestions": [], "reasoning": "",
        })])
        autopilot = Autopilot(
            llm=None,
            goal=Goal(objective="x", success_criteria=["a"]),
            checkpoint_dir=tmp_path,
            budget=BudgetPolicy(max_iterations=3, max_seconds=30),
            agent_factory=lambda **_: _ShortAgent(["out"]),
            critic=Critic(llm=llm),
        )
        events = list(autopilot.stream(run_id="critic-3"))
        kinds = [e["kind"] for e in events]
        assert "autopilot.critic" in kinds

    def test_critic_eq_true_builds_default(self, tmp_path: Path) -> None:
        """When `critic=True` but no LLM is reachable, the default critic is
        a no-op that returns zero-confidence verdicts — run halts on the
        iteration budget rather than on critic confirmation."""
        autopilot = Autopilot(
            llm=None,
            goal=Goal(objective="x", success_criteria=["a"]),
            checkpoint_dir=tmp_path,
            budget=BudgetPolicy(max_iterations=1, max_seconds=30),
            agent_factory=lambda **_: _ShortAgent(["out"]),
            critic=True,
        )
        assert isinstance(autopilot.critic, Critic)
        result = autopilot.run(run_id="critic-4")
        # BudgetPolicy uses strict `>`: `max_iterations=1` allows exactly
        # one completed iteration; usage.iterations reads 2 when the cap
        # trips. We care that the run halted for the budget, not the critic.
        assert "iteration" in result.halt_reason
        assert result.critic_verdict.get("confidence", 0.0) == 0.0
