"""Tests for AgentScheduler — recurring/cron-style agent jobs.

Time is injected via a fake clock so schedules fire deterministically with
zero real waiting.
"""

from __future__ import annotations

import datetime as _dt

from shipit_agent.schedule import AgentScheduler, ScheduledJob


class FakeClock:
    """A controllable monotonic clock for deterministic schedule tests."""

    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class RecordingAgent:
    """Minimal agent stand-in that records every prompt it runs."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def run(self, prompt: str):
        self.prompts.append(prompt)
        return type("R", (), {"metadata": {"usage": {"tokens": 3}}})()


def _make(agent=None):
    agent = agent or RecordingAgent()
    clock = FakeClock()
    sched = AgentScheduler(agent, clock=clock, sleep=lambda _s: None)
    return agent, clock, sched


class TestInterval:
    def test_fires_only_when_due(self) -> None:
        agent, clock, sched = _make()
        sched.add("ping", every=60)

        # scheduled 60s out — not due yet
        assert sched.run_pending() == []
        assert agent.prompts == []

        clock.advance(60)
        fired = sched.run_pending()
        assert len(fired) == 1
        assert agent.prompts == ["ping"]

    def test_reschedules_after_firing(self) -> None:
        agent, clock, sched = _make()
        sched.add("ping", every=60)

        clock.advance(60)
        sched.run_pending()
        # immediately after, not due again
        assert sched.run_pending() == []
        clock.advance(60)
        sched.run_pending()
        assert agent.prompts == ["ping", "ping"]

    def test_max_runs_stops_job(self) -> None:
        agent, clock, sched = _make()
        sched.add("ping", every=10, max_runs=2)
        for _ in range(5):
            clock.advance(10)
            sched.run_pending()
        assert agent.prompts == ["ping", "ping"]


class TestDailyAt:
    def test_next_run_is_upcoming_hhmm(self) -> None:
        agent, clock, sched = _make()
        job = sched.add("morning report", at="09:00")
        expected = _dt.datetime.fromtimestamp(job.next_run)
        assert (expected.hour, expected.minute) == (9, 0)
        assert job.next_run > clock.now

    def test_fires_at_the_time_then_next_day(self) -> None:
        agent, clock, sched = _make()
        job = sched.add("morning report", at="09:00")

        clock.now = job.next_run  # jump to 09:00
        fired = sched.run_pending()
        assert len(fired) == 1
        # rescheduled ~24h later
        assert 23 * 3600 <= job.next_run - clock.now <= 25 * 3600


class TestCallbacks:
    def test_on_result_receives_result(self) -> None:
        seen = []
        agent, clock, sched = _make()
        sched.add("ping", every=5, on_result=seen.append)
        clock.advance(5)
        sched.run_pending()
        assert len(seen) == 1
        assert seen[0].schedule_metadata["token_count"] == 3

    def test_callback_error_does_not_break_loop(self) -> None:
        def boom(_r):
            raise RuntimeError("nope")

        agent, clock, sched = _make()
        sched.add("ping", every=5, on_result=boom)
        clock.advance(5)
        # must not raise
        fired = sched.run_pending()
        assert len(fired) == 1


class TestRunForever:
    def test_stops_after_max_ticks(self) -> None:
        agent, clock, sched = _make()

        # advance the clock one interval per tick so the job keeps firing
        def sleep(_s):
            clock.advance(10)

        sched = AgentScheduler(agent, clock=clock, sleep=sleep)
        sched.add("ping", every=10)
        # tick 0 runs before any time passes (job due 10s out → no fire),
        # then each subsequent tick advances 10s and fires once.
        sched.run_forever(tick_seconds=10, max_ticks=4)
        assert len(agent.prompts) == 3


class TestScheduledJobCompute:
    def test_no_schedule_is_immediate(self) -> None:
        job = ScheduledJob(name="once", prompt="hi")
        assert job.compute_next(500.0) == 500.0
