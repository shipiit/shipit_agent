"""SQL text helpers: read-only checks, comment stripping and result rendering."""

from __future__ import annotations

import base64
import re
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

_WRITE_KEYWORDS = (
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "CREATE",
    "TRUNCATE",
    "REPLACE",
    "GRANT",
    "REVOKE",
    "MERGE",
)


_WRITE_PATTERN = re.compile(
    r"\b(" + "|".join(_WRITE_KEYWORDS) + r")\b",
    re.IGNORECASE,
)


_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)


_LINE_COMMENT = re.compile(r"--[^\n]*")


def _strip_comments(sql: str) -> str:
    without_block = _BLOCK_COMMENT.sub(" ", sql)
    return _LINE_COMMENT.sub(" ", without_block)


def _is_read_only(sql: str) -> bool:
    """Return True iff ``sql`` is a single pure SELECT (or WITH...SELECT CTE).

    The check scans the *entire* cleaned statement (after comments and
    leading whitespace/semicolons are removed) and rejects it if any
    mutation keyword appears anywhere, or if it contains more than one
    statement (a ``;`` followed by additional non-empty SQL). Scanning the
    whole string — rather than just the head — closes the bypass where a
    trailing ``; DELETE ...`` rides past a long leading SELECT. The CTE form
    is accepted because ``WITH ... SELECT`` is still a read.

    A semicolon inside a string literal will be (conservatively) treated as a
    statement separator; this fails *safe* — it rejects a legitimate query
    rather than admitting a write.
    """
    if not sql or not sql.strip():
        return False

    cleaned = _strip_comments(sql).strip().lstrip(";").strip()
    if not cleaned:
        return False

    # Reject multiple statements: drop a single trailing ``;`` then split.
    # ``SELECT 1;`` → 1 segment (OK); ``SELECT 1; DELETE ...`` → 2 (reject).
    trimmed = cleaned.rstrip().rstrip(";").rstrip()
    segments = [seg for seg in trimmed.split(";") if seg.strip()]
    if len(segments) > 1:
        return False

    # If any write keyword appears as a whole word anywhere, reject.
    if _WRITE_PATTERN.search(cleaned):
        return False

    lowered = cleaned.lower()
    if lowered.startswith("select") or lowered.startswith("with") or lowered.startswith("("):
        return True
    # ``VALUES ...`` and ``TABLE foo`` are technically reads in some
    # dialects but we keep the whitelist tight — explicit SELECT/WITH/(
    # only.
    return False


def _jsonify(value: Any) -> Any:
    """Convert SQLAlchemy-returned scalars into JSON-safe values."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "base64:" + base64.b64encode(bytes(value)).decode("ascii")
    if isinstance(value, (list, tuple)):
        return [_jsonify(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonify(v) for k, v in value.items()}
    # Fall back to string for exotic types (UUID, Enum, etc).
    return str(value)


def _render_markdown_table(rows: list[dict[str, Any]], limit: int = 10) -> str:
    if not rows:
        return "(no rows)"
    columns = list(rows[0].keys())
    head = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    body_lines: list[str] = []
    for row in rows[:limit]:
        cells = [str(_jsonify(row.get(c, ""))) for c in columns]
        body_lines.append("| " + " | ".join(cells) + " |")
    tail = ""
    if len(rows) > limit:
        tail = f"\n... ({len(rows) - limit} more rows)"
    return "\n".join([head, sep, *body_lines]) + tail

