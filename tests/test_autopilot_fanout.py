"""Tests for Autopilot.fanout() and Autopilot.fanout_stream()."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


from shipit_agent.autopilot import (
    Autopilot,
    AutopilotResult,
    BudgetPolicy,
)
from shipit_agent.autopilot.fanout import _rollup_status, _scale_budget, _slug
from shipit_agent.deep.goal_agent import Goal


@dataclass
class _FakeResult:
    output: str = "child-output"
    goal_status: str = "completed"
    criteria_met: list[bool] = field(default_factory=lambda: [True])
    metadata: dict[str, Any] = field(
        default_factory=lambda: {"usage": {"total_tokens": 5}}
    )


class _TinyAgent:
    """Inner agent that always succeeds and records the objective it saw."""

    _seen: list[str] = []

    def __init__(self, *, goal: Any, **_: Any) -> None:
        self.goal = goal
        _TinyAgent._seen.append(goal.objective)

    def run(self) -> _FakeResult:
        return _FakeResult(output=f"done:{self.goal.objective}")


class _FlakyAgent:
    def __init__(self, *, goal: Any, **_: Any) -> None:
        self.goal = goal

    def run(self) -> _FakeResult:
        if "fail" in self.goal.objective:
            raise RuntimeError("simulated")
        return _FakeResult(output=f"ok:{self.goal.objective}")


# ─────────────────────── helpers ───────────────────────


class TestHelpers:
    def test_slug_cleans_paths(self) -> None:
        assert _slug("PR 123 Review!") == "pr-123-review"
        assert _slug("../etc/passwd") == "etc-passwd"
        assert _slug("") == "item"

    def test_scale_budget_halves(self) -> None:
        parent = BudgetPolicy(
            max_seconds=1000,
            max_tool_calls=100,
            max_tokens=10_000,
            max_dollars=10.0,
            max_iterations=20,
        )
        child = _scale_budget(parent, 0.5)
        assert child.max_seconds == 500
        assert child.max_tool_calls == 50
        assert child.max_tokens == 5_000
        assert child.max_dollars == 5.0
        assert child.max_iterations == 10

    def test_scale_budget_preserves_none(self) -> None:
        parent = BudgetPolicy(
            max_seconds=None,
            max_tool_calls=None,
            max_tokens=None,
            max_dollars=None,
            max_iterations=None,
        )
        child = _scale_budget(parent, 0.5)
        assert child.max_seconds is None
        assert child.max_tool_calls is None

    def test_scale_budget_floor_enforced(self) -> None:
        parent = BudgetPolicy(max_tool_calls=1)
        child = _scale_budget(parent, 0.01)
        # Even a 1% scale can't go below 1 tool call.
        assert child.max_tool_calls == 1

    def test_scale_budget_frac_clamped(self) -> None:
        parent = BudgetPolicy(max_seconds=100)
        # Below 0.05 gets raised; above 1.0 gets capped.
        assert _scale_budget(parent, 0.0).max_seconds == 5.0
        assert _scale_budget(parent, 2.0).max_seconds == 100.0

    def test_rollup_status(self) -> None:
        assert _rollup_status([]) == "completed"
        assert _rollup_status(["completed", "completed"]) == "completed"
        assert _rollup_status(["failed", "failed"]) == "failed"
        assert _rollup_status(["completed", "partial"]) == "partial"
        assert _rollup_status(["completed", "failed"]) == "partial"


# ─────────────────────── fanout() ───────────────────────


def _make_parent(tmp_path: Path, *, agent_cls: type = _TinyAgent) -> Autopilot:
    return Autopilot(
        llm=None,
        goal=Goal(objective="parent", success_criteria=["p"]),
        checkpoint_dir=tmp_path,
        budget=BudgetPolicy(max_iterations=5, max_seconds=60),
        agent_factory=lambda *, goal, **kw: agent_cls(goal=goal, **kw),
    )


class TestFanoutSync:
    def setup_method(self) -> None:
        _TinyAgent._seen = []

    def test_empty_items_returns_completed_immediately(self, tmp_path: Path) -> None:
        autopilot = _make_parent(tmp_path)
        r = autopilot.fanout(items=[], objective_template="t {item}")
        assert r.status == "completed"
        assert r.children == []
        assert r.aggregated_output.startswith("(no items)")

    def test_each_child_sees_templated_objective(self, tmp_path: Path) -> None:
        autopilot = _make_parent(tmp_path)
        items = ["alpha", "beta", "gamma"]
        r = autopilot.fanout(
            items=items,
            objective_template="Review {item}",
            criteria_template=["done"],
            max_parallel=3,
        )
        # Order of _seen isn't deterministic (thread pool), so compare as sets.
        assert set(_TinyAgent._seen) == {f"Review {i}" for i in items}
        assert r.status == "completed"
        assert len(r.children) == 3

    def test_children_output_order_preserved_by_run_id(self, tmp_path: Path) -> None:
        autopilot = _make_parent(tmp_path)
        items = [f"case-{i}" for i in range(4)]
        r = autopilot.fanout(items=items, objective_template="handle {item}")
        run_ids = [c["run_id"] for c in r.children]
        # Sorted by run_id which embeds idx — output order is stable.
        assert run_ids == sorted(run_ids)

    def test_failed_child_recorded(self, tmp_path: Path) -> None:
        autopilot = _make_parent(tmp_path, agent_cls=_FlakyAgent)
        r = autopilot.fanout(
            items=["ok", "fail-1"],
            objective_template="handle {item}",
            max_parallel=2,
        )
        assert any(c["status"] == "failed" for c in r.children)
        # r.failed is a list of run_id strings (not dicts).
        assert any("fail" in rid for rid in r.failed)

    def test_custom_aggregator(self, tmp_path: Path) -> None:
        autopilot = _make_parent(tmp_path)

        def joiner(children: list[AutopilotResult]) -> str:
            return " | ".join(c.output for c in children)

        r = autopilot.fanout(
            items=["x", "y"],
            objective_template="Do {item}",
            aggregator=joiner,
        )
        assert r.aggregated_output.count("done:") == 2


class TestFanoutStream:
    def setup_method(self) -> None:
        _TinyAgent._seen = []

    def test_emits_started_and_result(self, tmp_path: Path) -> None:
        autopilot = _make_parent(tmp_path)
        events = list(
            autopilot.fanout_stream(
                items=["a", "b"],
                objective_template="t {item}",
                max_parallel=2,
            )
        )
        kinds = [e["kind"] for e in events]
        assert kinds[0] == "autopilot.fanout_started"
        assert kinds[-1] == "autopilot.fanout_result"
        assert kinds.count("autopilot.fanout_child") == 2

    def test_empty_items_still_emits_result(self, tmp_path: Path) -> None:
        autopilot = _make_parent(tmp_path)
        events = list(autopilot.fanout_stream(items=[], objective_template="t {item}"))
        assert events[0]["kind"] == "autopilot.fanout_started"
        assert events[-1]["kind"] == "autopilot.fanout_result"
        assert events[-1]["status"] == "completed"
