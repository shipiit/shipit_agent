"""Non-blocking ask_user side-channel.

Autopilot's ``ask_user`` tool ordinarily blocks the loop until the user
types something. For long-running overnight jobs that won't work: the
run either hangs forever or the user has to be at the keyboard.

This module implements a **file-based side channel**:

  1. The `ask_user_async` tool writes a question to
     ``~/.shipit_agent/askuser/<run_id>.json`` and returns a synthetic
     tool result that tells the model "I've asked the user, checkpoint
     and end your turn."
  2. Autopilot checkpoints + halts with ``status="awaiting_user"``.
  3. The user answers via CLI — ``shipit answer <run_id> "..."`` — or
     programmatically via :func:`write_answer`. The answer is appended
     to the same JSON file.
  4. On resume, Autopilot's loader sees the answered question and
     injects the answer as a "tool" message for the next iteration.

Thread-safety: atomic rename on write. Cross-process-safe.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


def channel_dir() -> Path:
    """Directory where ask/answer files live. Created on first access."""
    root = Path(
        os.environ.get("SHIPIT_ASKUSER_DIR")
        or (Path.home() / ".shipit_agent" / "askuser")
    )
    root.mkdir(parents=True, exist_ok=True)
    return root


def channel_file(run_id: str) -> Path:
    return channel_dir() / f"{_safe(run_id)}.json"


# ─────────────────────── envelope ───────────────────────


@dataclass(slots=True)
class AskEntry:
    """One question/answer pair in the channel. Multiple pairs accumulate
    across iterations as the agent asks follow-ups."""

    question: str
    asked_at: float = field(default_factory=time.time)
    context: str = ""
    choices: list[str] = field(default_factory=list)
    answer: str | None = None
    answered_at: float | None = None

    def answered(self) -> bool:
        return self.answer is not None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AskChannel:
    """Serialized form written to disk."""

    run_id: str
    entries: list[AskEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"run_id": self.run_id, "entries": [e.to_dict() for e in self.entries]}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AskChannel":
        entries = [AskEntry(**e) for e in d.get("entries", [])]
        return cls(run_id=str(d.get("run_id", "")), entries=entries)


# ─────────────────────── reads / writes ───────────────────────


def load(run_id: str) -> AskChannel:
    path = channel_file(run_id)
    if not path.exists():
        return AskChannel(run_id=run_id)
    try:
        return AskChannel.from_dict(json.loads(path.read_text()))
    except (OSError, json.JSONDecodeError):
        return AskChannel(run_id=run_id)


def save(channel: AskChannel) -> None:
    path = channel_file(channel.run_id)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(channel.to_dict(), indent=2))
    tmp.replace(path)  # atomic rename — never corrupt on crash


def ask_question(
    run_id: str,
    question: str,
    *,
    context: str = "",
    choices: list[str] | None = None,
) -> AskEntry:
    """Append a new question to the channel. Returns the entry so the
    tool impl can surface the index to the model."""
    channel = load(run_id)
    entry = AskEntry(question=question, context=context, choices=list(choices or []))
    channel.entries.append(entry)
    save(channel)
    return entry


def write_answer(run_id: str, answer: str, *, index: int | None = None) -> bool:
    """Answer the latest (or index-addressed) unanswered question.

    Returns True if an entry was updated, False if there was nothing
    outstanding.
    """
    channel = load(run_id)
    if not channel.entries:
        return False
    candidates = [
        (i, e)
        for i, e in enumerate(channel.entries)
        if (index is None or i == index) and not e.answered()
    ]
    if not candidates:
        return False
    i, entry = candidates[-1]
    channel.entries[i] = AskEntry(
        question=entry.question,
        asked_at=entry.asked_at,
        context=entry.context,
        choices=list(entry.choices),
        answer=answer,
        answered_at=time.time(),
    )
    save(channel)
    return True


def pending_questions(run_id: str) -> list[AskEntry]:
    """Unanswered questions in order. Empty when the run is not waiting."""
    return [e for e in load(run_id).entries if not e.answered()]


def all_entries(run_id: str) -> list[AskEntry]:
    return load(run_id).entries


def clear(run_id: str) -> None:
    """Delete the channel file — useful for test cleanup or reset."""
    path = channel_file(run_id)
    try:
        path.unlink()
    except FileNotFoundError:
        pass


# ─────────────────────── helpers ───────────────────────


def _safe(run_id: str) -> str:
    """Slug a run_id into a safe filename (defensive against path traversal)."""
    import re

    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", run_id.strip())
    return cleaned.strip("-.") or "run"
