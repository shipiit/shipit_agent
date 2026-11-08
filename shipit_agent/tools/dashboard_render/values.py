"""Escaping and value helpers for the dashboard renderer."""

from __future__ import annotations

import html
import re
from typing import Any

_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{3,8}$")


_BADGE_VARIANTS = {"blue", "green", "amber", "purple", "gray", "red"}


def _esc(text: Any) -> str:
    """HTML-escape anything. ``None`` renders as empty string so callers
    don't have to guard every optional field."""
    if text is None:
        return ""
    return html.escape(str(text), quote=True)


def _color(c: str | None, fallback: str = "#888888") -> str:
    """Return ``c`` if it's a safe hex color, otherwise ``fallback``.

    Belt-and-braces: we interpolate colors into inline ``style=``, and
    an attacker who controlled the spec could otherwise inject
    ``;background:url(javascript:…)``. Rejecting anything that isn't a
    hex triple keeps the XSS surface at zero.
    """
    if c and _HEX_COLOR.match(c):
        return c
    return fallback


def _pct(v: Any, default: float = 0.0) -> float:
    """Clamp any numeric-ish input into [0, 100]."""
    try:
        n = float(v)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(100.0, n))

