from __future__ import annotations

import datetime as _dt
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

from .models import AgentEvent


@dataclass(slots=True)
class ScheduleResult:
    """Result envelope for a scheduled agent execution."""

    agent_result: Any
    schedule_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ScheduleRunner:
    """Execute an agent or session-backed agent call on behalf of a scheduler."""

    agent: Any

    def execute(self, prompt: str, session_id: str | None = None) -> ScheduleResult:
        if session_id is not None:
            result = self._chat_session(session_id).send(prompt)
        else:
            result = self.agent.run(prompt)

        usage = getattr(result, "metadata", {}).get("usage", {})
        token_count = sum(usage.values()) if isinstance(usage, dict) else 0
        return ScheduleResult(
            agent_result=result,
            schedule_metadata={
                "session_id": session_id,
                "token_count": token_count,
            },
        )

    def execute_stream(
        self,
        prompt: str,
        session_id: str | None = None,
    ) -> Iterator[AgentEvent]:
        if session_id is not None:
            yield from self._chat_session(session_id).stream(prompt)
            return
        yield from self.agent.stream(prompt)

    def _chat_session(self, session_id: str) -> Any:
        try:
            return self.agent.chat_session(session_id=session_id)
        except TypeError:
            return self.agent.chat_session(session_id)


@dataclass
class ScheduledJob:
    """A recurring agent job — a prompt plus when to run it."""

    name: str
    prompt: str
    interval_seconds: float | None = None  # run every N seconds
    at: str | None = None                  # daily at "HH:MM" (local time)
    cron: str | None = None                # cron expression (needs `croniter`)
    session_id: str | None = None          # run inside a persistent chat session
    on_result: Callable[[ScheduleResult], None] | None = None
    max_runs: int | None = None            # stop after this many runs
    runs: int = 0
    next_run: float = 0.0

    def compute_next(self, now: float) -> float:
        if self.interval_seconds:
            return now + float(self.interval_seconds)
        if self.at:
            hour, minute = (int(x) for x in self.at.split(":"))
            base = _dt.datetime.fromtimestamp(now)
            target = base.replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
            if target.timestamp() <= now:
                target += _dt.timedelta(days=1)
            return target.timestamp()
        if self.cron:
            try:
                from croniter import croniter  # optional dependency
            except ImportError as err:
                raise ImportError(
                    "cron schedules need the optional `croniter` package — "
                    "install with `pip install croniter`, or use "
                    "`every=`/`at=` instead."
                ) from err

            return float(
                croniter(self.cron, _dt.datetime.fromtimestamp(now)).get_next(float)
            )
        return now  # no schedule → due immediately (run once)


class AgentScheduler:
    """Run an agent on a recurring schedule — cron jobs for agents.

    Register prompts to run every N seconds, daily at a time, or on a cron
    expression; :meth:`run_forever` fires each when it's due. The ``clock`` /
    ``sleep`` hooks are injectable so schedules are unit-testable without real
    time passing.

        sched = AgentScheduler(agent)
        sched.add("Review today's merged PRs for regressions.", at="09:00")
        sched.add("Summarize new error logs.", every=3600, on_result=notify)
        sched.run_forever()          # blocks, firing jobs as they come due
    """

    def __init__(
        self,
        agent: Any,
        *,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.runner = ScheduleRunner(agent)
        self.jobs: list[ScheduledJob] = []
        self._clock = clock or time.time
        self._sleep = sleep or time.sleep

    def add(
        self,
        prompt: str,
        *,
        every: float | None = None,
        at: str | None = None,
        cron: str | None = None,
        name: str | None = None,
        session_id: str | None = None,
        on_result: Callable[[ScheduleResult], None] | None = None,
        max_runs: int | None = None,
    ) -> ScheduledJob:
        job = ScheduledJob(
            name=name or f"job-{len(self.jobs) + 1}",
            prompt=prompt,
            interval_seconds=every,
            at=at,
            cron=cron,
            session_id=session_id,
            on_result=on_result,
            max_runs=max_runs,
        )
        job.next_run = job.compute_next(self._clock())
        self.jobs.append(job)
        return job

    def run_pending(self, now: float | None = None) -> list[ScheduleResult]:
        """Run every job whose ``next_run`` is due, and reschedule it."""
        moment = now if now is not None else self._clock()
        fired: list[ScheduleResult] = []
        for job in self.jobs:
            if job.max_runs is not None and job.runs >= job.max_runs:
                continue
            if moment < job.next_run:
                continue
            result = self.runner.execute(job.prompt, session_id=job.session_id)
            job.runs += 1
            if job.on_result is not None:
                try:
                    job.on_result(result)
                except Exception:
                    pass
            job.next_run = job.compute_next(moment)
            fired.append(result)
        return fired

    def run_forever(
        self, *, tick_seconds: float = 1.0, max_ticks: int | None = None
    ) -> None:
        """Block, firing due jobs every ``tick_seconds`` (until ``max_ticks``)."""
        ticks = 0
        while max_ticks is None or ticks < max_ticks:
            self.run_pending()
            self._sleep(tick_seconds)
            ticks += 1
