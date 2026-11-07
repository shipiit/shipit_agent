"""Turning event payloads into plain, JSON-safe values."""

from __future__ import annotations

import json
from typing import Any



def _dump(value: Any) -> str:
    try:
        return json.dumps(value, indent=2, ensure_ascii=False, default=str)
    except (TypeError, ValueError):  # pragma: no cover - default= covers it
        return str(value)


def _jsonable(value: Any) -> Any:
    """Keep structure when it is already JSON, fall back to text when not.

    A tool's output is usually a string; when it happens to be JSON, a UI can
    render it as a table rather than a blob, so it is worth parsing.
    """
    if isinstance(value, (dict, list, int, float, bool)) or value is None:
        return value
    text = str(value)
    stripped = text.strip()
    if stripped[:1] in ("{", "[") and stripped[-1:] in ("}", "]"):
        try:
            return json.loads(stripped)
        except ValueError:
            return text
    return text


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
