from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass(slots=True)
class MemoryFact:
    content: str
    category: str = "general"
    score: float = 1.0
    metadata: dict[str, object] = field(default_factory=dict)


class MemoryStore(Protocol):
    def add(self, fact: MemoryFact) -> None: ...

    def search(self, query: str, limit: int = 5) -> list[MemoryFact]: ...


class InMemoryMemoryStore:
    def __init__(self) -> None:
        self._facts: list[MemoryFact] = []

    def add(self, fact: MemoryFact) -> None:
        self._facts.append(fact)

    def search(self, query: str, limit: int = 5) -> list[MemoryFact]:
        lowered = query.lower()
        matches = [fact for fact in self._facts if lowered in fact.content.lower()]
        return matches[:limit]


class FileMemoryStore:
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
        lowered = query.lower()
        matches = [fact for fact in self._load_all() if lowered in fact.content.lower()]
        return matches[:limit]


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
