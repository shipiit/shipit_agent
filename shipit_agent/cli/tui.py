"""Bottom-pinned terminal layout — chat scrolls, the input never moves.

Uses the VT100 scroll-region (``ESC[{top};{bottom}r``) so the terminal
itself does the scrolling: all agent output flows inside rows
``1..height-2``, a rule sits at ``height-1``, and the prompt lives on the
last row — the Claude-Code layout, in ~100 lines of stdlib.

    with BottomInputTerminal() as term:
        while True:
            line = term.read("you ▸ ")
            term.print(f"agent ▸ {line}")

Degrades transparently: when stdout isn't a TTY (pipes, CI, tests) every
call falls back to plain ``print``/``input`` — same API, no escape codes.
"""

from __future__ import annotations

import os
import shutil
import sys
from typing import Any

_ESC = "\033"


class BottomInputTerminal:
    """Scroll-region layout: output above, a rule, input pinned at bottom."""

    def __init__(self, *, stream: Any = None, enabled: bool | None = None) -> None:
        self._out = stream or sys.stdout
        if enabled is None:
            try:
                enabled = self._out.isatty() and not os.environ.get("SHIPIT_NO_TUI")
            except Exception:
                enabled = False
        self.enabled = bool(enabled)
        self._rows = 0
        self._cols = 0

    # ── lifecycle ─────────────────────────────────────────────────────
    def start(self) -> "BottomInputTerminal":
        if not self.enabled:
            return self
        size = shutil.get_terminal_size(fallback=(80, 24))
        self._rows, self._cols = size.lines, size.columns
        if self._rows < 6:  # tiny panes: not worth a layout
            self.enabled = False
            return self
        w = self._out.write
        w(f"{_ESC}[2J")                                # clear screen
        w(f"{_ESC}[1;{self._rows - 2}r")               # scroll region = chat
        w(f"{_ESC}[{self._rows - 1};1H")               # draw the rule
        w("\x1b[2m" + "─" * self._cols + "\x1b[0m")
        w(f"{_ESC}[{self._rows - 2};1H")               # park cursor in chat
        self._out.flush()
        return self

    def stop(self) -> None:
        if not self.enabled:
            return
        w = self._out.write
        w(f"{_ESC}[r")                                 # reset scroll region
        w(f"{_ESC}[{self._rows};1H\n")                 # leave cursor sane
        self._out.flush()

    def __enter__(self) -> "BottomInputTerminal":
        return self.start()

    def __exit__(self, *_exc: Any) -> None:
        self.stop()

    # ── I/O ───────────────────────────────────────────────────────────
    def print(self, text: str = "") -> None:
        """Write into the scrolling chat region."""
        if not self.enabled:
            print(text, file=self._out)
            return
        w = self._out.write
        w(f"{_ESC}[{self._rows - 2};1H")               # bottom of chat region
        for line in (text.split("\n") if text else [""]):
            w("\n" + line)                             # \n scrolls the region
        self._out.flush()

    def write(self, text: str) -> None:
        """Stream-friendly write (token deltas) into the chat region."""
        if not self.enabled:
            self._out.write(text)
            self._out.flush()
            return
        self._out.write(text)
        self._out.flush()

    def read(self, prompt: str = "▸ ") -> str:
        """Read a line from the pinned bottom row."""
        if not self.enabled:
            return input(prompt)
        w = self._out.write
        w(f"{_ESC}[{self._rows};1H{_ESC}[2K")          # jump + clear input row
        self._out.flush()
        try:
            line = input(prompt)
        finally:
            w(f"{_ESC}[{self._rows};1H{_ESC}[2K")      # clear the typed line
            w(f"{_ESC}[{self._rows - 2};1H")           # back to the chat region
            self._out.flush()
        return line
