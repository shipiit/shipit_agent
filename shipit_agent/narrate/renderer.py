"""The Narrator's terminal renderer.

Renders a run the way Cloudflare OS renders one: prose is the content, work is
a quiet one-line receipt underneath it, and the whole thing closes with the
bill::

      ⌕ 3 resource reads                                       ›
        Enterprise Accounts · Open Tickets · Usage by Account

      Let me look at usage trends, open tickets and renewal dates together.

      ❯ Ran code const risk = scoreAccounts(usa…                ›

      Three I would put on your list:
        • Northwind: usage down 38% since March, renews in six weeks.

                                             18,240 tokens · $0.12

Usage::

    from shipit_agent.narrate import NarratorRenderer

    renderer = NarratorRenderer()
    for event in agent.stream("Which accounts are at risk?"):
        renderer.feed(event)
    renderer.close()

On a terminal the in-flight row updates **in place** in the present tense
(``Reading app.py`` → ``Read app.py``). Piped to a file or a CI log it buffers
and prints only the settled past-tense row — no escape codes, no cursor
motion, byte-for-byte stable output.
"""

from __future__ import annotations

import os
import sys
from typing import Any

from shipit_agent.models import AgentEvent

from .grouping import (
    ApprovalRow,
    NoticeRow,
    ProseRow,
    WorkGroup,
    WorkRow,
    WorkRunAccumulator,
)
from .verbs import ASCII_ICONS

__all__ = ["NarratorRenderer", "render_transcript", "LiveRegion"]

_ANSI = {
    "dim": "\033[2m",
    "bold": "\033[1m",
    "accent": "\033[38;5;209m",  # the warm orange the reference UI uses
    "green": "\033[32m",
    "red": "\033[31m",
    "reset": "\033[0m",
}

_GUTTER = "  "
_EXPAND_HINT = "›"


def _supports_unicode(stream: Any) -> bool:
    encoding = getattr(stream, "encoding", None) or ""
    if not encoding:
        return True  # StringIO and friends handle anything
    try:
        "⌕›·".encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return False
    return True


def _terminal_width(default: int = 80) -> int:
    try:
        return max(40, os.get_terminal_size().columns)
    except OSError:
        return default


class LiveRegion:
    """A block of lines that can be redrawn in place.

    Tracks how many lines it last wrote and rewinds over exactly those before
    writing again. A no-op when the stream isn't a terminal, which is what
    keeps piped output clean.
    """

    def __init__(self, write: Any, *, enabled: bool) -> None:
        self._write = write
        self._enabled = enabled
        self._lines = 0

    @property
    def active(self) -> bool:
        return self._lines > 0

    def draw(self, lines: list[str]) -> None:
        if not self._enabled:
            return
        self.clear()
        if not lines:
            return
        self._write("\n".join(lines) + "\n")
        self._lines = len(lines)

    def clear(self) -> None:
        """Erase what we drew, leaving the cursor where we started."""
        if not self._enabled or self._lines == 0:
            return
        # Up N lines, then erase from the cursor to the end of the screen.
        self._write(f"\033[{self._lines}A\033[J")
        self._lines = 0


class NarratorRenderer:
    """Render a live ``agent.stream(...)`` in the modern transcript style.

    ``style`` selects the look:

    - ``"auto"`` (default) — live in-place rows on a TTY, buffered otherwise
    - ``"live"`` — force in-place updates
    - ``"plain"`` — force buffered, no escape codes

    Pass ``file=`` to redirect (anything with ``write``). ``show_footer=False``
    drops the tokens/cost line.
    """

    def __init__(
        self,
        *,
        file: Any = None,
        style: str = "auto",
        show_footer: bool = True,
        model: str | None = None,
        cost_tracker: Any = None,
    ) -> None:
        self._file = file if file is not None else sys.stdout
        is_tty = bool(getattr(self._file, "isatty", lambda: False)())
        no_color = bool(os.environ.get("NO_COLOR"))
        force_color = bool(os.environ.get("FORCE_COLOR"))

        if style == "auto":
            live = is_tty
        else:
            live = style == "live"

        self._live_enabled = live
        self._color = (is_tty or force_color or style == "live") and not no_color
        self._unicode = _supports_unicode(self._file)
        self._show_footer = show_footer
        self._model = model
        self._cost_tracker = cost_tracker

        self._acc = WorkRunAccumulator()
        self._region = LiveRegion(self._raw_write, enabled=live)
        self._wrote_anything = False

    # ── plumbing ─────────────────────────────────────────────────────────

    def _raw_write(self, text: str) -> None:
        self._file.write(text)
        flush = getattr(self._file, "flush", None)
        if flush is not None:
            flush()

    def _write(self, text: str) -> None:
        self._raw_write(text)
        self._wrote_anything = True

    def _c(self, color: str, text: str) -> str:
        if not self._color or not text:
            return text
        return f"{_ANSI[color]}{text}{_ANSI['reset']}"

    def _glyph(self, icon: str) -> str:
        return icon if self._unicode else ASCII_ICONS.get(icon, "+")

    def _hint(self) -> str:
        return _EXPAND_HINT if self._unicode else ">"

    def _sep(self) -> str:
        return " · " if self._unicode else " | "

    # ── row rendering ────────────────────────────────────────────────────

    def _work_lines(self, group: WorkGroup, *, present: bool = False) -> list[str]:
        """One work row: gutter glyph, label, expand hint, optional details."""
        icon = self._c("dim", self._glyph(group.icon))
        label = group.label
        if group.has_error:
            label = f"{label} {self._c('red', '✗' if self._unicode else 'x')}"
        elif present:
            label = self._c("accent", label)

        head = f"{_GUTTER}{icon} {label} {self._c('dim', self._hint())}"
        lines = [head]
        if group.detail_lines:
            joined = self._sep().join(group.detail_lines)
            width = _terminal_width() - len(_GUTTER) - 4
            if len(joined) > width:
                joined = joined[: max(0, width - 1)] + ("…" if self._unicode else "...")
            lines.append(f"{_GUTTER}  {self._c('dim', joined)}")
        return lines

    def _emit_row(self, row: Any) -> None:
        if isinstance(row, WorkRow):
            for line in self._work_lines(row.group):
                self._write(line + "\n")
        elif isinstance(row, ProseRow):
            self._write("\n" + row.text.strip() + "\n\n")
        elif isinstance(row, ApprovalRow):
            for line in self._approval_lines(row):
                self._write(line + "\n")
        elif isinstance(row, NoticeRow):
            mark = "◈" if self._unicode else "-"
            self._write(f"{_GUTTER}{self._c('dim', f'{mark} {row.text}')}\n")

    def _approval_lines(self, row: ApprovalRow) -> list[str]:
        """A pending decision, or a note that a rule already covered it."""
        bullet = "●" if self._unicode else "*"
        if row.auto_approved:
            mark = "✓" if self._unicode else "v"
            return [
                f"{_GUTTER}{self._c('dim', mark)} "
                f"{self._c('dim', row.title + '  (auto-approved)')}"
            ]
        lines = [f"{_GUTTER}{self._c('accent', bullet)} {row.title}"]
        if row.tag:
            lines.append(f"{_GUTTER}  {self._c('dim', f'#{row.action_id} · {row.tag}')}")
        lines.append(
            f"{_GUTTER}  {self._c('dim', 'Always approve   Deny   ')}"
            + self._c("bold", "Approve")
        )
        return lines

    # ── the live row ─────────────────────────────────────────────────────

    def _redraw_pending(self) -> None:
        if not self._live_enabled:
            return
        pending = self._acc.pending
        self._region.draw(
            self._work_lines(pending, present=True) if pending is not None else []
        )

    # ── public ───────────────────────────────────────────────────────────

    def feed(self, event: AgentEvent) -> None:
        """Consume one ``AgentEvent``."""
        # Settled rows must land above the live region, so clear it first.
        self._region.clear()
        for row in self._acc.feed(event):
            self._emit_row(row)
        self._redraw_pending()

    def close(self) -> None:
        """Flush anything buffered and print the footer."""
        self._region.clear()
        for row in self._acc.finish():
            self._emit_row(row)
        if self._show_footer:
            footer = self._footer()
            if footer:
                self._write(footer + "\n")

    def _footer(self) -> str:
        """``18,240 tokens · $0.12 · claude-opus-5``, right-aligned and dim."""
        usage = self._acc.usage or {}
        tokens = int(usage.get("total_tokens") or 0)
        if not tokens:
            tokens = int(usage.get("prompt_tokens") or 0) + int(
                usage.get("completion_tokens") or 0
            )
        parts: list[str] = []
        if tokens:
            parts.append(f"{tokens:,} tokens")
        cost = self._cost()
        if cost is not None:
            parts.append(f"${cost:,.2f}" if cost >= 0.01 else f"${cost:.4f}")
        if self._model:
            parts.append(self._model)
        if not parts:
            return ""
        text = self._sep().join(parts)
        pad = max(0, _terminal_width() - len(text) - 2)
        return " " * pad + self._c("dim", text)

    def _cost(self) -> float | None:
        """Run cost in USD, when a tracker was supplied and knows the model."""
        tracker = self._cost_tracker
        if tracker is None:
            return None
        usage = self._acc.usage or {}
        try:
            if self._model:
                return float(
                    tracker.calculate_cost(
                        model=self._model,
                        input_tokens=int(usage.get("prompt_tokens") or 0),
                        output_tokens=int(usage.get("completion_tokens") or 0),
                    )
                )
            return float(tracker.total_cost())
        except Exception:
            # A missing price or an unexpected tracker shape must never take
            # the transcript down — just omit the dollar figure.
            return None

    @property
    def rows(self) -> list[Any]:
        return self._acc.rows


def render_transcript(
    source: Any,
    *,
    model: str | None = None,
    cost_tracker: Any = None,
    width: int | None = None,
) -> str:
    """Render a finished run as a plain-text transcript.

    The offline counterpart to :class:`NarratorRenderer` — same rows, same
    labels, no escape codes. Useful for logs, tests, and ``--share`` output::

        print(render_transcript(agent.run("...")))
    """
    import io

    buffer = io.StringIO()
    renderer = NarratorRenderer(
        file=buffer, style="plain", model=model, cost_tracker=cost_tracker
    )
    for event in getattr(source, "events", source):
        renderer.feed(event)
    renderer.close()
    return buffer.getvalue()
