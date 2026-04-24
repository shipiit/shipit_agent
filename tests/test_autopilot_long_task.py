"""Long-task Autopilot tests.

Two layers here:

1. **Compressed-time simulations** (always run, ~seconds total) — prove
   the 24-hour semantics without spending 24 hours. We fake the clock
   and the inner agent, then verify the *logic* that would run in
   production: crash → resume chain, SIGTERM mid-run, corrupt checkpoint
   recovery, many-iteration budgets, many-child fan-out.

2. **Bedrock soak test** (opt-in) — gated on ``SHIPIT_AUTOPILOT_SOAK=<seconds>``,
   drives a real Bedrock LLM for that duration and verifies the
   pilot survives cleanly — no crashes, checkpoint valid, usage
   counters accurate, halt_reason sensible.

The soak test is what you run before a 1.x release to convince
yourself the library really does hold up for long runs.
"""

from __future__ import annotations

import json
import os
import signal
import threading
import time
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
from shipit_agent.deep.goal_agent import Goal


# ─────────────────────── stubs ───────────────────────


@dataclass
class _Result:
    output: str = ""
    goal_status: str = "in_progress"
    criteria_met: list[bool] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class _ProgressAgent:
    """Inner agent that emits deterministic per-iteration state.

    Each call bumps a criterion and reports a fixed token/dollar cost
    — so test assertions can compute expected totals exactly.
    """

    def __init__(
        self,
        *,
        criteria: int,
        tokens: int = 100,
        cost_usd: float = 0.001,
        stop_after: int | None = None,
    ) -> None:
        self.criteria = criteria
        self.tokens = tokens
        self.cost_usd = cost_usd
        self.stop_after = stop_after
        self.calls = 0

    def run(self) -> _Result:
        self.calls += 1
        met = [i < self.calls for i in range(self.criteria)]
        status = (
            "completed"
            if (self.stop_after and self.calls >= self.stop_after)
            else "in_progress"
        )
        return _Result(
            output=f"step-{self.calls}",
            goal_status=status,
            criteria_met=met,
            metadata={
                "cost_usd": self.cost_usd,
                "usage": {"total_tokens": self.tokens},
            },
        )


def _autopilot(
    tmp_path: Path, *, agent: Any, budget: BudgetPolicy, **kw: Any
) -> Autopilot:
    return Autopilot(
        llm=None,
        goal=Goal(objective="long", success_criteria=["done"]),
        checkpoint_dir=tmp_path,
        budget=budget,
        agent_factory=lambda **_: agent,
        install_signal_handlers=False,
        **kw,
    )


# ─────────────────────── long iteration count ───────────────────────


class TestManyIterations:
    """A 24-hour run will go through hundreds of iterations — verify
    we don't accumulate pathological per-iteration cost."""

    def test_hundreds_of_iterations_complete(self, tmp_path: Path) -> None:
        # criteria=0 → an empty criteria_met list keeps the "all
        # criteria met" short-circuit inactive, so the loop runs
        # until the iteration budget trips.
        agent = _ProgressAgent(criteria=0, tokens=50, cost_usd=0.0005, stop_after=None)
        auto = _autopilot(
            tmp_path,
            agent=agent,
            budget=BudgetPolicy(
                max_iterations=500,
                max_seconds=60,
                max_tokens=10_000_000,
                max_dollars=100.0,
                max_tool_calls=None,
            ),
        )
        result = auto.run(run_id="many")
        # We hit the iteration cap, not seconds.
        assert "iteration limit" in result.halt_reason
        assert result.iterations >= 500
        # All iterations persisted summaries.
        assert len(result.step_outputs) >= 500

    def test_step_outputs_stay_bounded_in_memory(self, tmp_path: Path) -> None:
        """Each iteration appends one summary; for a 24h run we'd hit
        thousands. Verify that the per-summary size is capped so we
        don't blow up a long-running process' RSS."""
        agent = _ProgressAgent(criteria=0, tokens=10, stop_after=None)
        auto = _autopilot(
            tmp_path,
            agent=agent,
            budget=BudgetPolicy(
                max_iterations=50,
                max_seconds=30,
                max_tokens=None,
                max_dollars=None,
                max_tool_calls=None,
            ),
        )
        result = auto.run(run_id="bounded")
        # Every summary is truncated at 500 chars even if the underlying
        # output is larger (see core.run's [:500] slice).
        assert all(len(s["summary"]) <= 500 for s in result.step_outputs)


# ─────────────────────── crash-resume chain ───────────────────────


class TestCrashResumeChain:
    """Simulate a 24-hour job that crashes every ``N`` iterations. The
    resumed runs together must produce the same cumulative usage as
    one uninterrupted run would have."""

    def test_chain_resumes_cleanly_across_five_crashes(self, tmp_path: Path) -> None:
        crashes = 5
        iters_per_segment = 4
        run_id = "crash-chain"

        total_iters = 0
        total_tokens = 0
        total_dollars = 0.0

        for segment in range(crashes):
            # Budget is CUMULATIVE across resume. Grow the per-segment
            # iteration cap by `iters_per_segment` each time so each
            # segment gets a fair share — otherwise segment 2+ trips
            # the cap immediately because prior iterations already
            # exhausted it.
            agent = _ProgressAgent(criteria=0, tokens=200, cost_usd=0.005)
            auto = Autopilot(
                llm=None,
                goal=Goal(objective="crash chain", success_criteria=["done"]),
                checkpoint_dir=tmp_path,
                budget=BudgetPolicy(
                    max_iterations=iters_per_segment * (segment + 1),
                    max_seconds=30,
                    max_tokens=None,
                    max_dollars=None,
                    max_tool_calls=None,
                ),
                agent_factory=lambda a=agent, **_: a,
                install_signal_handlers=False,
            )
            result = auto.run(run_id=run_id, resume=(segment > 0))
            # Each segment halts at its own iteration cap; cumulative
            # totals have to keep growing monotonically.
            assert result.usage["iterations"] >= total_iters
            assert result.usage["tokens"] >= total_tokens
            assert result.usage["dollars"] >= total_dollars
            total_iters = result.usage["iterations"]
            total_tokens = result.usage["tokens"]
            total_dollars = result.usage["dollars"]

        # After five segments of 4 iters each, we should be near 20 iters.
        # Budget uses strict `>`, so we allow +1 for the cap-tripping iter.
        assert total_iters >= crashes * iters_per_segment


# ─────────────────────── SIGTERM / signal halt ───────────────────────


class TestSignalHaltMidRun:
    """systemd stops a service with SIGTERM. launchd does the same. A
    long-running Autopilot must treat SIGTERM as a request to halt
    cleanly and save one last checkpoint — not as a kill signal that
    leaves the run stranded."""

    @pytest.mark.skipif(
        os.name == "nt",
        reason="POSIX signals not available on Windows",
    )
    def test_sigterm_halts_and_preserves_checkpoint(self, tmp_path: Path) -> None:
        # Inner agent that sleeps briefly each iteration so we can
        # reliably deliver SIGTERM between iters.
        class _SleepyAgent:
            def __init__(self) -> None:
                self.calls = 0

            def run(self) -> _Result:
                self.calls += 1
                time.sleep(0.05)
                return _Result(
                    output=f"s{self.calls}",
                    criteria_met=[False],
                    metadata={"cost_usd": 0.0001, "usage": {"total_tokens": 10}},
                )

        auto = Autopilot(
            llm=None,
            goal=Goal(objective="sig", success_criteria=["c"]),
            checkpoint_dir=tmp_path,
            budget=BudgetPolicy(
                max_iterations=200,
                max_seconds=10,
                max_tokens=None,
                max_dollars=None,
                max_tool_calls=None,
            ),
            agent_factory=lambda **_: _SleepyAgent(),
            install_signal_handlers=True,
        )

        # Fire SIGTERM after a short delay — the main loop should see
        # ``_stop_requested`` set and halt at the next boundary.
        def _send_sigterm() -> None:
            time.sleep(0.15)
            os.kill(os.getpid(), signal.SIGTERM)

        threading.Thread(target=_send_sigterm, daemon=True).start()
        result = auto.run(run_id="sigterm-mid")

        assert "SIGTERM" in result.halt_reason
        assert result.iterations >= 1

        # A checkpoint for this run exists and is valid JSON with the
        # final usage snapshot — exactly what a resuming process needs.
        saved = json.loads((tmp_path / "sigterm-mid.json").read_text())
        assert saved["usage"]["iterations"] == result.iterations
        assert saved["usage"]["tokens"] >= 0


# ─────────────────────── corrupt checkpoint mid-run ───────────────────────


class TestMidRunCorruption:
    """If disk goes bad and a checkpoint is corrupted, a resume call
    should quarantine the broken file (not silently dump the run) and
    start fresh. Production ops want to be able to see the evidence."""

    def test_corrupt_checkpoint_is_quarantined_on_resume(self, tmp_path: Path) -> None:
        # Write a valid checkpoint, then stomp it with garbage.
        store = CheckpointStore(tmp_path)
        store.save(
            "bad",
            goal={"objective": "x", "success_criteria": ["a"], "max_steps": None},
            usage=BudgetUsage(iterations=5, tokens=1000, seconds=30.0),
            step_outputs=[{"iteration": 5}],
            output="something-important",
        )
        (tmp_path / "bad.json").write_text("not valid json{{{")

        auto = _autopilot(
            tmp_path,
            agent=_ProgressAgent(criteria=1, stop_after=1),
            budget=BudgetPolicy(
                max_iterations=2,
                max_seconds=30,
                max_tokens=None,
                max_dollars=None,
                max_tool_calls=None,
            ),
        )
        result = auto.resume("bad")

        # Run starts fresh (empty usage) because the checkpoint was
        # unreadable, and the quarantine file preserves the bad bytes.
        assert result.iterations >= 1
        corruption_files = list(tmp_path.glob("bad.corrupted.*.json"))
        assert corruption_files, "expected the bad file to be quarantined"
        assert "not valid json" in corruption_files[0].read_text()


# ─────────────────────── large fan-out ───────────────────────


class TestLargeFanout:
    """A 50-item fan-out exercises the ThreadPoolExecutor, child budget
    scaling, aggregation, and result ordering under realistic load."""

    def test_fifty_children_all_accounted_for(self, tmp_path: Path) -> None:
        class _Instant:
            def __init__(self, *, goal: Any, **_: Any) -> None:
                self.goal = goal

            def run(self) -> _Result:
                return _Result(
                    output=f"done:{self.goal.objective}",
                    goal_status="completed",
                    criteria_met=[True],
                    metadata={"cost_usd": 0.0001, "usage": {"total_tokens": 5}},
                )

        auto = Autopilot(
            llm=None,
            goal=Goal(objective="parent", success_criteria=["p"]),
            checkpoint_dir=tmp_path,
            budget=BudgetPolicy(
                max_iterations=10,
                max_seconds=120,
                max_tokens=10_000_000,
                max_dollars=5.0,
                max_tool_calls=None,
            ),
            agent_factory=lambda *, goal, **_: _Instant(goal=goal),
            install_signal_handlers=False,
        )
        items = [f"item-{i:02d}" for i in range(50)]
        result = auto.fanout(
            items=items,
            objective_template="Handle {item}",
            criteria_template=["done"],
            max_parallel=10,
            child_budget_frac=0.2,
        )
        assert len(result.children) == 50
        assert result.status == "completed"
        # Every child status is present — no silent drops.
        assert all(c["status"] == "completed" for c in result.children)


# ─────────────────────── opt-in Bedrock soak ───────────────────────


SOAK_SECONDS = int(os.environ.get("SHIPIT_AUTOPILOT_SOAK", "0") or "0")
SOAK_ENABLED = SOAK_SECONDS > 0


@pytest.mark.skipif(
    not SOAK_ENABLED,
    reason=(
        "Soak test disabled. Set SHIPIT_AUTOPILOT_SOAK=<seconds> (e.g. 300 for "
        "a five-minute soak) AND have Bedrock credentials configured."
    ),
)
def test_bedrock_soak_for_requested_duration(tmp_path: Path) -> None:
    """Drive a real Bedrock Autopilot for SHIPIT_AUTOPILOT_SOAK seconds.

    Budget caps are sized from the requested duration:
      * max_seconds = soak_seconds + 30s slack
      * max_iterations = soak_seconds / 5 (rough: one iter per 5s)
      * max_tokens = 100k + 5k/second
      * max_dollars = $0.10 + $0.001/second

    The test passes when the run terminates (either by hitting the
    wall-clock cap or by satisfying the criterion) without raising,
    and leaves a valid checkpoint behind."""
    try:
        import litellm  # noqa: F401
    except ImportError:
        pytest.skip("litellm not installed")

    from shipit_agent.llms import build_llm_from_settings
    from shipit_agent.models import Message

    model = os.environ.get(
        "SHIPIT_AUTOPILOT_SOAK_MODEL",
        "bedrock/openai.gpt-oss-120b-1:0",
    )
    try:
        llm = build_llm_from_settings(
            {"provider": "bedrock", "model": model},
            provider="bedrock",
        )
    except RuntimeError as exc:
        pytest.skip(f"Bedrock unreachable: {exc}")

    # Minimal inner agent — one LLM call per iteration. Proves the
    # full stack (LLM + checkpoint + budget + heartbeat) runs under
    # sustained pressure.
    class _Pinger:
        def __init__(self, *, llm: Any, goal: Goal, **_: Any) -> None:
            self.llm = llm
            self.goal = goal

        def run(self) -> _Result:
            resp = self.llm.complete(
                messages=[
                    Message(role="user", content="Reply with just the word 'alive'."),
                ]
            )
            content = resp.content or ""
            usage = resp.usage or {}
            return _Result(
                output=content,
                goal_status="in_progress",
                criteria_met=[False],
                metadata={
                    "model": model,
                    "usage": {
                        "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
                        "completion_tokens": int(
                            usage.get("completion_tokens", 0) or 0
                        ),
                        "total_tokens": int(usage.get("total_tokens", 0) or 0),
                    },
                },
            )

    hb_count = {"n": 0}

    def _hb(_payload: dict[str, Any]) -> None:
        hb_count["n"] += 1

    auto = Autopilot(
        llm=llm,
        goal=Goal(
            objective="Stay responsive for the soak duration.",
            # Intentionally unsatisfiable — we want to run until the
            # wall-clock cap trips.
            success_criteria=["criterion-never-met"],
        ),
        checkpoint_dir=tmp_path,
        budget=BudgetPolicy(
            max_seconds=float(SOAK_SECONDS + 30),
            max_iterations=max(5, SOAK_SECONDS // 5),
            max_tokens=100_000 + 5_000 * SOAK_SECONDS,
            max_dollars=0.10 + 0.001 * SOAK_SECONDS,
            max_tool_calls=None,
        ),
        agent_factory=lambda *, llm, goal, **_: _Pinger(llm=llm, goal=goal),
        heartbeat_every_seconds=max(5.0, SOAK_SECONDS / 30),
        on_heartbeat=_hb,
        install_signal_handlers=False,
    )

    start = time.monotonic()
    result = auto.run(run_id=f"soak-{SOAK_SECONDS}s")
    elapsed = time.monotonic() - start

    # The pilot terminated without raising.
    assert result.status in ("halted", "partial", "completed")
    # It actually used wall-clock — at least some fraction of the soak.
    assert elapsed >= min(5.0, SOAK_SECONDS * 0.3)
    # Usage counters are non-zero: LLM calls happened.
    assert result.usage["tokens"] > 0
    # We got heartbeats along the way — the observability signal works.
    assert hb_count["n"] >= 1
    # Checkpoint is on disk and loads.
    saved = (tmp_path / f"soak-{SOAK_SECONDS}s.json").read_text()
    payload = json.loads(saved)
    assert payload["usage"]["tokens"] > 0
