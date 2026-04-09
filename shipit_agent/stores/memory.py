from __future__ import annotations

import json
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
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def add(self, fact: MemoryFact) -> None:
        facts = self._load_all()
        facts.append(fact)
        self._save_all(facts)

    def search(self, query: str, limit: int = 5) -> list[MemoryFact]:
        lowered = query.lower()
        matches = [fact for fact in self._load_all() if lowered in fact.content.lower()]
        return matches[:limit]
