"""Trigger queues: the interface, in-memory and SQLite."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Protocol

from .trigger_types import TriggerEvent

#: How long a claimed event stays claimed before it is considered abandoned.
#: Long enough for a slow agent run, short enough that a crashed worker's
#: work is picked up in the same hour.
VISIBILITY_SECONDS = 15 * 60


class TriggerQueue(Protocol):
    """Durable-enough storage for events between firing and running."""

    def put(self, event: TriggerEvent) -> None: ...

    def claim(self, limit: int = 10) -> list[TriggerEvent]: ...

    def done(self, event_id: str) -> None: ...

    def release(self, event_id: str, *, error: str = "") -> None: ...

    def pending(self) -> int: ...


class InMemoryTriggerQueue:
    """For tests and single-process toys.

    Named so nobody reaches for it by accident: an in-memory queue loses
    every unhandled event when the process ends, which is exactly the failure
    a trigger system exists to prevent.
    """

    def __init__(self) -> None:
        self._events: dict[str, TriggerEvent] = {}
        self._claimed: dict[str, float] = {}
        self._lock = threading.Lock()

    def put(self, event: TriggerEvent) -> None:
        with self._lock:
            self._events[event.id] = event

    def claim(self, limit: int = 10) -> list[TriggerEvent]:
        now = time.time()
        with self._lock:
            for event_id, at in list(self._claimed.items()):
                if now - at > VISIBILITY_SECONDS:
                    del self._claimed[event_id]
            ready = [
                event for event in self._events.values()
                if event.id not in self._claimed
            ]
            ready.sort(key=lambda event: event.created_at)
            taken = ready[:limit]
            for event in taken:
                self._claimed[event.id] = now
            return taken

    def done(self, event_id: str) -> None:
        with self._lock:
            self._events.pop(event_id, None)
            self._claimed.pop(event_id, None)

    def release(self, event_id: str, *, error: str = "") -> None:
        with self._lock:
            self._claimed.pop(event_id, None)
            event = self._events.get(event_id)
            if event is not None:
                event.attempts += 1

    def pending(self) -> int:
        with self._lock:
            return len(self._events)


class SqliteTriggerQueue:
    """The default: events survive the process that received them.

    One table, one file, no server. A trigger system whose queue needs its
    own infrastructure is one nobody turns on.
    """

    def __init__(self, path: str | Path = ".shipit/triggers.db") -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS trigger_events (
                       id TEXT PRIMARY KEY,
                       source TEXT NOT NULL,
                       data TEXT NOT NULL,
                       created_at REAL NOT NULL,
                       attempts INTEGER NOT NULL DEFAULT 0,
                       claimed_at REAL,
                       last_error TEXT DEFAULT ''
                   )"""
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS trigger_ready "
                "ON trigger_events (claimed_at, created_at)"
            )
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        # A queue is read-modify-write from several workers; WAL is what
        # makes that not a lock storm.
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def put(self, event: TriggerEvent) -> None:
        row = event.to_row()
        with closing(self._connect()) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO trigger_events "
                "(id, source, data, created_at, attempts) "
                "VALUES (:id, :source, :data, :created_at, :attempts)", row)
            connection.commit()

    def claim(self, limit: int = 10) -> list[TriggerEvent]:
        cutoff = time.time() - VISIBILITY_SECONDS
        now = time.time()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT id, source, data, created_at, attempts "
                "FROM trigger_events "
                "WHERE claimed_at IS NULL OR claimed_at < ? "
                "ORDER BY created_at LIMIT ?", (cutoff, limit)).fetchall()
            for row in rows:
                connection.execute(
                    "UPDATE trigger_events SET claimed_at = ? WHERE id = ?",
                    (now, row[0]))
            connection.commit()
        return [
            TriggerEvent(id=row[0], source=row[1], data=json.loads(row[2]),
                         created_at=row[3], attempts=row[4])
            for row in rows
        ]

    def done(self, event_id: str) -> None:
        with closing(self._connect()) as connection:
            connection.execute("DELETE FROM trigger_events WHERE id = ?",
                               (event_id,))
            connection.commit()

    def release(self, event_id: str, *, error: str = "") -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                "UPDATE trigger_events SET claimed_at = NULL, "
                "attempts = attempts + 1, last_error = ? WHERE id = ?",
                (error[:500], event_id))
            connection.commit()

    def pending(self) -> int:
        with closing(self._connect()) as connection:
            return connection.execute(
                "SELECT COUNT(*) FROM trigger_events").fetchone()[0]

