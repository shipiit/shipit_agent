"""Provider-neutral detection of unparsed model action attempts."""

from __future__ import annotations

import re
import unicodedata
from typing import Sequence

_IDENTIFIER = r"[A-Za-z_][A-Za-z0-9_.-]*"
_NAMED_OBJECT = re.compile(
    rf"(?<![A-Za-z0-9_])({_IDENTIFIER})\s*(?:\(|:|=)?\s*\{{",
    re.MULTILINE,
)
_ANGLE_FORM = re.compile(rf"<\s*/?\s*({_IDENTIFIER})(?:\s|>|$)")
_REPEATED_SUFFIX = re.compile(r"(.{4,128}?)(?:\1){7,}$", re.DOTALL)


def _has_periodic_tail(text: str) -> bool:
    """Detect alternating/repeating prose blocks without knowing their words.

    Degenerate generations are not always one repeated token sequence.  A
    model may alternate two or three complete sentences (A, B, A, B, ...),
    which defeats a character-suffix detector while consuming the whole output
    budget.  Look for any short period repeated four times at the end.  Long
    blocks are required so ordinary short lists and punctuation cannot trip it.
    """
    blocks = [
        " ".join(block.split())
        for block in re.split(r"(?:\n\s*){2,}|(?<=[.!?])\s+", text)
        if len(" ".join(block.split())) >= 24
    ]
    for period in range(1, min(6, len(blocks) // 4) + 1):
        width = period * 4
        tail = blocks[-width:]
        if tail == tail[:period] * 4:
            return True
    return False


class RepetitionGuard:
    """Incrementally detect a provider stuck repeating an arbitrary suffix.

    The detector knows nothing about model families, tags, or tool syntax. It
    normalizes whitespace and looks only for the same 4–128 character unit at
    least eight times at the end of a bounded rolling window.
    """

    def __init__(self, *, window: int = 4096) -> None:
        self.window = window
        self._text = ""

    def add(self, chunk: str) -> bool:
        self._text = (self._text + str(chunk))[-self.window :]
        compact = " ".join(self._text.split())
        return len(compact) >= 32 and (
            _REPEATED_SUFFIX.search(compact) is not None
            or _has_periodic_tail(self._text)
        )


def is_degenerate_repetition(text: str | None) -> bool:
    guard = RepetitionGuard(window=8192)
    return guard.add(text or "")


def is_malformed_action_attempt(
    text: str | None, *, allowed_names: Sequence[str] = ()
) -> bool:
    """Detect call grammar that failed to parse, without provider markers.

    This only identifies recovery candidates. Tool-call healing separately
    validates names and arguments against the advertised schemas before any
    action can execute.
    """
    raw_source = text or ""
    source = raw_source.strip()
    if not source:
        return False

    advertised = {name for name in allowed_names if name}
    if advertised and is_degenerate_repetition(source):
        return True

    compact = " ".join(source.split())
    if (
        advertised
        and len(raw_source) >= 256
        and len(compact) <= 300
        and len(raw_source) >= max(1, len(compact)) * 3
    ):
        return True

    for match in _NAMED_OBJECT.finditer(source):
        if not advertised or match.group(1) in advertised:
            return True

    if advertised:
        names = "|".join(
            re.escape(name) for name in sorted(advertised, key=len, reverse=True)
        )
        if re.search(rf"(?<![A-Za-z0-9_])(?:{names})\s*(?:\(|\{{|:|=)", source):
            return True
        code_formatted_name = re.search(rf"`(?:{names})`", source)
        if code_formatted_name and not unicodedata.category(source[-1]).startswith(
            "P"
        ):
            return True

    return bool(_ANGLE_FORM.search(source)) and source.count("<") != source.count(">")
