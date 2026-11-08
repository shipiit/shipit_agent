"""Value helpers for the PDF tool."""

from __future__ import annotations

from typing import Any


def _coerce_str(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return str(value)
    except Exception:
        return None

