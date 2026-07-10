"""Shared, clean tool-output formatting.

Long tool output (bash logs, greps, code stdout) shouldn't flood the model's
context — but a naive head-cut throws away the *tail*, which is usually where
the error message or exit status lives. :func:`clip_text` keeps both ends with a
clear omission marker, the way a good coding agent surfaces a long log::

    <first lines>

    … [output truncated — 340 lines omitted, showing head + tail] …

    <last lines>
"""

from __future__ import annotations

DEFAULT_MAX_CHARS = 30_000
DEFAULT_MAX_LINES = 400


def clip_text(
    text: str | None,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    max_lines: int = DEFAULT_MAX_LINES,
    head_ratio: float = 0.7,
) -> str:
    """Clip long text, preserving the head and the tail.

    Returns ``text`` unchanged when it's within both budgets. Otherwise keeps
    the first ``head_ratio`` of ``max_lines`` and the remaining lines from the
    end, with the middle replaced by a one-line marker; a final char-budget
    pass trims the head if the two ends together still exceed ``max_chars``.
    """
    if not text:
        return text or ""
    lines = text.splitlines()
    if len(text) <= max_chars and len(lines) <= max_lines:
        return text

    if len(lines) > max_lines:
        head_n = max(1, int(max_lines * head_ratio))
        tail_n = max(1, max_lines - head_n)
        head = "\n".join(lines[:head_n])
        tail = "\n".join(lines[-tail_n:])
        omitted_lines = len(lines) - head_n - tail_n
    else:
        head, tail, omitted_lines = text, "", 0

    # Char-budget pass: if head + tail still overflow, trim the head.
    if len(head) + len(tail) > max_chars:
        head = head[: max(0, max_chars - len(tail) - 120)].rstrip()

    if omitted_lines > 0:
        marker = (
            f"\n\n… [output truncated — {omitted_lines:,} lines omitted, "
            "showing head + tail] …\n\n"
        )
    else:
        marker = "\n\n… [output truncated] …\n\n"

    clipped = head + marker + tail if tail else head + marker
    return clipped.strip()
