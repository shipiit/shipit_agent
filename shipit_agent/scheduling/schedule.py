"""Scheduled agent runs: job definitions, a SQLite job store and the runner that executes due jobs.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from shipit_agent.core.models import AgentEvent

from .config import (
    ScheduledAgentConfig as ScheduledAgentConfig,
)
from .config import (
    ScheduledAgentFactory as ScheduledAgentFactory,
)
from .config import (
    ScheduleResult as ScheduleResult,
)
from .job_store import ScheduledJob as ScheduledJob
from .job_store import SQLiteJobStore as SQLiteJobStore
from .runner import ScheduleRunner as ScheduleRunner


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

    Pass ``store=SQLiteJobStore()`` to make jobs durable: due times and run
    counts persist across restarts, so a re-`add()`ed job resumes its slot
    instead of resetting.
    """

    def __init__(
        self,
        agent: Any = None,
        *,
        agent_resolver: Callable[[ScheduledAgentConfig], Any] | None = None,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
        store: SQLiteJobStore | None = None,
        on_event: Callable[[ScheduledJob, AgentEvent], None] | None = None,
        max_consecutive_failures: int = 5,
    ) -> None:
        self.runner = ScheduleRunner(agent, agent_resolver)
        self.jobs: list[ScheduledJob] = []
        self._clock = clock or time.time
        self._sleep = sleep or time.sleep
        self.store = store
        self.on_event = on_event
        #: Pause a job after this many failures in a row. Generous, because
        #: a provider having a bad afternoon should not retire a working
        #: job; `0` disables the behaviour entirely for a caller who would
        #: rather watch it fail.
        self.max_consecutive_failures = max_consecutive_failures

    def add(
        self,
        prompt: str,
        *,
        every: float | None = None,
        at: str | None = None,
        cron: str | None = None,
        name: str | None = None,
        session_id: str | None = None,
        agent_config: ScheduledAgentConfig | dict[str, Any] | None = None,
        on_result: Callable[[ScheduleResult], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
        max_runs: int | None = None,
    ) -> ScheduledJob:
        job = ScheduledJob(
            name=name or f"job-{len(self.jobs) + 1}",
            prompt=prompt,
            interval_seconds=every,
            at=at,
            cron=cron,
            session_id=session_id,
            agent_config=(
                agent_config
                if isinstance(agent_config, ScheduledAgentConfig)
                else ScheduledAgentConfig.from_dict(agent_config)
            ),
            on_result=on_result,
            on_error=on_error,
            max_runs=max_runs,
        )
        job.next_run = job.compute_next(self._clock())
        if self.store is not None:
            # Durable mode: a job re-added after a restart resumes its
            # persisted slot (next_run / runs) instead of resetting.
            persisted = self.store.load(job.name)
            if persisted is not None:
                job.next_run = persisted.next_run
                job.runs = persisted.runs
                job.enabled = persisted.enabled
                job.consecutive_failures = persisted.consecutive_failures
                job.last_error = persisted.last_error
                job.last_run = persisted.last_run
            self.store.save(job)
        self.jobs.append(job)
        return job

    def run_pending(self, now: float | None = None) -> list[ScheduleResult]:
        """Run every job whose ``next_run`` is due, and reschedule it."""
        moment = now if now is not None else self._clock()
        fired: list[ScheduleResult] = []
        for job in self.jobs:
            if not job.enabled:
                continue
            if job.max_runs is not None and job.runs >= job.max_runs:
                continue
            if moment < job.next_run:
                continue
            job.last_run = moment
            try:
                if job.agent_config.stream_events:
                    result = self.runner.execute_stream_result(
                        job.prompt,
                        session_id=job.session_id,
                        config=job.agent_config,
                        job_name=job.name,
                        on_event=(
                            (lambda event, current=job: self.on_event(current, event))
                            if self.on_event is not None
                            else None
                        ),
                    )
                else:
                    result = self.runner.execute(
                        job.prompt,
                        session_id=job.session_id,
                        config=job.agent_config,
                        job_name=job.name,
                    )
            except Exception as exc:  # one failed provider must not stop the daemon
                job.consecutive_failures += 1
                job.last_error = str(exc)
                # A job whose provider is gone, whose model was deleted, or
                # whose connection was revoked fails identically forever.
                # Counting that and doing nothing means a broken job runs
                # every interval for as long as the daemon lives, burning
                # quota and filling logs with the same line. It is paused
                # rather than deleted: the configuration is intact and
                # `jobs resume` is one command.
                if (self.max_consecutive_failures
                        and job.consecutive_failures
                        >= self.max_consecutive_failures):
                    job.enabled = False
                if job.on_error is not None:
                    try:
                        job.on_error(exc)
                    except Exception:
                        pass
            else:
                job.runs += 1
                job.consecutive_failures = 0
                job.last_error = ""
                if job.on_result is not None:
                    try:
                        job.on_result(result)
                    except Exception:
                        pass
                fired.append(result)
            job.next_run = job.compute_next(moment)
            if self.store is not None:
                self.store.save(job)
        return fired

    def set_enabled(self, name: str, enabled: bool) -> ScheduledJob:
        """Pause or resume a job.

        Resuming clears the failure count: a job somebody fixed and
        resumed would otherwise be paused again by the very next failure,
        because the count that paused it was still there.
        """
        job = next((item for item in self.jobs if item.name == name), None)
        if job is None:
            raise KeyError(f"Unknown scheduled job: {name}")
        job.enabled = enabled
        if enabled:
            job.consecutive_failures = 0
            job.last_error = ""
        if self.store is not None:
            self.store.save(job)
        return job

    def run_forever(
        self, *, tick_seconds: float = 1.0, max_ticks: int | None = None
    ) -> None:
        """Block, firing due jobs every ``tick_seconds`` (until ``max_ticks``)."""
        ticks = 0
        while max_ticks is None or ticks < max_ticks:
            self.run_pending()
            self._sleep(tick_seconds)
            ticks += 1
