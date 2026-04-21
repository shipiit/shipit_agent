"""Scheduler daemon — keep an Autopilot queue running indefinitely.

Reads a persistent JSON queue of goals, drains it one goal at a time
through ``Autopilot``, and loops. Designed to be run under a supervisor
(systemd, launchd, Docker) so a single command ``python -m shipit_agent.cli
daemon`` turns your machine into a 24-hour agent host.

Queue file format (``~/.shipit_agent/autopilot-queue.json``)::

    [
      {
        "run_id": "nightly-security-review",
        "objective": "Review every PR merged today for security regressions",
        "success_criteria": ["No high-severity finding in last 24h"],
        "budget": {"max_seconds": 1800, "max_tool_calls": 150},
        "status": "pending",
        "created_at": 1713710400.0
      },
      ...
    ]

A task transitions pending → running → done | failed | halted. The daemon
picks the earliest ``pending`` entry each tick. Completed entries stay in
the queue so you can inspect their `result` key.

This file intentionally does NOT import heavy LLM SDKs — the caller
provides an ``llm_factory`` callable that builds whatever provider they
want. That way the daemon module is import-safe in any environment.
"""

from __future__ import annotations

import json
import os
import signal
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from shipit_agent.autopilot import (
    Autopilot,
    AutopilotResult,
    BudgetPolicy,
    default_heartbeat_stderr,
)
from shipit_agent.deep.goal_agent import Goal


@dataclass(slots=True)
class QueueEntry:
    run_id: str
    objective: str
    success_criteria: list[str] = field(default_factory=list)
    budget: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"             # pending | running | done | failed | halted
    created_at: float = 0.0
    started_at: float | None = None
    finished_at: float | None = None
    result: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        # asdict() works with slots=True; __dict__.copy() does not.
        return asdict(self)


LlmFactory = Callable[[], Any]


class SchedulerDaemon:
    """Tick-based goal queue runner. `run_forever()` blocks; `run_once()`
    drains only the first pending entry (useful for cron / tests).

    The caller supplies ``llm_factory`` so the daemon doesn't hard-depend
    on any one provider. Each tick builds a fresh LLM — important for
    long runs where the underlying SDK may reset auth tokens.
    """

    def __init__(
        self,
        *,
        llm_factory: LlmFactory,
        queue_path: str | Path | None = None,
        tick_seconds: float = 5.0,
        heartbeat_every_ticks: int = 60,      # ~5 min at 5s tick
        on_heartbeat: Callable[[dict[str, Any]], None] | None = None,
        tools: list[Any] | None = None,
        mcps: list[Any] | None = None,
        checkpoint_dir: str | Path | None = None,
    ) -> None:
        self.llm_factory = llm_factory
        self.queue_path = (
            Path(queue_path).expanduser()
            if queue_path
            else Path.home() / ".shipit_agent" / "autopilot-queue.json"
        )
        self.tick_seconds = max(1.0, tick_seconds)
        self.heartbeat_every_ticks = max(1, heartbeat_every_ticks)
        self.on_heartbeat = on_heartbeat
        self.tools = list(tools or [])
        self.mcps = list(mcps or [])
        self.checkpoint_dir = checkpoint_dir
        self._stopping = False

    # ── public API ────────────────────────────────────────────────

    def enqueue(
        self,
        *,
        run_id: str,
        objective: str,
        success_criteria: list[str] | None = None,
        budget: dict[str, Any] | None = None,
    ) -> QueueEntry:
        entries = self._load_queue()
        if any(e.run_id == run_id for e in entries):
            raise ValueError(f"A task with run_id={run_id!r} already exists in the queue.")
        entry = QueueEntry(
            run_id=run_id,
            objective=objective,
            success_criteria=list(success_criteria or []),
            budget=dict(budget or {}),
            created_at=time.time(),
        )
        entries.append(entry)
        self._save_queue(entries)
        return entry

    def list_queue(self) -> list[QueueEntry]:
        return self._load_queue()

    def remove(self, run_id: str) -> bool:
        entries = self._load_queue()
        kept = [e for e in entries if e.run_id != run_id]
        self._save_queue(kept)
        return len(kept) != len(entries)

    def run_once(self) -> AutopilotResult | None:
        entries = self._load_queue()
        idx = next((i for i, e in enumerate(entries) if e.status == "pending"), None)
        if idx is None:
            return None
        entry = entries[idx]
        entry.status = "running"
        entry.started_at = time.time()
        self._save_queue(entries)

        try:
            autopilot = Autopilot(
                llm=self.llm_factory(),
                goal=Goal(
                    objective=entry.objective,
                    success_criteria=list(entry.success_criteria),
                ),
                tools=list(self.tools),
                mcps=list(self.mcps),
                budget=BudgetPolicy(**entry.budget) if entry.budget else BudgetPolicy(),
                checkpoint_dir=self.checkpoint_dir,
                on_heartbeat=self.on_heartbeat,
            )
            result = autopilot.run(run_id=entry.run_id)
        except Exception as err:       # noqa: BLE001
            entry.status = "failed"
            entry.finished_at = time.time()
            entry.result = {"status": "failed", "error": f"{type(err).__name__}: {err}"}
            self._save_queue(self._merge_update(entry))
            return None

        entry.finished_at = time.time()
        entry.result = result.to_dict()
        entry.status = {
            "completed": "done",
            "partial": "done",
            "halted": "halted",
            "failed": "failed",
        }.get(result.status, "done")
        self._save_queue(self._merge_update(entry))
        return result

    def run_forever(self) -> None:
        """Block and drain the queue until SIGINT / SIGTERM."""
        signal.signal(signal.SIGINT, self._request_stop)
        signal.signal(signal.SIGTERM, self._request_stop)

        tick = 0
        idle_ticks = 0
        while not self._stopping:
            tick += 1
            result = self.run_once()
            if result is None:
                idle_ticks += 1
            else:
                idle_ticks = 0

            if self.on_heartbeat and idle_ticks > 0 and idle_ticks % self.heartbeat_every_ticks == 0:
                entries = self._load_queue()
                pending = [e for e in entries if e.status == "pending"]
                self.on_heartbeat(
                    {
                        "kind": "daemon_heartbeat",
                        "tick": tick,
                        "idle_ticks": idle_ticks,
                        "pending": len(pending),
                        "total": len(entries),
                        "queue_path": str(self.queue_path),
                    }
                )

            # Sleep in 0.25s steps so SIGINT wakes us promptly.
            remaining = self.tick_seconds
            while remaining > 0 and not self._stopping:
                time.sleep(min(0.25, remaining))
                remaining -= 0.25

    # ── internals ─────────────────────────────────────────────────

    def _request_stop(self, *_args: Any) -> None:
        self._stopping = True

    def _load_queue(self) -> list[QueueEntry]:
        if not self.queue_path.exists():
            return []
        try:
            raw = json.loads(self.queue_path.read_text())
        except (OSError, json.JSONDecodeError):
            return []
        out: list[QueueEntry] = []
        for item in raw:
            try:
                out.append(QueueEntry(**item))
            except TypeError:
                # Forward-compat: ignore entries with new/unknown fields.
                known = {k: v for k, v in item.items() if k in QueueEntry.__slots__}
                out.append(QueueEntry(**known))
        return out

    def _save_queue(self, entries: list[QueueEntry]) -> None:
        self.queue_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.queue_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps([e.to_dict() for e in entries], indent=2))
        tmp.replace(self.queue_path)

    def _merge_update(self, updated: QueueEntry) -> list[QueueEntry]:
        entries = self._load_queue()
        for i, e in enumerate(entries):
            if e.run_id == updated.run_id:
                entries[i] = updated
                break
        else:
            entries.append(updated)
        return entries
