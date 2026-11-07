"""Terminal helpers for the transcript: colours, glyph support, width, and a redrawable block."""

from __future__ import annotations

import os
from typing import Any

_ANSI = {
    "dim": "\033[2m",
    "bold": "\033[1m",
    "accent": "\033[38;5;209m",  # the warm orange the reference UI uses
    "green": "\033[32m",
    "red": "\033[31m",
    "reset": "\033[0m",
}


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
