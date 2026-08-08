from __future__ import annotations

import datetime as _dt
import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

from .models import AgentEvent, AgentResult


@dataclass(slots=True)
class ScheduleResult:
    """Result envelope for a scheduled agent execution."""

    agent_result: Any
    schedule_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ScheduledAgentConfig:
    """Serializable agent/runtime selection for one scheduled job."""

    provider: str | None = None
    model: str | None = None
    role: str | None = None
    project_root: str | None = None
    runtime: str = "project"  # project | builtins | role
    optimized: bool = True
    permission_mode: str = "default"
    guardrails: str | None = "standard"
    mcps: list[str] = field(default_factory=list)
    connections: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    auto_use_skills: bool = True
    max_iterations: int | None = None
    stream_events: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if self.runtime not in {"project", "builtins", "role"}:
            raise ValueError("runtime must be project, builtins, or role")
        if self.permission_mode not in {"default", "acceptEdits", "plan", "bypass"}:
            raise ValueError(
                "permission_mode must be default, acceptEdits, plan, or bypass"
            )
        if self.guardrails not in {None, "standard", "strict"}:
            raise ValueError("guardrails must be standard, strict, or None")
        if self.runtime == "role" and not self.role:
            raise ValueError("role runtime requires a role")
        if self.max_iterations is not None and self.max_iterations < 1:
            raise ValueError("max_iterations must be positive")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "provider": self.provider,
            "model": self.model,
            "role": self.role,
            "project_root": self.project_root,
            "runtime": self.runtime,
            "optimized": self.optimized,
            "permission_mode": self.permission_mode,
            "guardrails": self.guardrails,
            "mcps": list(self.mcps),
            "connections": list(self.connections),
            "skills": list(self.skills),
            "auto_use_skills": self.auto_use_skills,
            "max_iterations": self.max_iterations,
            "stream_events": self.stream_events,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "ScheduledAgentConfig":
        raw = dict(value or {})
        known = {field.name for field in cls.__dataclass_fields__.values()}
        config = cls(**{key: item for key, item in raw.items() if key in known})
        config.mcps = [str(name) for name in config.mcps]
        config.connections = [str(name) for name in config.connections]
        config.skills = [str(name) for name in config.skills]
        config.metadata = dict(config.metadata or {})
        config.validate()
        return config


@dataclass(slots=True)
class ScheduledAgentFactory:
    """Build isolated agents from persisted scheduled-job configuration."""

    llm_factory: Callable[[str | None, str | None], Any]
    mcp_factory: Callable[[str], Any] | None = None
    default_provider: str | None = None
    default_model: str | None = None
    default_project_root: str | None = None
    default_mcps: list[str] = field(default_factory=list)
    credential_store: Any = None

    def __call__(self, config: ScheduledAgentConfig) -> Any:
        from pathlib import Path

        from shipit_agent import Agent, Guardrails, connect_mcp

        config.validate()
        provider = config.provider or self.default_provider
        model = config.model or self.default_model
        project_root = (
            config.project_root or self.default_project_root or str(Path.cwd())
        )
        llm = self.llm_factory(provider, model)

        guardrails = None
        if config.guardrails == "strict":
            guardrails = Guardrails.strict()
        elif config.guardrails == "standard":
            guardrails = Guardrails.standard()

        attach_mcp = self.mcp_factory or connect_mcp
        mcp_names = config.mcps or self.default_mcps
        common: dict[str, Any] = {
            "guardrails": guardrails,
            "mcps": [attach_mcp(name) for name in mcp_names],
            "permission_mode": config.permission_mode,
            "default_skill_ids": list(config.skills),
            "auto_use_skills": config.auto_use_skills,
            "metadata": {
                **dict(config.metadata),
                "scheduled": True,
                "required_connections": list(config.connections),
            },
        }
        if self.credential_store is not None:
            common["credential_store"] = self.credential_store
        if config.max_iterations is not None:
            common["max_iterations"] = config.max_iterations

        if config.runtime == "role":
            return Agent.for_role(
                config.role or "",
                llm=llm,
                project_root=project_root,
                **common,
            )
        if config.runtime == "builtins":
            return Agent.with_builtins(
                llm=llm,
                project_root=project_root,
                optimized=config.optimized,
                **common,
            )
        return Agent.for_project(
            llm=llm,
            project_root=project_root,
            optimized=config.optimized,
            **common,
        )


@dataclass(slots=True)
class ScheduleRunner:
    """Execute an agent or session-backed agent call on behalf of a scheduler."""

    agent: Any = None
    agent_resolver: Callable[[ScheduledAgentConfig], Any] | None = None

    def execute(
        self,
        prompt: str,
        session_id: str | None = None,
        *,
        config: ScheduledAgentConfig | None = None,
        job_name: str | None = None,
    ) -> ScheduleResult:
        selected = config or ScheduledAgentConfig()
        agent = self._resolve_agent(selected)
        if session_id is not None:
            result = self._chat_session(agent, session_id).send(prompt)
        else:
            result = agent.run(prompt)

        usage = self._usage(result)
        token_count = int(usage.get("total_tokens", 0) or 0)
        if token_count <= 0:
            token_count = int(usage.get("prompt_tokens", 0) or 0) + int(
                usage.get("completion_tokens", 0) or 0
            )
        if token_count <= 0:
            token_count = sum(
                int(value) for value in usage.values() if isinstance(value, int | float)
            )
        return ScheduleResult(
            agent_result=result,
            schedule_metadata={
                "job_name": job_name,
                "session_id": session_id,
                "token_count": token_count,
                "usage": usage,
                "agent_config": selected.to_dict(),
            },
        )

    def execute_stream(
        self,
        prompt: str,
        session_id: str | None = None,
        *,
        config: ScheduledAgentConfig | None = None,
    ) -> Iterator[AgentEvent]:
        agent = self._resolve_agent(config or ScheduledAgentConfig())
        if session_id is not None:
            yield from self._chat_session(agent, session_id).stream(prompt)
            return
        yield from agent.stream(prompt)

    def execute_stream_result(
        self,
        prompt: str,
        session_id: str | None = None,
        *,
        config: ScheduledAgentConfig | None = None,
        job_name: str | None = None,
        on_event: Callable[[AgentEvent], None] | None = None,
    ) -> ScheduleResult:
        """Consume a live run while preserving its events and final output."""
        selected = config or ScheduledAgentConfig()
        events: list[AgentEvent] = []
        for event in self.execute_stream(
            prompt,
            session_id=session_id,
            config=selected,
        ):
            events.append(event)
            if on_event is not None:
                try:
                    on_event(event)
                except Exception:
                    # Observability must not turn a successful agent run into
                    # a failed scheduled job.
                    pass

        completed = next(
            (event for event in reversed(events) if event.type == "run_completed"),
            None,
        )
        payload = completed.payload if completed is not None else {}
        usage = dict(payload.get("usage", {}))
        output = str(payload.get("output") or payload.get("content") or "")
        token_count = int(usage.get("total_tokens", 0) or 0)
        if token_count <= 0:
            token_count = int(usage.get("prompt_tokens", 0) or 0) + int(
                usage.get("completion_tokens", 0) or 0
            )
        result = AgentResult(
            output=output,
            messages=[],
            events=events,
            metadata={"usage": usage},
        )
        return ScheduleResult(
            agent_result=result,
            schedule_metadata={
                "job_name": job_name,
                "session_id": session_id,
                "token_count": token_count,
                "usage": usage,
                "agent_config": selected.to_dict(),
                "streamed": True,
            },
        )

    def _resolve_agent(self, config: ScheduledAgentConfig) -> Any:
        config.validate()
        if self.agent_resolver is not None:
            return self.agent_resolver(config)
        if self.agent is None:
            raise RuntimeError("scheduled job has no agent or agent_resolver")
        return self.agent

    @staticmethod
    def _usage(result: Any) -> dict[str, Any]:
        metadata_usage = getattr(result, "metadata", {}).get("usage", {})
        if isinstance(metadata_usage, dict) and metadata_usage:
            return dict(metadata_usage)
        for event in reversed(list(getattr(result, "events", []) or [])):
            if getattr(event, "type", "") != "run_completed":
                continue
            usage = getattr(event, "payload", {}).get("usage", {})
            if isinstance(usage, dict):
                return dict(usage)
        return {}

    @staticmethod
    def _chat_session(agent: Any, session_id: str) -> Any:
        try:
            return agent.chat_session(session_id=session_id)
        except TypeError:
            return agent.chat_session(session_id)


@dataclass
class ScheduledJob:
    """A recurring agent job — a prompt plus when to run it."""

    name: str
    prompt: str
    interval_seconds: float | None = None  # run every N seconds
    at: str | None = None  # daily at "HH:MM" (local time)
    cron: str | None = None  # cron expression (needs `croniter`)
    session_id: str | None = None  # run inside a persistent chat session
    agent_config: ScheduledAgentConfig = field(default_factory=ScheduledAgentConfig)
    on_result: Callable[[ScheduleResult], None] | None = None
    on_error: Callable[[Exception], None] | None = None
    max_runs: int | None = None  # stop after this many runs
    runs: int = 0
    next_run: float = 0.0
    enabled: bool = True
    consecutive_failures: int = 0
    last_error: str = ""
    last_run: float | None = None

    def compute_next(self, now: float) -> float:
        if self.interval_seconds:
            return now + float(self.interval_seconds)
        if self.at:
            hour, minute = (int(x) for x in self.at.split(":"))
            base = _dt.datetime.fromtimestamp(now)
            target = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
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


class SQLiteJobStore:
    """Persist scheduler jobs so they survive process restarts.

    Stores each job's schedule spec, ``next_run``, and run count in a small
    SQLite file. Callbacks (`on_result`) are code, not data — they re-attach
    when you re-`add()` the job after a restart; everything else (due times,
    run counts) is restored from disk so no schedule slot is lost or doubled.
    """

    def __init__(self, path: str = ".shipit_workspace/schedule.db") -> None:
        import sqlite3
        from pathlib import Path

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                name TEXT PRIMARY KEY,
                prompt TEXT NOT NULL,
                interval_seconds REAL,
                at TEXT,
                cron TEXT,
                session_id TEXT,
                max_runs INTEGER,
                runs INTEGER NOT NULL DEFAULT 0,
                next_run REAL NOT NULL DEFAULT 0
            )
            """
        )
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        columns = {
            row[1] for row in self._conn.execute("PRAGMA table_info(jobs)").fetchall()
        }
        additions = {
            "agent_config": "TEXT NOT NULL DEFAULT '{}'",
            "enabled": "INTEGER NOT NULL DEFAULT 1",
            "consecutive_failures": "INTEGER NOT NULL DEFAULT 0",
            "last_error": "TEXT NOT NULL DEFAULT ''",
            "last_run": "REAL",
        }
        for name, declaration in additions.items():
            if name not in columns:
                self._conn.execute(f"ALTER TABLE jobs ADD COLUMN {name} {declaration}")

    def save(self, job: ScheduledJob) -> None:
        self._conn.execute(
            """
            INSERT INTO jobs (name, prompt, interval_seconds, at, cron,
                              session_id, max_runs, runs, next_run, agent_config,
                              enabled, consecutive_failures, last_error, last_run)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                prompt=excluded.prompt, interval_seconds=excluded.interval_seconds,
                at=excluded.at, cron=excluded.cron, session_id=excluded.session_id,
                max_runs=excluded.max_runs, runs=excluded.runs,
                next_run=excluded.next_run, agent_config=excluded.agent_config,
                enabled=excluded.enabled,
                consecutive_failures=excluded.consecutive_failures,
                last_error=excluded.last_error, last_run=excluded.last_run
            """,
            (
                job.name,
                job.prompt,
                job.interval_seconds,
                job.at,
                job.cron,
                job.session_id,
                job.max_runs,
                job.runs,
                job.next_run,
                json.dumps(job.agent_config.to_dict(), sort_keys=True),
                int(job.enabled),
                job.consecutive_failures,
                job.last_error,
                job.last_run,
            ),
        )
        self._conn.commit()

    def load(self, name: str) -> ScheduledJob | None:
        row = self._conn.execute(
            "SELECT name, prompt, interval_seconds, at, cron, session_id, "
            "max_runs, runs, next_run, agent_config, enabled, "
            "consecutive_failures, last_error, last_run FROM jobs WHERE name = ?",
            (name,),
        ).fetchone()
        if row is None:
            return None
        return ScheduledJob(
            name=row[0],
            prompt=row[1],
            interval_seconds=row[2],
            at=row[3],
            cron=row[4],
            session_id=row[5],
            max_runs=row[6],
            runs=row[7],
            next_run=row[8],
            agent_config=ScheduledAgentConfig.from_dict(json.loads(row[9] or "{}")),
            enabled=bool(row[10]),
            consecutive_failures=row[11],
            last_error=row[12] or "",
            last_run=row[13],
        )

    def load_all(self) -> list[ScheduledJob]:
        rows = self._conn.execute("SELECT name FROM jobs ORDER BY name").fetchall()
        return [self.load(row[0]) for row in rows]

    def delete(self, name: str) -> None:
        self._conn.execute("DELETE FROM jobs WHERE name = ?", (name,))
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


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
