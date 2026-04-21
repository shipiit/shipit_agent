"""Event helpers: coercion + default stderr heartbeat."""

from __future__ import annotations

import sys
from typing import Any


def coerce_event(ev: Any, *, kind_hint: str = "autopilot.event") -> dict[str, Any]:
    """Normalize whatever an inner agent yields into the
    ``{"kind": str, **payload}`` envelope the stream emits.

    Supported input shapes:
      - ``dict``                    — passed through (kind inferred if missing).
      - ``AgentEvent``              — uses ``.type``, ``.message``, ``.payload``.
      - ``GoalResult``              — mapped to an ``autopilot.iteration`` event.
      - anything else               — wrapped as an opaque repr.
    """
    if isinstance(ev, dict):
        if "kind" not in ev:
            return {"kind": kind_hint, **ev}
        return ev

    t = getattr(ev, "type", None) or getattr(ev, "event_type", None)
    if t:
        return {
            "kind": f"autopilot.{t}",
            "message": getattr(ev, "message", None),
            "payload": getattr(ev, "payload", {}),
        }

    # GoalResult duck-type: has criteria_met
    if hasattr(ev, "criteria_met"):
        return {
            "kind": "autopilot.iteration",
            "criteria_met": list(getattr(ev, "criteria_met", [])),
            "summary": str(getattr(ev, "output", ""))[:500],
        }

    return {"kind": kind_hint, "value": repr(ev)[:500]}


def looks_like_tool_event(item: Any) -> bool:
    """True if the item is an AgentEvent-shape whose type is tool-related."""
    if isinstance(item, dict):
        t = item.get("type") or item.get("event_type") or item.get("kind", "")
        return any(s in str(t) for s in ("tool_called", "tool_completed", "tool_failed"))
    t = getattr(item, "type", None) or getattr(item, "event_type", None)
    return t in {"tool_called", "tool_completed", "tool_failed"}


def default_heartbeat_stderr(payload: dict[str, Any]) -> None:
    """Write a one-line heartbeat to stderr — a sensible default sink."""
    u = payload.get("usage", {})
    met = payload.get("criteria_satisfied_count", 0)
    total = payload.get("criteria_total", 0)
    sys.stderr.write(
        f"[autopilot heartbeat] iter={payload.get('iteration')} "
        f"t={u.get('seconds', 0):.0f}s tools={u.get('tool_calls', 0)} "
        f"tok={u.get('tokens', 0)} criteria={met}/{total}\n"
    )
