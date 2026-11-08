"""FanoutResult and the budget, aggregation and naming helpers autopilot fan-out uses."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field  # asdict used for event payloads
from typing import Any

from .budget import BudgetPolicy
from .result import AutopilotResult


@dataclass(slots=True)
class FanoutResult:
    """Aggregate envelope returned by :meth:`Autopilot.fanout`.

    ``status`` rollup:
      - ``completed`` — every child finished ``completed``.
      - ``partial``    — some children completed; others partial/halted.
      - ``failed``     — every child failed.
    """

    parent_run_id: str
    objective_template: str
    status: str = "unknown"
    children: list[dict[str, Any]] = field(default_factory=list)
    aggregated_output: str = ""
    wall_seconds: float = 0.0
    failed: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _scale_budget(parent: BudgetPolicy, frac: float) -> BudgetPolicy:
    """Return a new BudgetPolicy whose caps are the parent's * frac."""
    frac = max(0.05, min(1.0, frac))

    def _scale(v: int | float | None) -> int | float | None:
        if v in (None, 0):
            return v
        if isinstance(v, int):
            return max(1, int(v * frac))
        return max(1.0, v * frac)

    return BudgetPolicy(
        max_seconds=_scale(parent.max_seconds),
        max_tool_calls=_scale(parent.max_tool_calls),
        max_tokens=_scale(parent.max_tokens),
        max_dollars=_scale(parent.max_dollars),
        max_iterations=_scale(parent.max_iterations),
    )


def _default_aggregator(children: list[AutopilotResult]) -> str:
    """Stitch child outputs into a single markdown digest."""
    if not children:
        return "(no children)"
    lines: list[str] = [f"# Fan-out digest — {len(children)} children\n"]
    for c in children:
        header = f"## {c.run_id} · {c.status.upper()} · {c.iterations} iters"
        body = (c.output or "").strip()
        if len(body) > 1500:
            body = body[:1500] + "\n…(truncated)"
        lines.append(f"{header}\n\n{body}\n")
    return "\n".join(lines)


def _rollup_status(statuses: list[str]) -> str:
    if not statuses:
        return "completed"
    if all(s == "completed" for s in statuses):
        return "completed"
    if all(s == "failed" for s in statuses):
        return "failed"
    return "partial"


def _slug(item: Any) -> str:
    """Make a filesystem-safe id fragment out of whatever the user passed.

    Strip any leading/trailing dots OR dashes so paths like "../etc/passwd"
    don't round-trip as "..-etc-passwd" (which still looks like a path
    traversal and breaks the expected "etc-passwd" slug).
    """
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", str(item).strip().lower())
    return s.strip(".-")[:48] or "item"

