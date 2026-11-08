"""Human-readable activity traces — Claude-Code-style tool cards.

Turn a run's event stream into a clean, scannable log::

    from shipit_agent import format_activity

    result = agent.run("Fix the failing test")
    print(format_activity(result))

    ⚙ bash(command="pytest -q") ✓ 1.2s
      └ exit_code: 0 · 1906 passed
    ⚙ edit_file(path="app.py") ✓ 0.1s
      └ replaced 1 occurrence
    ✔ run completed · 2 tool calls · 1 iteration

Works on an ``AgentResult`` or a raw list of ``AgentEvent``; also usable
live from ``agent.stream(...)`` via :func:`format_event_line`.
"""

from __future__ import annotations

from typing import Any, Iterable

from shipit_agent.core.models import AgentEvent, AgentResult

from .event_lines import _MAX_OUTPUT_CHARS
from .event_lines import (
    _clip as _clip,
)
from .event_lines import (
    _format_args as _format_args,
)
from .event_lines import (
    _format_duration as _format_duration,
)
from .event_lines import (
    format_event_line as format_event_line,
)
from .stream_renderer import StreamRenderer as StreamRenderer


def format_activity(source: AgentResult | Iterable[AgentEvent]) -> str:
    """Render a full run as a clean activity trace.

    Pairs each ``tool_called`` with its ``tool_completed``/``tool_failed``
    into a single card (name, args, status, duration, result preview), and
    appends a one-line summary footer.
    """
    events = list(source.events if isinstance(source, AgentResult) else source)
    lines: list[str] = []
    # Pair calls to results by call_id when present; fall back to LIFO order.
    pending_args: dict[Any, str] = {}
    calls = ok = failed = 0
    iterations: set[Any] = set()

    for event in events:
        p = event.payload
        if "iteration" in p:
            iterations.add(p["iteration"])
        if event.type == "tool_called":
            calls += 1
            pending_args[p.get("call_id", calls)] = _format_args(p.get("arguments"))
        elif event.type in (
            "skills_selected",
            "agent_decision",
            "agent_observation",
        ):
            line = format_event_line(event)
            if line:
                lines.append(line)
        elif event.type in ("tool_completed", "tool_failed"):
            key = p.get("call_id")
            if key not in pending_args:
                key = max(pending_args, default=0, key=lambda k: str(k))
            args_text = pending_args.pop(key, "")
            dur = _format_duration(p.get("duration_ms"))
            status = "✓" if event.type == "tool_completed" else "✗"
            head = f"⚙ {p.get('tool', '?')}({args_text}) {status}"
            if dur:
                head += f" {dur}"
            lines.append(head)
            if event.type == "tool_completed":
                ok += 1
                preview = _clip(str(p.get("output", "")), _MAX_OUTPUT_CHARS)
                if preview:
                    lines.append(f"  └ {preview}")
            else:
                failed += 1
                lines.append(
                    f"  └ error: {_clip(str(p.get('error', '')), _MAX_OUTPUT_CHARS)}"
                )
        elif event.type == "tool_retry":
            lines.append(f"↻ retry (attempt {p.get('attempt', '?')})")

    footer = f"✔ run completed · {calls} tool call{'s' if calls != 1 else ''}"
    if failed:
        footer += f" ({failed} failed)"
    if iterations:
        n = len(iterations)
        footer += f" · {n} iteration{'s' if n != 1 else ''}"
    lines.append(footer)
    return "\n".join(lines)
