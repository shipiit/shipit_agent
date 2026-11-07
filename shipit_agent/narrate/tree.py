"""The run as a tree — structure over prose.

The default Narrator reads like a colleague talking: prose is the content and
work is a quiet receipt underneath it. That is right when you are reading the
*answer*.

Sometimes you want the opposite — the *shape* of the run, with every call
named and its status beside it. Debugging a tool that fired twice, explaining
what an agent did, or watching a long autonomous run: for those, a tree beats
a transcript::

    Agent started
    │
    ├─ Decision
    │  The RSVP details were extracted. Now check for an existing record.
    │
    ├─ Tool group: Read 2 files
    │  ├─ read_file                                    completed   4ms
    │  └─ read_file                                    completed    6ms
    │
    ├─ Approval required
    │  Used Slack #eng                                 comms.send
    │
    └─ Final answer
       RSVP successfully recorded.

Same rows, same grouping, same verbs as :class:`NarratorRenderer` — this only
changes the shape. Select it with ``agent.run_live(style="tree")``.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any

from shipit_agent.core.models import AgentEvent

from .grouping import (
    ProseRow,
    WorkRow,
    WorkRunAccumulator,
)
from .renderer import LiveRegion
from .tree_rows import TreeRowsMixin

__all__ = ["TreeRenderer", "render_tree"]

_ANSI = {
    "dim": "\033[2m",
    "bold": "\033[1m",
    "accent": "\033[38;5;209m",
    "green": "\033[32m",
    "red": "\033[31m",
    "reset": "\033[0m",
}


# Events that change the shape of the tree rather than extend a line of prose.
# Nobody should wait for a throttle to learn that a tool started.
_STRUCTURAL = frozenset(
    {
        "tool_called",
        "tool_completed",
        "tool_failed",
        "tool_denied",
        "action_queued",
        "sub_agent_event",
        "run_completed",
    }
)



class TreeRenderer(TreeRowsMixin):
    """Render a run as a tree of decisions and tool groups.

    On a terminal it redraws **in place** as the run proceeds: the tree grows
    downward, statuses flip from ``running`` to ``completed`` where they
    stand, and the trunk stays open (``├─ working…``) until the run ends —
    drawing the final corner early would claim the agent had finished. When
    the run closes, the draft is erased and the finished tree written once,
    so the scrollback holds one clean copy.

    Pass ``live=False`` for a single buffered write (what piped output and
    notebooks get by default), or ``live=True`` to force in-place updates.
    """

    def __init__(
        self,
        *,
        file: Any = None,
        color: bool | None = None,
        show_footer: bool = True,
        model: str | None = None,
        detail: bool = False,
        output_lines: int | None = 6,
        live: bool | None = None,
        min_interval: float = 0.08,
        accumulator: WorkRunAccumulator | None = None,
    ) -> None:
        self._file = file if file is not None else sys.stdout
        is_tty = bool(getattr(self._file, "isatty", lambda: False)())
        no_color = bool(os.environ.get("NO_COLOR"))
        self._color = (is_tty if color is None else color) and not no_color
        self._unicode = self._supports_unicode()
        self._show_footer = show_footer
        self._model = model
        self._detail = detail
        self._output_lines = output_lines
        # A caller that already feeds an accumulator (the notebook panel does)
        # passes it in, so one run is never accumulated twice.
        self._acc = accumulator if accumulator is not None else WorkRunAccumulator()
        self._owns_accumulator = accumulator is None
        # Redrawing in place needs a terminal to rewind over; piped output
        # would otherwise collect one copy of the tree per event.
        self._region = (
            LiveRegion(self._write, enabled=True)
            if (is_tty if live is None else live)
            else None
        )
        self._min_interval = min_interval
        self._last_draw = 0.0

    def _supports_unicode(self) -> bool:
        encoding = getattr(self._file, "encoding", None) or ""
        if not encoding:
            return True
        try:
            "│├└─".encode(encoding)
        except (UnicodeEncodeError, LookupError):
            return False
        return True

    # ── glyphs ───────────────────────────────────────────────────────────

    @property
    def _pipe(self) -> str:
        return "│" if self._unicode else "|"

    @property
    def _tee(self) -> str:
        return "├─" if self._unicode else "+-"

    @property
    def _corner(self) -> str:
        return "└─" if self._unicode else "`-"

    def _c(self, color: str, text: str) -> str:
        if not self._color or not text:
            return text
        return f"{_ANSI[color]}{text}{_ANSI['reset']}"

    # ── ingest ───────────────────────────────────────────────────────────

    def feed(self, event: AgentEvent) -> None:
        self._acc.feed(event)
        if self._region is not None:
            now = time.monotonic()
            structural = event.type in _STRUCTURAL
            if structural or (now - self._last_draw) >= self._min_interval:
                self._last_draw = now
                self._region.draw(self.render(live=True).splitlines())

    def close(self) -> None:
        if self._owns_accumulator:
            self._acc.finish()
        if self._region is not None:
            # Erase the growing draft and write the finished tree once, so the
            # scrollback holds one clean copy rather than every intermediate.
            self._region.clear()
        self._write(self.render())

    def _write(self, text: str) -> None:
        self._file.write(text)
        flush = getattr(self._file, "flush", None)
        if flush is not None:
            flush()

    # ── render ───────────────────────────────────────────────────────────

    def render(self, *, live: bool = False) -> str:
        """The tree as text.

        ``live=True`` includes the work that has not settled yet and leaves
        the trunk open at the bottom — the run is not over, so drawing the
        final corner would be a lie.
        """
        source = self._acc.live_rows() if live else self._acc.rows
        rows = [r for r in source if not _is_empty(r)]
        lines: list[str] = [self._c("bold", "Agent started")]

        # The last prose row is the answer; everything before it is a step
        # along the way. Naming them differently is the whole point of the
        # tree — you can see where the agent *decided* something. While the
        # run is live there is no answer yet: the last prose is still a step.
        last_prose = (
            -1
            if live
            else max(
                (i for i, r in enumerate(rows) if isinstance(r, ProseRow)), default=-1
            )
        )
        # The opening prose — before any tool has run — is the agent saying
        # what it is about to do, not a decision it reached.
        first_prose = next(
            (i for i, r in enumerate(rows) if isinstance(r, ProseRow)), -1
        )
        opening = first_prose if first_prose == 0 and last_prose != 0 else -1

        for index, row in enumerate(rows):
            last = index == len(rows) - 1 and not live
            branch = self._corner if last else self._tee
            # A trunk under every branch except the final one.
            trunk = "   " if last else f"{self._pipe}  "
            lines.append(self._pipe)
            lines.extend(
                self._render_row(
                    row,
                    branch,
                    trunk,
                    is_answer=index == last_prose,
                    is_opening=index == opening,
                )
            )

        if live:
            # An open trunk: more is coming.
            lines.append(self._pipe)
            lines.append(self._c("dim", f"{self._tee} working…"))
            return "\n".join(lines) + "\n"

        if self._show_footer:
            footer = self._footer()
            if footer:
                lines.append("")
                lines.append(footer)
        return "\n".join(lines) + "\n"


def _is_empty(row: Any) -> bool:
    if isinstance(row, ProseRow):
        return not row.text.strip()
    if isinstance(row, WorkRow):
        return not row.group.calls
    return False


def render_tree(
    source: Any,
    *,
    model: str | None = None,
    detail: bool = False,
    output_lines: int | None = 6,
) -> str:
    """Render a finished run as a tree, with no escape codes.

    ::

        print(render_tree(result))

    ``detail=True`` opens every call up — the arguments it was called with and
    the first lines of what came back::

        ├─ Tool group: Searched for def summarize
        │  └─ grep_files                              completed  204ms
        │     ↳ pattern='def summarize', path='shipit_agent'
        │       shipit_agent/narrate/verbs.py:589:def summarize(name: str, …
    """
    import io

    buffer = io.StringIO()
    renderer = TreeRenderer(
        file=buffer,
        color=False,
        model=model,
        detail=detail,
        output_lines=output_lines,
    )
    for event in getattr(source, "events", source):
        renderer.feed(event)
    renderer.close()
    return buffer.getvalue()
