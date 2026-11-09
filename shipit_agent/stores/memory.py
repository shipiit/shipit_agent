"""Stores for remembered facts: in memory or in a JSON file."""

from __future__ import annotations

import json
import re
import os
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass(slots=True)
class MemoryFact:
    """One remembered fact, with its category and metadata."""
    content: str
    category: str = "general"
    score: float = 1.0
    metadata: dict[str, object] = field(default_factory=dict)


class MemoryStore(Protocol):
    """Where an agent saves facts and searches them later."""
    def add(self, fact: MemoryFact) -> None: ...

    def search(self, query: str, limit: int = 5) -> list[MemoryFact]: ...


class InMemoryMemoryStore:
    """A memory store that lives for the life of the process."""
    def __init__(self) -> None:
        self._facts: list[MemoryFact] = []

    def add(self, fact: MemoryFact) -> None:
        self._facts.append(fact)

    def search(self, query: str, limit: int = 5) -> list[MemoryFact]:
        return rank_facts(self._facts, query, limit)


class FileMemoryStore:
    """A memory store kept in one JSON file."""
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # In-process lock guarding the read-modify-write cycle in add().
        self._lock = threading.Lock()
        if not self.path.exists():
            self.path.write_text("[]", encoding="utf-8")

    def _load_all(self) -> list[MemoryFact]:
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return [
            MemoryFact(
                content=item["content"],
                category=item.get("category", "general"),
                score=float(item.get("score", 1.0)),
                metadata=dict(item.get("metadata", {})),
            )
            for item in raw
        ]

    def _save_all(self, facts: list[MemoryFact]) -> None:
        payload = [
            {
                "content": fact.content,
                "category": fact.category,
                "score": fact.score,
                "metadata": fact.metadata,
            }
            for fact in facts
        ]
        _atomic_write_text(self.path, json.dumps(payload, indent=2))

    def add(self, fact: MemoryFact) -> None:
        # Lock the whole load -> append -> save cycle so concurrent adds
        # cannot lose updates; the write itself is atomic via temp + replace.
        with self._lock:
            facts = self._load_all()
            facts.append(fact)
            self._save_all(facts)

    def search(self, query: str, limit: int = 5) -> list[MemoryFact]:
        return rank_facts(self._load_all(), query, limit)


#: Words too common to say what a search is about.
_STOPWORDS = frozenset(
    "a an and are as at be by do does for from how i in is it me my of on or so that the this to "
    "was we what when where which who why with you your".split()
)


def rank_facts(facts: list[MemoryFact], query: str, limit: int) -> list[MemoryFact]:
    """Facts that match *query*, best first.

    The exact query text ranks first; after it, facts score by how many of the
    query's words (common words left out) they contain, so a natural phrase such
    as "deploy region" finds "deploys from the eu-west-1 region". An empty query
    returns facts in stored order.
    """
    lowered = query.lower().strip()
    if not lowered:
        return facts[:limit]
    words = [w for w in re.findall(r"[\w-]+", lowered) if w not in _STOPWORDS and len(w) > 1]
    scored: list[tuple[int, int, MemoryFact]] = []
    for index, fact in enumerate(facts):
        text = fact.content.lower()
        score = (len(words) + 1 if lowered in text else 0) + sum(1 for w in words if w in text)
        if score:
            scored.append((-score, index, fact))
    return [fact for _, _, fact in sorted(scored)[:limit]]


def _atomic_write_text(path: Path, text: str) -> None:
    """Write *text* to *path* atomically via a temp file + ``os.replace``.

    The temp file is created in the same directory so the rename is atomic
    on one filesystem; a concurrent reader never sees a truncated write.
    """
    directory = path.parent
    fd, tmp_name = tempfile.mkstemp(dir=directory, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
