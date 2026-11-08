"""Scheduled jobs and their SQLite store."""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass, field
from typing import Callable

from .config import ScheduledAgentConfig, ScheduleResult


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

