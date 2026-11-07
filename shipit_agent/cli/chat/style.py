"""Terminal colour, event lines, the typewriter effect and the spinner."""

from __future__ import annotations

import itertools
import sys
import threading
import time
from typing import Any

_USE_COLOR = sys.stdout.isatty()


def _ansi(text: str, code: str) -> str:
    if not _USE_COLOR:
        return text
    return f"\x1b[{code}m{text}\x1b[0m"


def dim(t: str) -> str:
    """*text* in the terminal's dim style."""
    return _ansi(t, "2")


def bold(t: str) -> str:
    """*text* in bold."""
    return _ansi(t, "1")


def cyan(t: str) -> str:
    """*text* in cyan."""
    return _ansi(t, "36")


def green(t: str) -> str:
    """*text* in green."""
    return _ansi(t, "32")


def yellow(t: str) -> str:
    """*text* in yellow."""
    return _ansi(t, "33")


def red(t: str) -> str:
    """*text* in red."""
    return _ansi(t, "31")


def magenta(t: str) -> str:
    """*text* in magenta."""
    return _ansi(t, "35")


def blue(t: str) -> str:
    """*text* in blue."""
    return _ansi(t, "34")


def banner(title: str, subtitle: str = "") -> str:
    """A boxed title (and optional subtitle) for the top of the chat."""
    width = max(len(title), len(subtitle)) + 4
    top = "╭" + "─" * (width - 2) + "╮"
    bot = "╰" + "─" * (width - 2) + "╯"
    parts = [magenta(top), magenta("│ ") + bold(title.ljust(width - 4)) + magenta(" │")]
    if subtitle:
        parts.append(magenta("│ ") + dim(subtitle.ljust(width - 4)) + magenta(" │"))
    parts.append(magenta(bot))
    return "\n".join(parts)


EVENT_STYLE: dict[str, tuple[str, str]] = {
    "run_started": ("▶", "34"),
    "reasoning_started": ("✧", "35"),
    "reasoning_completed": ("✓", "35"),
    "step_started": ("·", "2"),
    "planning_started": ("◐", "33"),
    "planning_completed": ("◑", "33"),
    "tool_called": ("⚙", "36"),
    "tool_completed": ("✓", "32"),
    "tool_failed": ("✗", "31"),
    "mcp_attached": ("⧉", "34"),
    "llm_retry": ("↻", "33"),
    "tool_retry": ("↻", "33"),
    "interactive_request": ("?", "33"),
    "context_snapshot": ("◆", "2"),
    "rag_sources": ("❀", "35"),
    "run_completed": ("■", "32"),
}


def format_event(event: Any) -> str:
    """One run event as a single styled terminal line."""
    etype = getattr(event, "type", "event")
    icon, color = EVENT_STYLE.get(etype, ("·", "2"))
    msg = getattr(event, "message", "") or ""
    payload = getattr(event, "payload", {}) or {}
    extra = ""
    if etype == "tool_called":
        name = payload.get("name") or payload.get("tool") or ""
        if name:
            extra = dim(f"  → {name}")
    elif etype == "tool_completed":
        name = payload.get("name") or payload.get("tool") or ""
        if name:
            extra = dim(f"  ← {name}")
    elif etype == "tool_failed":
        err = payload.get("error", "")
        extra = dim(f"  {str(err)[:60]}")
    return f"  {_ansi(icon, color)} {_ansi(etype, '2')} {msg}{extra}"


def typewriter(
    text: str,
    *,
    output,
    chunk_size: int = 3,
    delay: float = 0.012,
    enabled: bool = True,
) -> None:
    """Print text with a gentle typewriter effect when writing to a TTY."""
    if not text:
        return
    if not enabled or not _USE_COLOR:
        output(text)
        return
    try:
        for i in range(0, len(text), chunk_size):
            sys.stdout.write(text[i : i + chunk_size])
            sys.stdout.flush()
            time.sleep(delay)
        sys.stdout.write("\n")
        sys.stdout.flush()
    except Exception:
        output(text)


class Spinner:
    """Lightweight single-line activity indicator for TTYs."""

    _FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, label: str = "thinking") -> None:
        self.label = label
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._enabled = _USE_COLOR and sys.stdout.isatty()

    def _run(self) -> None:
        it = itertools.cycle(self._FRAMES)
        while not self._stop.is_set():
            frame = next(it)
            try:
                sys.stdout.write(f"\r  {magenta(frame)} {dim(self.label)}   ")
                sys.stdout.flush()
            except Exception:
                return
            time.sleep(0.08)
        try:
            sys.stdout.write("\r" + " " * (len(self.label) + 8) + "\r")
            sys.stdout.flush()
        except Exception:
            pass

    def start(self) -> None:
        if not self._enabled:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def update(self, label: str) -> None:
        self.label = label

    def stop(self) -> None:
        if not self._enabled:
            return
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=0.5)
