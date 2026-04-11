from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import AgentEvent, Message


@dataclass(slots=True)
class ContextSnapshot:
    """Point-in-time snapshot of context window utilization."""

    total_tokens: int
    max_tokens: int
    breakdown: dict[str, int]
    utilization: float
    compaction_threshold: float
    will_compact: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_tokens": self.total_tokens,
            "max_tokens": self.max_tokens,
            "breakdown": self.breakdown,
            "utilization": round(self.utilization, 4),
            "compaction_threshold": self.compaction_threshold,
            "will_compact": self.will_compact,
        }


@dataclass(slots=True)
class ContextTracker:
    """Tracks context window utilization across agent execution."""

    max_tokens: int = 128_000
    compaction_threshold: float = 0.75
    snapshots: list[ContextSnapshot] = field(default_factory=list)

    def snapshot(
        self,
        messages: list[Message],
        tool_schemas: list[dict[str, Any]] | None = None,
        memory_context: str = "",
        system_prompt: str = "",
    ) -> ContextSnapshot:
        breakdown = {
            "system_prompt": self._estimate_tokens(system_prompt),
            "conversation": sum(
                self._estimate_tokens(m.content)
                for m in messages
                if m.role not in ("system", "tool")
            ),
            "tool_schemas": sum(
                self._estimate_tokens(str(s)) for s in (tool_schemas or [])
            ),
            "tool_results": sum(
                self._estimate_tokens(m.content) for m in messages if m.role == "tool"
            ),
            "memory": self._estimate_tokens(memory_context),
        }

        total = sum(breakdown.values())
        utilization = total / self.max_tokens if self.max_tokens > 0 else 0.0

        snap = ContextSnapshot(
            total_tokens=total,
            max_tokens=self.max_tokens,
            breakdown=breakdown,
            utilization=utilization,
            compaction_threshold=self.compaction_threshold,
            will_compact=utilization >= self.compaction_threshold,
        )
        self.snapshots.append(snap)
        return snap

    def to_event(self) -> AgentEvent:
        if not self.snapshots:
            return AgentEvent(
                type="context_snapshot", message="No snapshots", payload={}
            )
        latest = self.snapshots[-1]
        return AgentEvent(
            type="context_snapshot",
            message=f"Context: {latest.total_tokens}/{latest.max_tokens} tokens ({latest.utilization:.0%})",
            payload=latest.to_dict(),
        )

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        if not text:
            return 0
        return max(1, len(text) // 4)
