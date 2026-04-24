"""Hardening tests — resume cumulativity, dollar tracking, signal stops,
corruption recovery, and pre-iteration budget projection.

These are the guarantees that let an Autopilot survive a 24-hour run:

* Crash at hour 12, resume for hour 13, budget caps measured from hour 0.
* A corrupt checkpoint is quarantined, not silently dropped — so an
  operator can investigate rather than losing state.
* ``SIGTERM`` (systemd / launchd / Docker stop) triggers a clean halt,
  not a killed process that leaves the run stranded.
* Dollar usage accumulates from LLM response metadata, so budget caps
  on ``max_dollars`` actually work instead of always reading ``$0``.
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
    CheckpointStore,
)
from shipit_agent.autopilot.core import _lookup_dollars, _resolve_pricing
from shipit_agent.deep.goal_agent import Goal


# ─────────────────────── stubs ───────────────────────


@dataclass
class _Result:
    output: str = "step"
    goal_status: str = "in_progress"
    criteria_met: list[bool] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class _CountingAgent:
    """Inner agent that counts invocations and returns a preset token/cost shape."""

    def __init__(
        self,
        *,
        criteria: int,
        tokens_per_call: int = 100,
        model: str = "gpt-4o-mini",
        cost_usd: float | None = None,
        stop_after: int | None = None,
    ) -> None:
        self.criteria = criteria
        self.tokens_per_call = tokens_per_call
        self.model = model
        self.cost_usd = cost_usd
        self.stop_after = stop_after
        self.calls = 0

    def run(self) -> _Result:
        self.calls += 1
        met = [i < self.calls for i in range(self.criteria)]
        meta: dict[str, Any] = {
            "model": self.model,
            "usage": {
                "prompt_tokens": self.tokens_per_call // 2,
                "completion_tokens": self.tokens_per_call // 2,
                "total_tokens": self.tokens_per_call,
            },
        }
        if self.cost_usd is not None:
            meta["cost_usd"] = self.cost_usd
        status = (
            "completed"
            if self.stop_after and self.calls >= self.stop_after
            else "in_progress"
        )
        return _Result(
            output=f"step-{self.calls}",
            goal_status=status,
            criteria_met=met,
            metadata=meta,
        )


def _autopilot(
    tmp_path: Path, *, agent: Any, budget: BudgetPolicy | None = None, **kw: Any
) -> Autopilot:
    return Autopilot(
        llm=None,
        goal=Goal(objective="hardening", success_criteria=["a"]),
        checkpoint_dir=tmp_path,
        budget=budget or BudgetPolicy(max_iterations=3, max_seconds=60),
        agent_factory=lambda **_: agent,
        install_signal_handlers=False,  # tests don't own the signal table
        **kw,
    )


# ─────────────────────── checkpoint persistence ───────────────────────


class TestFullUsagePersistence:
    """The checkpoint must carry every field of :class:`BudgetUsage` so
    resume is cumulative across wall-clock, tokens, dollars, and tool
    calls — not just iterations."""

    def test_usage_roundtrips_through_checkpoint(self, tmp_path: Path) -> None:
        store = CheckpointStore(tmp_path)
        store.save(
            "rt",
            goal={"objective": "x", "success_criteria": ["a"], "max_steps": None},
            usage=BudgetUsage(
                seconds=123.4, tool_calls=7, tokens=500, dollars=0.42, iterations=3
            ),
            step_outputs=[{"iteration": 1}],
            output="hello",
        )
        loaded = store.load("rt")
        assert loaded["usage"] == {
            "seconds": 123.4,
            "tool_calls": 7,
            "tokens": 500,
            "dollars": 0.42,
            "iterations": 3,
        }
        restored = CheckpointStore.usage_from_payload(loaded)
        assert restored.seconds == 123.4
        assert restored.dollars == 0.42
        assert restored.tokens == 500
        assert restored.tool_calls == 7
        assert restored.iterations == 3

    def test_v1_checkpoint_still_loads(self, tmp_path: Path) -> None:
        # A checkpoint written by an older Autopilot that only stored
        # ``iterations`` at the top level must still load — users don't
        # restart their runs just because the library upgraded.
        path = tmp_path / "old.json"
        path.write_text(
            json.dumps(
                {
                    "run_id": "old",
                    "goal": {},
                    "iterations": 4,
                    "step_outputs": [],
                    "output": "resumed",
                }
            )
        )
        store = CheckpointStore(tmp_path)
        loaded = store.load("old")
        restored = CheckpointStore.usage_from_payload(loaded)
        assert restored.iterations == 4
        assert restored.dollars == 0.0  # absent field → 0, no crash

    def test_resume_carries_wall_clock_cumulatively(self, tmp_path: Path) -> None:
        """A run that spent 50 seconds should resume with usage.seconds
        starting at 50, not 0 — otherwise a 24-hour cap is trivially
        evaded by crashing and resuming."""
        # Seed the store with a checkpoint pretending 50s + 1000 tokens
        # were already spent.
        store = CheckpointStore(tmp_path)
        store.save(
            "long",
            goal={"objective": "x", "success_criteria": ["a"], "max_steps": None},
            usage=BudgetUsage(seconds=50.0, tokens=1000, iterations=2),
            step_outputs=[],
            output="",
        )
        # Budget of 2s total — with cumulative seconds we trip instantly.
        auto = Autopilot(
            llm=None,
            goal=Goal(objective="x", success_criteria=["a"]),
            checkpoint_dir=tmp_path,
            budget=BudgetPolicy(
                max_seconds=2.0,
                max_iterations=100,
                max_tokens=0,
                max_dollars=0,
                max_tool_calls=0,
            ),
            agent_factory=lambda **_: _CountingAgent(criteria=1),
            install_signal_handlers=False,
        )
        result = auto.resume("long")
        assert "wall-clock" in result.halt_reason
        assert result.usage["seconds"] >= 50.0


# ─────────────────────── corruption recovery ───────────────────────


class TestCorruptionRecovery:
    def test_bad_json_quarantined_not_silently_dropped(self, tmp_path: Path) -> None:
        store = CheckpointStore(tmp_path)
        path = tmp_path / "ruined.json"
        path.write_text("{ this is not json")

        loaded = store.load("ruined")
        assert loaded == {}
        assert not path.exists(), "corrupt file must be moved aside"

        survivors = list(tmp_path.glob("ruined.corrupted.*.json"))
        assert len(survivors) == 1, "exactly one quarantine file expected"
        # The quarantined file preserves the original bytes so an
        # operator can inspect what went wrong.
        assert "this is not json" in survivors[0].read_text()


# ─────────────────────── dollar tracking ───────────────────────


class TestDollarTracking:
    def test_explicit_cost_usd_is_trusted(self, tmp_path: Path) -> None:
        agent = _CountingAgent(criteria=1, cost_usd=0.0123, stop_after=1)
        auto = _autopilot(tmp_path, agent=agent)
        r = auto.run(run_id="cost-1")
        assert r.usage["dollars"] == pytest.approx(0.0123, rel=1e-6)

    def test_pricing_table_lookup_for_known_model(self, tmp_path: Path) -> None:
        agent = _CountingAgent(
            criteria=1,
            tokens_per_call=10_000,
            model="gpt-4o-mini",
            stop_after=1,
        )
        auto = _autopilot(tmp_path, agent=agent)
        r = auto.run(run_id="cost-2")
        # 5k input * $0.15 / 1M + 5k output * $0.60 / 1M = $0.000375 each → $0.00375
        assert 0.001 < r.usage["dollars"] < 0.02

    def test_track_dollars_false_skips_accounting(self, tmp_path: Path) -> None:
        agent = _CountingAgent(criteria=1, cost_usd=1.23, stop_after=1)
        auto = _autopilot(tmp_path, agent=agent, track_dollars=False)
        r = auto.run(run_id="cost-3")
        assert r.usage["dollars"] == 0.0

    def test_resolve_pricing_strips_bedrock_prefix(self) -> None:
        table = {"claude-sonnet-4": {"input": 3.0, "output": 15.0}}
        # Bedrock-style id with provider prefix.
        row = _resolve_pricing("bedrock/anthropic.claude-sonnet-4", table)
        assert row is not None
        assert row["input"] == 3.0

    def test_lookup_dollars_unknown_model_returns_zero(self) -> None:
        assert _lookup_dollars("nope/unknown-model", 1000, 1000) == 0.0


# ─────────────────────── signal handling ───────────────────────


class TestSignalStop:
    def test_request_stop_halts_next_iteration(self, tmp_path: Path) -> None:
        """``request_stop()`` is the thread-safe way daemons and UIs ask
        for a clean halt. It sets a flag; the loop checks it between
        iterations and exits with ``halt_reason`` surfacing the cause."""

        agent = _CountingAgent(criteria=10, stop_after=None)
        auto = _autopilot(
            tmp_path,
            agent=agent,
            budget=BudgetPolicy(max_iterations=100, max_seconds=60),
        )
        # Stopping before the run starts means iteration 1 completes,
        # then the break fires — we never reach iteration 2.
        auto.request_stop("user cancelled")
        r = auto.run(run_id="stop-1")
        assert r.halt_reason == "user cancelled"
        assert r.iterations == 1


# ─────────────────────── heartbeat & progress ───────────────────────


class TestHeartbeatProgress:
    def test_heartbeat_fires_on_first_iteration(self, tmp_path: Path) -> None:
        """A slow first iteration should NOT look like a hang. The run()
        path must emit one heartbeat on iteration 1 even if the regular
        interval hasn't elapsed yet."""
        seen: list[dict[str, Any]] = []
        auto = Autopilot(
            llm=None,
            goal=Goal(objective="x", success_criteria=["a"]),
            checkpoint_dir=tmp_path,
            budget=BudgetPolicy(max_iterations=1, max_seconds=30),
            agent_factory=lambda **_: _CountingAgent(criteria=1, stop_after=1),
            heartbeat_every_seconds=9999,  # effectively disables interval
            on_heartbeat=seen.append,
            install_signal_handlers=False,
        )
        auto.run(run_id="hb-1")
        assert seen, "expected at least one heartbeat on iter 1"
        hb = seen[0]
        assert hb["iteration"] == 1
        assert "remaining" in hb
        assert hb["remaining"]["iterations"] is not None


# ─────────────────────── stream carries remaining ───────────────────────


class TestStreamEnrichment:
    def test_iteration_event_has_remaining(self, tmp_path: Path) -> None:
        auto = Autopilot(
            llm=None,
            goal=Goal(objective="x", success_criteria=["a"]),
            checkpoint_dir=tmp_path,
            budget=BudgetPolicy(max_iterations=3, max_dollars=1.0, max_seconds=60),
            agent_factory=lambda **_: _CountingAgent(criteria=1, stop_after=1),
            install_signal_handlers=False,
        )
        events = list(auto.stream(run_id="str-1"))
        iters = [e for e in events if e["kind"] == "autopilot.iteration"]
        assert iters, "no iteration events yielded"
        # Remaining payload pinpoints the tight axis — useful for UI ETA.
        assert "remaining" in iters[0]
        assert "iterations" in iters[0]["remaining"]


# ─────────────────────── budget projection ───────────────────────


class TestBudgetProjection:
    def test_would_exceed_after_detects_token_overrun(self) -> None:
        policy = BudgetPolicy(max_tokens=10_000)
        usage = BudgetUsage(tokens=9_500)
        exceeded, why = policy.would_exceed_after(usage, extra_tokens=1_000)
        assert exceeded
        assert "token" in why

    def test_remaining_reports_disabled_axes_as_none(self) -> None:
        policy = BudgetPolicy(
            max_seconds=100,
            max_tool_calls=None,
            max_tokens=None,
            max_dollars=None,
            max_iterations=None,
        )
        rem = policy.remaining(BudgetUsage(seconds=25))
        assert rem["seconds"] == 75
        assert rem["tool_calls"] is None
        assert rem["tokens"] is None
        assert rem["dollars"] is None
        assert rem["iterations"] is None
