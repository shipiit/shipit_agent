"""StreamRenderer: live terminal rendering of a run's events."""

from __future__ import annotations

from typing import Any

from shipit_agent.core.models import AgentEvent

from .event_lines import (
    _MAX_OUTPUT_CHARS,
    _clip,
    _format_args,
    _format_duration,
    format_event_line,
)

_ANSI = {
    "dim": "\033[2m",
    "bold": "\033[1m",
    "cyan": "\033[36m",
    "green": "\033[32m",
    "red": "\033[31m",
    "yellow": "\033[33m",
    "reset": "\033[0m",
}


class StreamRenderer:
    """Render a live event stream like Claude Code — tokens + tool cards.

    Text deltas print inline as they arrive; tool calls appear as cards
    between them, with proper newline handling either side::

        from shipit_agent import StreamRenderer

        renderer = StreamRenderer()
        for event in agent.stream("Close Q2 and hand me the workbook."):
            renderer.feed(event)
        renderer.close()

    ``style`` controls the look:

    - ``"auto"`` (default) — rich when writing to a TTY, plain otherwise
    - ``"rich"`` — Claude-Code-style ⏺/⎿ cards with ANSI colors
    - ``"plain"`` — the ⚙-card format with no escape codes

    Writes to ``sys.stdout`` by default; pass any ``write(str)``-able
    ``file`` (e.g. ``io.StringIO``) to capture instead.
    """

    def __init__(
        self,
        *,
        file: Any = None,
        show_summary: bool = True,
        show_tool_output: bool = True,
        style: str = "auto",
    ) -> None:
        import sys

        self._file = file or sys.stdout
        self._mid_text = False  # currently inside a streamed text line
        self._saw_delta = False
        self._show_summary = show_summary
        self._show_tool_output = show_tool_output
        self._streamed_tool_calls: set[str] = set()
        self._events: list[AgentEvent] = []
        if style == "auto":
            style = (
                "rich" if getattr(self._file, "isatty", lambda: False)() else "plain"
            )
        self._rich = style == "rich"

    def _c(self, color: str, text: str) -> str:
        """Wrap in ANSI color when rich mode is on."""
        if not self._rich:
            return text
        return f"{_ANSI[color]}{text}{_ANSI['reset']}"

    def _rich_line(self, event: AgentEvent) -> str | None:
        """Claude-Code-style ⏺/⎿ card line for one event."""
        p = event.payload
        if event.type == "skills_selected":
            line = format_event_line(event)
            return self._c("cyan", f"◈ {line}") if line else None
        if event.type == "agent_decision":
            summary = _clip(event.display_message, _MAX_OUTPUT_CHARS)
            return self._c("cyan", f"◆ {summary}") if summary else None
        if event.type == "agent_observation":
            summary = _clip(event.display_message, _MAX_OUTPUT_CHARS)
            return self._c("dim", f"  └ {summary}") if summary else None
        if event.type == "tool_called":
            name = self._c("bold", self._c("cyan", str(p.get("tool", "?"))))
            args = self._c("dim", _format_args(p.get("arguments")))
            return f"⏺ {name}({args})"
        if event.type == "tool_completed":
            dur = _format_duration(p.get("duration_ms"))
            status = self._c("green", "✓") + (self._c("dim", f" {dur}") if dur else "")
            preview = _clip(str(p.get("output", "")), _MAX_OUTPUT_CHARS)
            body = f"  ⎿ {preview} {status}" if preview else f"  ⎿ {status}"
            return body
        if event.type == "tool_failed":
            err = _clip(str(p.get("error", "")), _MAX_OUTPUT_CHARS)
            return f"  ⎿ {self._c('red', '✗ ' + err)}"
        if event.type == "tool_retry":
            return self._c("yellow", f"  ⎿ ↻ retry (attempt {p.get('attempt', '?')})")
        if event.type == "context_compacted":
            return self._c(
                "dim",
                f"◈ context compacted ({p.get('before')}→{p.get('after')} messages)",
            )
        if event.type == "run_cancelled":
            return self._c("yellow", "■ cancelled")
        return None

    def _write(self, text: str) -> None:
        self._file.write(text)
        flush = getattr(self._file, "flush", None)
        if flush is not None:
            flush()

    def _break_text(self) -> None:
        """End an in-progress token line before printing a card."""
        if self._mid_text:
            self._write("\n")
            self._mid_text = False

    def feed(self, event: AgentEvent) -> None:
        self._events.append(event)
        if event.type == "text_delta":
            chunk = str(event.payload.get("chunk", ""))
            if chunk:
                self._write(chunk)
                self._mid_text = True
                self._saw_delta = True
            return
        if event.type == "tool_output_delta" and self._show_tool_output:
            chunk = str(event.payload.get("chunk", ""))
            if chunk:
                self._break_text()
                tool = str(event.payload.get("tool", "?"))
                call_id = str(event.payload.get("call_id", "?"))
                self._streamed_tool_calls.add(call_id)
                prefix = self._c("dim", f"  {tool}[{call_id}] | ")
                rendered = chunk.replace("\n", "\n" + prefix).removesuffix(prefix)
                self._write(prefix + rendered)
                if not chunk.endswith("\n"):
                    self._write("\n")
            return
        if (
            event.type == "tool_completed"
            and str(event.payload.get("call_id", "?")) in self._streamed_tool_calls
        ):
            self._break_text()
            dur = _format_duration(event.payload.get("duration_ms"))
            status = "✓ tool completed" + (f" in {dur}" if dur else "")
            self._write(self._c("green", f"  {status}") + "\n")
            return
        line = self._rich_line(event) if self._rich else format_event_line(event)
        if line is not None:
            self._break_text()
            self._write(line + "\n")
        elif event.type == "run_completed":
            self._break_text()
            # If the adapter didn't stream tokens, the answer never printed
            # inline — show it now so the renderer works with every LLM.
            if not self._saw_delta:
                output = str(event.payload.get("output", "") or "")
                if output:
                    self._write(output + "\n")
            if self._show_summary:
                calls = sum(1 for e in self._events if e.type == "tool_called")
                failed = sum(1 for e in self._events if e.type == "tool_failed")
                footer = f"✔ done · {calls} tool call{'s' if calls != 1 else ''}"
                if failed:
                    footer += f" ({failed} failed)"
                self._write(self._c("green", footer) + "\n")

    def close(self) -> None:
        self._break_text()

    @property
    def events(self) -> list[AgentEvent]:
        return list(self._events)

