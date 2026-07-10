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

from .models import AgentEvent, AgentResult

_MAX_ARG_CHARS = 80
_MAX_OUTPUT_CHARS = 160


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text).split())  # collapse whitespace/newlines
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _format_args(arguments: dict[str, Any] | None, limit: int = _MAX_ARG_CHARS) -> str:
    if not arguments:
        return ""
    parts = []
    for key, value in arguments.items():
        rendered = repr(value) if not isinstance(value, str) else f'"{value}"'
        parts.append(f"{key}={_clip(rendered, 40)}")
    return _clip(", ".join(parts), limit)


def _format_duration(duration_ms: Any) -> str:
    try:
        ms = float(duration_ms)
    except (TypeError, ValueError):
        return ""
    return f"{ms / 1000:.1f}s" if ms >= 1000 else f"{ms:.0f}ms"


def format_event_line(event: AgentEvent) -> str | None:
    """Render one event as a display line (``None`` = not user-facing)."""
    p = event.payload
    if event.type == "tool_called":
        return f"⚙ {p.get('tool', '?')}({_format_args(p.get('arguments'))}) …"
    if event.type == "tool_completed":
        dur = _format_duration(p.get("duration_ms"))
        head = f"⚙ {p.get('tool', '?')} ✓" + (f" {dur}" if dur else "")
        preview = _clip(str(p.get("output", "")), _MAX_OUTPUT_CHARS)
        return f"{head}\n  └ {preview}" if preview else head
    if event.type == "tool_failed":
        dur = _format_duration(p.get("duration_ms"))
        head = f"⚙ {p.get('tool', '?')} ✗" + (f" {dur}" if dur else "")
        return f"{head}\n  └ error: {_clip(str(p.get('error', '')), _MAX_OUTPUT_CHARS)}"
    if event.type == "tool_retry":
        return f"↻ retry {p.get('tool', '')} (attempt {p.get('attempt', '?')})"
    if event.type == "run_completed":
        return None  # summarized in the footer instead
    return None


def format_activity(source: AgentResult | Iterable[AgentEvent]) -> str:
    """Render a full run as a clean activity trace.

    Pairs each ``tool_called`` with its ``tool_completed``/``tool_failed``
    into a single card (name, args, status, duration, result preview), and
    appends a one-line summary footer.
    """
    events = list(source.events if isinstance(source, AgentResult) else source)
    lines: list[str] = []
    pending_args: dict[int, str] = {}  # order-preserving call → args text
    calls = ok = failed = 0
    iterations: set[Any] = set()

    for event in events:
        p = event.payload
        if "iteration" in p:
            iterations.add(p["iteration"])
        if event.type == "tool_called":
            calls += 1
            pending_args[calls] = _format_args(p.get("arguments"))
        elif event.type in ("tool_completed", "tool_failed"):
            args_text = pending_args.pop(max(pending_args, default=0), "")
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
