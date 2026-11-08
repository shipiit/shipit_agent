"""One-line formatting for runtime events."""

from __future__ import annotations

from typing import Any

from shipit_agent.core.models import AgentEvent

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
    if event.type == "skills_selected":
        ids = ", ".join(str(item) for item in p.get("skill_ids", []))
        tools = ", ".join(str(item) for item in p.get("injected_tools", []))
        suffix = f" (tools: {tools})" if tools else ""
        return f"skills  {ids}{suffix}" if ids else None
    if event.type == "agent_decision":
        summary = _clip(event.display_message, _MAX_OUTPUT_CHARS)
        return f"agent_decision     {summary}" if summary else None
    if event.type == "agent_observation":
        summary = _clip(event.display_message, _MAX_OUTPUT_CHARS)
        return f"agent_observation  {summary}" if summary else None
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

