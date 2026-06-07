"""Side-by-side diffing of two agent traces.

Comparing a baseline run against a fork-and-replay tells you what
actually changed downstream of an edit. Compact output by default;
detailed diffs available via ``TraceDiff.to_lines()``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shipit_agent.models import AgentEvent

from .replayer import TraceReplayer


@dataclass(slots=True)
class TraceDiff:
    """Result of comparing two traces.

    Both traces are walked in order. Events that match (same type + same
    payload) are paired; mismatches and length deltas are reported.
    """

    left_id: str
    right_id: str
    matched: int = 0
    diverged_at: int | None = None
    """0-indexed event number where the two traces first diverged, or None
    if one is a strict prefix of the other (or they're identical)."""
    only_in_left: list[tuple[int, AgentEvent]] = field(default_factory=list)
    only_in_right: list[tuple[int, AgentEvent]] = field(default_factory=list)
    type_mismatches: list[tuple[int, str, str]] = field(default_factory=list)
    """``[(event_index, left_type, right_type), ...]`` for divergent events."""

    @property
    def identical(self) -> bool:
        return (
            self.diverged_at is None
            and not self.only_in_left
            and not self.only_in_right
            and not self.type_mismatches
        )

    def to_lines(self, *, limit: int = 40) -> list[str]:
        """Render a human-readable summary, capped at ``limit`` lines."""
        lines = [
            f"Trace diff: {self.left_id} ↔ {self.right_id}",
            f"  matched events: {self.matched}",
        ]
        if self.identical:
            lines.append("  ✓ identical")
            return lines[:limit]
        if self.diverged_at is not None:
            lines.append(f"  diverged at event {self.diverged_at}")
        if self.type_mismatches:
            lines.append(f"  type mismatches: {len(self.type_mismatches)}")
            for i, (idx, lt, rt) in enumerate(self.type_mismatches[:10]):
                lines.append(f"    event {idx}: {lt!r} → {rt!r}")
        if self.only_in_left:
            lines.append(f"  only in left ({self.left_id}): {len(self.only_in_left)}")
            for idx, ev in self.only_in_left[:10]:
                lines.append(f"    [{idx}] {ev.type}: {ev.message[:80]}")
        if self.only_in_right:
            lines.append(f"  only in right ({self.right_id}): {len(self.only_in_right)}")
            for idx, ev in self.only_in_right[:10]:
                lines.append(f"    [{idx}] {ev.type}: {ev.message[:80]}")
        return lines[:limit]


def diff_traces(
    left: TraceReplayer | Any,
    right: TraceReplayer | Any,
) -> TraceDiff:
    """Diff two traces. Accepts either ``TraceReplayer`` or raw ``TraceRecord``.

    Walks both event lists in order. As soon as the types disagree on a
    paired index, every subsequent event is treated as "diverged" — the
    common prefix is reported via ``matched``, and tail events on both
    sides are returned via ``only_in_left`` / ``only_in_right``.
    """
    left_events = _events(left)
    right_events = _events(right)
    diff = TraceDiff(
        left_id=_id(left),
        right_id=_id(right),
    )

    n = min(len(left_events), len(right_events))
    matched = 0
    diverged = False
    for i in range(n):
        a = left_events[i]
        b = right_events[i]
        if a.type == b.type:
            # Only the common prefix counts as matched — once the traces have
            # diverged, a later reconvergence must not resume the count.
            if not diverged:
                matched += 1
        else:
            if not diverged:
                diff.diverged_at = i
                diverged = True
            diff.type_mismatches.append((i, a.type, b.type))

    diff.matched = matched

    # Tail handling — events past the common length live in only-in-left / right
    if len(left_events) > n:
        for i in range(n, len(left_events)):
            diff.only_in_left.append((i, left_events[i]))
        if not diverged:
            diff.diverged_at = n
    if len(right_events) > n:
        for i in range(n, len(right_events)):
            diff.only_in_right.append((i, right_events[i]))
        if not diverged:
            diff.diverged_at = n

    return diff


def _events(t: Any) -> list[AgentEvent]:
    if isinstance(t, TraceReplayer):
        return t.events
    if hasattr(t, "events"):
        return list(t.events)
    raise TypeError(f"diff_traces: unsupported trace type {type(t)}")


def _id(t: Any) -> str:
    if isinstance(t, TraceReplayer):
        return t.trace_id
    return getattr(t, "trace_id", "unknown")
