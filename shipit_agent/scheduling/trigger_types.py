"""Trigger events, triggers and trigger runs."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(slots=True)
class TriggerEvent:
    """One thing that happened, waiting to be turned into a run."""

    source: str
    data: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: float = field(default_factory=time.time)
    attempts: int = 0

    def to_row(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "data": json.dumps(self.data, default=str),
            "created_at": self.created_at,
            "attempts": self.attempts,
        }


@dataclass(slots=True)
class Trigger:
    """A source, and what to ask the agent when it fires."""

    name: str
    source: str
    #: Event → prompt. Returning ``None`` skips this event entirely, which is
    #: how a trigger filters: "only RSVPs", "only failures", "only my inbox".
    build_prompt: Callable[[TriggerEvent], str | None]
    enabled: bool = True
    description: str = ""

    def prompt_for(self, event: TriggerEvent) -> str | None:
        prompt = self.build_prompt(event)
        return prompt.strip() if isinstance(prompt, str) and prompt.strip() else None


@dataclass(slots=True)
class TriggerRun:
    """What one delivery did."""

    trigger: str
    event_id: str
    ok: bool
    skipped: bool = False
    output: str = ""
    error: str = ""

