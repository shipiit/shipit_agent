"""CLI UI kit — modern, minimal, terminal-safe.

One `style()` code path (no-op when color is off), `NO_COLOR`/`FORCE_COLOR`
respected before `isatty()`, and printing that can never crash a launch on
a weird terminal encoding.
"""

from __future__ import annotations

import os
import sys

# 256-color palette, named — one place to retheme the whole CLI.
PALETTE = {
    "title": "38;5;117;1",     # bright sky, bold
    "accent": "38;5;141",      # violet
    "ok": "38;5;114",          # green
    "warn": "38;5;215",        # amber
    "err": "38;5;203",         # red
    "dim": "38;5;245",         # grey
    "url": "38;5;108;1",       # sage, bold
    "bold": "1",
}


def supports_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    try:
        return sys.stdout.isatty()
    except Exception:
        return False


def style(text: str, name: str) -> str:
    if not supports_color():
        return text
    return f"\033[{PALETTE.get(name, '0')}m{text}\033[0m"


def out(text: str = "") -> None:
    """Print that survives any terminal encoding."""
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", errors="replace").decode("ascii"))


def rule(width: int = 56) -> None:
    out(style("─" * width, "dim"))


def banner(title: str, rows: list[tuple[str, str]], *, emoji: str = "🚀") -> None:
    """Audience-bucketed info banner."""
    out()
    out(style(f"{emoji} {title}", "title"))
    rule()
    for label, value in rows:
        out(f"  {style(label, 'dim'):<34} {style(value, 'bold')}")
    rule()


def section(title: str) -> None:
    out()
    out(style(title, "accent"))


def kv(label: str, value: str, *, tone: str = "bold") -> None:
    out(f"  {style(label, 'dim'):<34} {style(value, tone)}")
