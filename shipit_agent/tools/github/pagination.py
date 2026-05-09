from __future__ import annotations

import re

_LINK_ENTRY_RE = re.compile(r"<([^>]+)>\s*;\s*rel=\"([^\"]+)\"")


def parse_next_url(link_header: str | None) -> str | None:
    """Return the URL for rel=\"next\" from a GitHub Link header, or None.

    GitHub's Link header looks like:
        <https://api.github.com/...&page=2>; rel="next", <...&page=5>; rel="last"

    We only return the URL for the ``next`` relation. If no ``next`` rel is
    present (e.g. only ``last`` and ``first``, or an empty/None input), this
    returns ``None``.
    """
    if not link_header:
        return None
    for url, rel in _LINK_ENTRY_RE.findall(link_header):
        if rel.strip() == "next":
            return url.strip()
    return None
