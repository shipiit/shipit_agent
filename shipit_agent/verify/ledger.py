"""The verification ledger — completion gated on evidence, not the model's word.

An autonomous coding agent that trusts its own "done" ships broken code. The
fix, borrowed from the reference agent, is a tiny append-only ledger with one
rule: **an edit makes the workspace dirty; only a matching test/build that
exits 0 makes it clean again.** The loop then refuses to finish a turn that
changed code without fresh passing evidence (see :mod:`.gate`).

Two tables in one SQLite file:

- ``verification_events`` — every classified verify run (command, pass/fail by
  real exit code, a short output summary, when).
- ``verification_state`` — per ``(session, root)``: when code was last edited,
  and the id of the last *passing* event. Clean iff a pass is newer than the
  last edit.

State is keyed by ``(session_id, root)`` so two projects, or two sessions on one
project, never contaminate each other. The clock is injectable so tests are
deterministic.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

#: What the ledger says about a workspace right now.
#: - ``passed``          — code was edited and a matching verify run then passed.
#: - ``unverified``      — code was edited with no passing run since.
#: - ``not_applicable``  — no code edits recorded this session (nothing to verify).
Status = str


@dataclass(frozen=True, slots=True)
class VerificationStatus:
    status: Status
    last_command: str = ""
    last_summary: str = ""
    last_passed: bool | None = None


class VerificationLedger:
    """A SQLite record of edits and verify runs, per ``(session, root)``."""

    def __init__(
        self,
        db_path: str | Path = ":memory:",
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._clock = clock
        if db_path != ":memory:":
            Path(db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: the agent loop may touch this from a tool
        # thread; every method takes the connection's implicit lock per statement.
        self._db = sqlite3.connect(str(db_path), check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._create_schema()

    def _create_schema(self) -> None:
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS verification_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                root TEXT NOT NULL,
                command TEXT NOT NULL,
                passed INTEGER NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS verification_state (
                session_id TEXT NOT NULL,
                root TEXT NOT NULL,
                last_edit_at REAL NOT NULL DEFAULT 0,
                last_pass_event_id INTEGER,
                last_pass_at REAL NOT NULL DEFAULT 0,
                changed_paths TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (session_id, root)
            );
            """
        )
        self._db.commit()

    def _key(self, session_id: str, root: str | Path) -> tuple[str, str]:
        return str(session_id or ""), str(Path(root).expanduser())

    def mark_edited(
        self, *, session_id: str, root: str | Path, paths: list[str] | None = None
    ) -> None:
        """Record that code changed — the workspace is now dirty (unverified)."""
        session, root_key = self._key(session_id, root)
        now = self._clock()
        joined = "\n".join(str(p) for p in (paths or []))
        self._db.execute(
            """
            INSERT INTO verification_state (session_id, root, last_edit_at, changed_paths)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(session_id, root) DO UPDATE SET
                last_edit_at = excluded.last_edit_at,
                changed_paths = excluded.changed_paths
            """,
            (session, root_key, now, joined),
        )
        self._db.commit()

    def record_run(
        self,
        *,
        session_id: str,
        root: str | Path,
        command: str,
        passed: bool,
        summary: str = "",
    ) -> int:
        """Record a verify run's outcome (pass/fail by real exit code).

        A *passing* run advances the clean pointer, so a workspace edited then
        verified reads ``passed``. A failing run is recorded (for the nudge's
        "last failure" context) but never marks the workspace clean.
        """
        session, root_key = self._key(session_id, root)
        now = self._clock()
        cursor = self._db.execute(
            """
            INSERT INTO verification_events
                (session_id, root, command, passed, summary, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session, root_key, command, int(bool(passed)), summary[:2000], now),
        )
        event_id = int(cursor.lastrowid or 0)
        if passed:
            self._db.execute(
                """
                INSERT INTO verification_state
                    (session_id, root, last_pass_event_id, last_pass_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id, root) DO UPDATE SET
                    last_pass_event_id = excluded.last_pass_event_id,
                    last_pass_at = excluded.last_pass_at
                """,
                (session, root_key, event_id, now),
            )
        self._db.commit()
        return event_id

    def status(self, *, session_id: str, root: str | Path) -> VerificationStatus:
        """Where the workspace stands: passed / unverified / not_applicable."""
        session, root_key = self._key(session_id, root)
        row = self._db.execute(
            "SELECT last_edit_at, last_pass_at FROM verification_state "
            "WHERE session_id = ? AND root = ?",
            (session, root_key),
        ).fetchone()
        last_event = self._db.execute(
            "SELECT command, passed, summary FROM verification_events "
            "WHERE session_id = ? AND root = ? ORDER BY id DESC LIMIT 1",
            (session, root_key),
        ).fetchone()
        command = last_event[0] if last_event else ""
        summary = last_event[2] if last_event else ""
        last_passed = bool(last_event[1]) if last_event else None

        if row is None or not row[0]:
            status = "not_applicable"      # no edits recorded → nothing to verify
        elif row[1] and row[1] >= row[0]:
            status = "passed"              # a pass at or after the last edit
        else:
            status = "unverified"          # edited, no pass since
        return VerificationStatus(
            status=status, last_command=command, last_summary=summary,
            last_passed=last_passed,
        )

    def close(self) -> None:
        self._db.close()
