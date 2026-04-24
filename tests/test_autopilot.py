"""Tests for the Autopilot / BudgetPolicy / SchedulerDaemon stack.

These tests deliberately don't hit a real LLM. They use a stub inner
agent whose `run()` returns a fake GoalResult, so we can verify the
Autopilot's orchestration behavior — budgets, termination, checkpoints,
streaming events — in milliseconds with no network.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from shipit_agent.autopilot import (
    Autopilot,
    BudgetPolicy,
    BudgetUsage,
    coerce_event,
)
from shipit_agent.deep.goal_agent import Goal
from shipit_agent.scheduler_daemon import SchedulerDaemon
from shipit_agent.live_renderer import render_stream


# ─────────────────────── stubs ───────────────────────


@dataclass
class FakeResult:
    output: str = "done"
    goal_status: str = "unknown"
    criteria_met: list[bool] = field(default_factory=list)
    metadata: dict[str, Any] = field(
        default_factory=lambda: {"usage": {"total_tokens": 50}}
    )


class StubAgent:
    """An inner agent that satisfies one more criterion each call."""

    def __init__(self, *, criteria: int, complete_on: int = -1) -> None:
        self.criteria = criteria
        self.calls = 0
        self.complete_on = (
            complete_on  # iteration (1-based) when it flips to "completed"
        )

    def run(self) -> FakeResult:
        self.calls += 1
        met = [i < self.calls for i in range(self.criteria)]
        status = "completed" if self.calls == self.complete_on else "in_progress"
        return FakeResult(
            output=f"step {self.calls}",
            goal_status=status,
            criteria_met=met,
        )


class StubFactory:
    """Reusable factory so Autopilot builds a fresh StubAgent each iter."""

    def __init__(self, *, criteria: int) -> None:
        self.shared = StubAgent(criteria=criteria)

    def __call__(self, **kwargs: Any) -> StubAgent:
        return self.shared


# ─────────────────────── budget ───────────────────────


class TestBudgetPolicy:
    def test_defaults_are_conservative(self) -> None:
        # Defaults should NOT let a runaway exceed an overnight run without
        # opting in. Anything looser is a foot-gun.
        b = BudgetPolicy()
        assert b.max_seconds and b.max_seconds <= 3600
        assert b.max_tool_calls and b.max_tool_calls <= 500
        assert b.max_dollars and b.max_dollars <= 20

    def test_each_axis_trips_independently(self) -> None:
        b = BudgetPolicy(
            max_seconds=10,
            max_tool_calls=5,
            max_tokens=100,
            max_dollars=1.0,
            max_iterations=3,
        )
        assert b.exceeded(BudgetUsage(seconds=1)) == (False, "")
        ok, why = b.exceeded(BudgetUsage(seconds=11))
        assert ok and "wall-clock" in why
        ok, why = b.exceeded(BudgetUsage(tool_calls=6))
        assert ok and "tool-call" in why
        ok, why = b.exceeded(BudgetUsage(tokens=200))
        assert ok and "token" in why
        ok, why = b.exceeded(BudgetUsage(dollars=2.0))
        assert ok and "dollar" in why
        ok, why = b.exceeded(BudgetUsage(iterations=5))
        assert ok and "iteration" in why

    def test_none_disables_axis(self) -> None:
        b = BudgetPolicy(
            max_seconds=None,
            max_tool_calls=None,
            max_tokens=None,
            max_dollars=None,
            max_iterations=None,
        )
        assert b.exceeded(BudgetUsage(seconds=10_000, tool_calls=5000)) == (False, "")


# ─────────────────────── autopilot.run ───────────────────────


class TestAutopilotRun:
    def test_completes_when_all_criteria_met(self, tmp_path: Path) -> None:
        goal = Goal(objective="Do thing", success_criteria=["c1", "c2", "c3"])
        factory = StubFactory(criteria=3)
        a = Autopilot(
            llm=None,
            goal=goal,
            checkpoint_dir=tmp_path,
            budget=BudgetPolicy(max_iterations=10, max_seconds=30),
            agent_factory=factory,
        )
        r = a.run(run_id="r1")
        assert r.status == "completed"
        assert r.criteria_met == [True, True, True]
        assert r.iterations >= 3

    def test_halts_on_iteration_budget(self, tmp_path: Path) -> None:
        goal = Goal(objective="x", success_criteria=["c1", "c2", "c3"])
        factory = StubFactory(criteria=3)
        a = Autopilot(
            llm=None,
            goal=goal,
            checkpoint_dir=tmp_path,
            budget=BudgetPolicy(max_iterations=2, max_seconds=30),
            agent_factory=factory,
        )
        r = a.run(run_id="r-halt")
        assert r.status in ("partial", "halted")
        assert "iteration limit" in r.halt_reason

    def test_refuses_to_overwrite_existing_checkpoint(self, tmp_path: Path) -> None:
        goal = Goal(objective="x", success_criteria=["c1"])
        a = Autopilot(
            llm=None,
            goal=goal,
            checkpoint_dir=tmp_path,
            agent_factory=StubFactory(criteria=1),
            budget=BudgetPolicy(max_iterations=5),
        )
        a.run(run_id="dup")
        with pytest.raises(FileExistsError):
            a.run(run_id="dup")

    def test_resume_picks_up_iteration_count(self, tmp_path: Path) -> None:
        goal = Goal(objective="x", success_criteria=["c1", "c2"])
        a = Autopilot(
            llm=None,
            goal=goal,
            checkpoint_dir=tmp_path,
            agent_factory=StubFactory(criteria=2),
            budget=BudgetPolicy(max_iterations=1),
        )
        first = a.run(run_id="resumable")
        # 2 criteria, but max_iterations=1 → we expect partial
        assert first.status in ("partial", "halted")
        assert first.iterations >= 1

        a2 = Autopilot(
            llm=None,
            goal=goal,
            checkpoint_dir=tmp_path,
            agent_factory=StubFactory(criteria=2),
            budget=BudgetPolicy(max_iterations=5),
        )
        second = a2.resume("resumable")
        assert second.iterations > first.iterations

    def test_inner_completion_short_circuits(self, tmp_path: Path) -> None:
        goal = Goal(objective="x", success_criteria=["c1", "c2", "c3"])
        factory = StubFactory(criteria=3)
        factory.shared.complete_on = 1
        a = Autopilot(
            llm=None,
            goal=goal,
            checkpoint_dir=tmp_path,
            agent_factory=factory,
            budget=BudgetPolicy(max_iterations=10),
        )
        r = a.run(run_id="short")
        assert r.iterations == 1
        assert "completion" in r.halt_reason

    def test_exception_sets_failed_status(self, tmp_path: Path) -> None:
        class Boom:
            def run(self):
                raise RuntimeError("boom")

        goal = Goal(objective="x", success_criteria=["c1"])
        a = Autopilot(
            llm=None,
            goal=goal,
            checkpoint_dir=tmp_path,
            agent_factory=lambda **_: Boom(),
            budget=BudgetPolicy(max_iterations=3),
        )
        r = a.run(run_id="fail")
        assert r.status == "failed"
        assert "RuntimeError" in r.halt_reason


# ─────────────────────── autopilot.stream ───────────────────────


class TestAutopilotStream:
    def test_stream_yields_events_until_result(self, tmp_path: Path) -> None:
        goal = Goal(objective="x", success_criteria=["c1", "c2"])
        a = Autopilot(
            llm=None,
            goal=goal,
            checkpoint_dir=tmp_path,
            agent_factory=StubFactory(criteria=2),
            budget=BudgetPolicy(max_iterations=5),
        )
        events = list(a.stream(run_id="s1"))
        kinds = [e["kind"] for e in events]
        assert kinds[0] == "autopilot.run_started"
        assert kinds[-1] == "autopilot.result"
        assert "autopilot.iteration" in kinds

    def test_stream_emits_budget_exceeded(self, tmp_path: Path) -> None:
        goal = Goal(objective="x", success_criteria=["c1", "c2", "c3"])
        a = Autopilot(
            llm=None,
            goal=goal,
            checkpoint_dir=tmp_path,
            agent_factory=StubFactory(criteria=3),
            budget=BudgetPolicy(max_iterations=1),
        )
        events = list(a.stream(run_id="s2"))
        kinds = [e["kind"] for e in events]
        assert "autopilot.budget_exceeded" in kinds

    def test_result_event_carries_status_and_usage(self, tmp_path: Path) -> None:
        goal = Goal(objective="x", success_criteria=["c1"])
        a = Autopilot(
            llm=None,
            goal=goal,
            checkpoint_dir=tmp_path,
            agent_factory=StubFactory(criteria=1),
            budget=BudgetPolicy(max_iterations=5),
        )
        events = list(a.stream(run_id="s3"))
        final = events[-1]
        assert final["status"] == "completed"
        assert "usage" in final


# ─────────────────────── coerce_event ───────────────────────


class TestEventCoercion:
    def test_passes_through_dict(self) -> None:
        ev = coerce_event({"kind": "x", "value": 1})
        assert ev == {"kind": "x", "value": 1}

    def test_infers_kind_for_dict_without_one(self) -> None:
        ev = coerce_event({"value": 1}, kind_hint="autopilot.hint")
        assert ev == {"kind": "autopilot.hint", "value": 1}

    def test_wraps_agent_event_shape(self) -> None:
        class E:
            type = "tool_called"
            message = "bash"
            payload = {"cmd": "ls"}

        ev = coerce_event(E())
        assert ev["kind"] == "autopilot.tool_called"
        assert ev["payload"] == {"cmd": "ls"}


# ─────────────────────── checkpoint ───────────────────────


class TestCheckpointSafety:
    def test_atomic_save_on_crash(self, tmp_path: Path) -> None:
        # Autopilot should save a checkpoint before the exception propagates,
        # so a subsequent resume sees the partial state.
        call_count = {"n": 0}

        class Flaky:
            def run(self):
                call_count["n"] += 1
                if call_count["n"] == 2:
                    raise RuntimeError("simulated crash")
                return FakeResult(criteria_met=[True, False])

        goal = Goal(objective="x", success_criteria=["c1", "c2"])
        a = Autopilot(
            llm=None,
            goal=goal,
            checkpoint_dir=tmp_path,
            agent_factory=lambda **_: Flaky(),
            budget=BudgetPolicy(max_iterations=10),
        )
        r = a.run(run_id="flaky")
        assert r.status == "failed"

        cp = tmp_path / "flaky.json"
        assert cp.exists()
        loaded = json.loads(cp.read_text())
        assert loaded["iterations"] >= 1


# ─────────────────────── scheduler daemon ───────────────────────


class TestSchedulerDaemon:
    def test_enqueue_list_remove_roundtrip(self, tmp_path: Path) -> None:
        q = tmp_path / "queue.json"
        d = SchedulerDaemon(llm_factory=lambda: None, queue_path=q)
        d.enqueue(run_id="j1", objective="do x", success_criteria=["a", "b"])
        d.enqueue(run_id="j2", objective="do y")
        assert {e.run_id for e in d.list_queue()} == {"j1", "j2"}
        assert d.remove("j1") is True
        assert {e.run_id for e in d.list_queue()} == {"j2"}

    def test_duplicate_run_id_rejected(self, tmp_path: Path) -> None:
        q = tmp_path / "queue.json"
        d = SchedulerDaemon(llm_factory=lambda: None, queue_path=q)
        d.enqueue(run_id="dup", objective="x")
        with pytest.raises(ValueError):
            d.enqueue(run_id="dup", objective="x again")

    def test_run_once_returns_none_when_empty(self, tmp_path: Path) -> None:
        d = SchedulerDaemon(llm_factory=lambda: None, queue_path=tmp_path / "q.json")
        assert d.run_once() is None


# ─────────────────────── live renderer ───────────────────────


class TestLiveRenderer:
    def test_plain_render_captures_iteration_and_result(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        events = [
            {
                "kind": "autopilot.run_started",
                "run_id": "r",
                "goal": {"objective": "o"},
            },
            {
                "kind": "autopilot.iteration",
                "iteration": 1,
                "criteria_met": [True],
                "usage": {"seconds": 2, "tool_calls": 3, "tokens": 100},
                "summary": "ok",
            },
            {
                "kind": "autopilot.result",
                "status": "completed",
                "iterations": 1,
                "usage": {"seconds": 2, "tool_calls": 3, "tokens": 100},
            },
        ]
        result = render_stream(events, fmt="plain")
        out = capsys.readouterr().out
        assert "Autopilot" in out
        assert "iter 1" in out
        assert "COMPLETED" in out
        assert result and result["status"] == "completed"

    def test_jsonl_round_trip(self, capsys: pytest.CaptureFixture) -> None:
        events = [{"kind": "autopilot.run_started", "run_id": "r"}]
        render_stream(events, fmt="jsonl")
        out = capsys.readouterr().out.strip()
        assert json.loads(out) == {"kind": "autopilot.run_started", "run_id": "r"}


# ─────────────────────── specialist agents ───────────────────────


class TestSpecialistRoster:
    def test_seven_new_specialist_ids_present(self) -> None:
        from shipit_agent.agents import _specialists_patch  # noqa: F401

        data = json.loads(
            (
                Path(__file__).parent.parent / "shipit_agent" / "agents" / "agents.json"
            ).read_text()
        )
        ids = {a["id"] for a in data}
        for expected in [
            "generalist-developer",
            "debugger",
            "design-reviewer",
            "product-manager",
            "sales-outreach",
            "customer-success",
            "marketing-writer",
        ]:
            assert expected in ids, f"specialist {expected} missing from agents.json"

    def test_patch_is_idempotent(self) -> None:
        from shipit_agent.agents._specialists_patch import apply_patch

        assert apply_patch() == 0  # second invocation adds nothing
