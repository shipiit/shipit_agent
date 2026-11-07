"""A compaction checkpoint: where replay starts, and the summary that stands in for what came before."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Sequence

from shipit_agent.core.models import Message


@dataclass(slots=True)
class CompactionCheckpoint:
    """Immutable record of one compaction.

    Kept forever. Canonical history is never rewritten — ``compacted_to`` says
    where *replay* starts, and ``summary`` stands in for everything before it.
    """

    compacted_to: int
    summary: str
    tokens_before: int
    tokens_after: int
    created_at: float = field(default_factory=time.time)

    @property
    def saved_tokens(self) -> int:
        return max(0, self.tokens_before - self.tokens_after)

    def replay(self, messages: Sequence[Message]) -> list[Message]:
        """The message list to send the model: system + summary + retained."""
        head = [m for m in messages[: self.compacted_to] if m.role == "system"]
        summary = Message(
            role="user",
            content=self.summary,
            metadata={"compacted": True, "compacted_to": self.compacted_to},
        )
        return [*head, summary, *messages[self.compacted_to :]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "compacted_to": self.compacted_to,
            "summary": self.summary,
            "tokens_before": self.tokens_before,
            "tokens_after": self.tokens_after,
            "saved_tokens": self.saved_tokens,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CompactionCheckpoint":
        """Restore a checkpoint stored with a durable chat session."""
        return cls(
            compacted_to=max(0, int(value.get("compacted_to", 0) or 0)),
            summary=str(value.get("summary", "") or ""),
            tokens_before=max(0, int(value.get("tokens_before", 0) or 0)),
            tokens_after=max(0, int(value.get("tokens_after", 0) or 0)),
            created_at=float(value.get("created_at", time.time()) or time.time()),
        )
