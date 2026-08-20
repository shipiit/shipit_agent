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
