"""Resource catalogs — bounded discovery, re-validated on our side.

A binding's *catalog* is a short index of what is reachable through it: the
repos you can see, the tables in the warehouse, the documents in a knowledge
collection. It goes in the system prompt so the agent knows what exists without
paging an API, and it is deliberately small — a catalog is a table of contents,
not the book.

The security property is the reason this module exists rather than being three
lines inline. Cloudflare OS re-validates every catalog **workshop-side**, and
says why in one line: *"the gatekeeper output is untrusted."* A catalog is
text from a third-party service that lands directly in the system prompt of a
tool-using agent. That is a prompt-injection surface, and the connector is not
the right place to defend it — a compromised or merely sloppy connector is
exactly the threat.

So :func:`normalize_catalog` runs on our side of the boundary regardless of
what the connector already did:

- control characters stripped, whitespace collapsed
- each field clamped to a hard length
- entries with no usable id or title dropped
- deterministic sort, so an unstable upstream can't reorder the prompt
- a hard cap on entry count, with the truncation made visible
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

__all__ = [
    "CatalogEntry",
    "ResourceCatalog",
    "normalize_catalog",
    "MAX_ENTRIES",
    "MAX_ID_LENGTH",
    "MAX_TITLE_LENGTH",
    "MAX_DESCRIPTION_LENGTH",
]

# Hard bounds. A catalog is a table of contents; anything longer belongs behind
# a method call, not in every prompt for the rest of the run.
MAX_ENTRIES = 50
MAX_ID_LENGTH = 128
MAX_TITLE_LENGTH = 120
MAX_DESCRIPTION_LENGTH = 240

# Unicode control characters, including the bidi and zero-width tricks that
# make injected text render differently from how it tokenizes.
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f​-‏ -‮⁦-⁩]")
_WHITESPACE = re.compile(r"\s+")


def _clean(value: Any, max_length: int) -> str:
    """Strip control characters, collapse whitespace, clamp length."""
    text = _CONTROL.sub(" ", str(value if value is not None else ""))
    text = _WHITESPACE.sub(" ", text).strip()
    return text[:max_length]


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """One reachable thing, as the agent sees it."""

    id: str
    title: str
    description: str = ""

    def render(self) -> str:
        line = f"  - {self.id}: {self.title}"
        return f"{line} — {self.description}" if self.description else line


@dataclass(slots=True)
class ResourceCatalog:
    """A bounded index of what a binding can reach."""

    entries: list[CatalogEntry] = field(default_factory=list)
    truncated: bool = False

    def __len__(self) -> int:
        return len(self.entries)

    def __bool__(self) -> bool:
        return bool(self.entries)

    def render(self) -> str:
        """The prompt fragment. Empty string when there is nothing to say."""
        if not self.entries:
            return ""
        lines = [entry.render() for entry in self.entries]
        if self.truncated:
            lines.append(
                f"  … list truncated at {MAX_ENTRIES}; query the binding for more"
            )
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entries": [
                {"id": e.id, "title": e.title, "description": e.description}
                for e in self.entries
            ],
            "truncated": self.truncated,
        }


def normalize_catalog(raw: Any) -> ResourceCatalog:
    """Sanitize untrusted catalog data into a :class:`ResourceCatalog`.

    Accepts whatever a connector hands back — a ``ResourceCatalog``, a dict
    with ``entries``, a bare list, or a list of strings — and returns
    something safe to put in a prompt. Never raises: a malformed catalog
    yields an empty one, because a connector returning garbage must not be
    able to take a run down or smuggle text into the system prompt.
    """
    if isinstance(raw, ResourceCatalog):
        items: Iterable[Any] = [
            {"id": e.id, "title": e.title, "description": e.description}
            for e in raw.entries
        ]
        already_truncated = raw.truncated
    elif isinstance(raw, dict):
        items = raw.get("entries") or []
        already_truncated = bool(raw.get("truncated"))
    elif isinstance(raw, (list, tuple)):
        items = raw
        already_truncated = False
    else:
        return ResourceCatalog()

    cleaned: list[CatalogEntry] = []
    for item in items:
        if isinstance(item, CatalogEntry):
            entry_id, title, description = item.id, item.title, item.description
        elif isinstance(item, dict):
            entry_id = item.get("id") or item.get("name") or item.get("key")
            title = item.get("title") or item.get("name") or entry_id
            description = item.get("description") or item.get("summary") or ""
        elif isinstance(item, str):
            entry_id = title = item
            description = ""
        else:
            continue

        entry_id = _clean(entry_id, MAX_ID_LENGTH)
        title = _clean(title, MAX_TITLE_LENGTH)
        description = _clean(description, MAX_DESCRIPTION_LENGTH)
        if not entry_id or not title:
            # An entry the agent cannot name or address is not usable.
            continue
        cleaned.append(CatalogEntry(id=entry_id, title=title, description=description))

    # Deterministic order, so an unstable upstream cannot reshuffle the prompt
    # between runs (which would also defeat prompt caching).
    cleaned.sort(key=lambda e: (e.title.lower(), e.id))

    # De-duplicate by id, keeping the first after sorting.
    seen: set[str] = set()
    unique: list[CatalogEntry] = []
    for entry in cleaned:
        if entry.id in seen:
            continue
        seen.add(entry.id)
        unique.append(entry)

    truncated = already_truncated or len(unique) > MAX_ENTRIES
    return ResourceCatalog(entries=unique[:MAX_ENTRIES], truncated=truncated)


def load_catalog(binding_or_tool: Any) -> ResourceCatalog:
    """Ask a tool for its catalog, if it offers one.

    A tool opts in with ``agent_catalog()``. Failure is never fatal: one
    connector that raises must not lose every other binding's catalog or abort
    the turn, so it is recorded as simply having none.
    """
    getter = getattr(binding_or_tool, "agent_catalog", None)
    if not callable(getter):
        return ResourceCatalog()
    try:
        return normalize_catalog(getter())
    except Exception:
        return ResourceCatalog()
