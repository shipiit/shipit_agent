"""Typed, provenance-carrying facts explicitly declared by tool results."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping


@dataclass(frozen=True, slots=True)
class VerifiedFact:
    key: str
    value: str
    source_tool: str
    source_call_id: str
    updated_at: float

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "VerifiedFact":
        return cls(
            key=str(value.get("key", "")),
            value=str(value.get("value", "")),
            source_tool=str(value.get("source_tool", "")),
            source_call_id=str(value.get("source_call_id", "")),
            updated_at=float(value.get("updated_at", 0.0) or 0.0),
        )


class FactLedger:
    """Last-write-wins facts whose values always name their tool provenance."""

    def __init__(self, facts: Iterable[VerifiedFact] = ()) -> None:
        self._facts = {fact.key: fact for fact in facts if fact.key and fact.value}

    @classmethod
    def from_serialized(cls, values: Any) -> "FactLedger":
        if not isinstance(values, list):
            return cls()
        facts: list[VerifiedFact] = []
        for value in values:
            if isinstance(value, Mapping):
                fact = VerifiedFact.from_dict(value)
                if fact.key and fact.value:
                    facts.append(fact)
        return cls(facts)

    def ingest_tool_results(self, results: Iterable[Any]) -> int:
        """Accept only explicit ``metadata['facts']``; never infer from prose."""
        changed = 0
        for result in results:
            metadata = dict(getattr(result, "metadata", None) or {})
            declared = metadata.get("facts")
            pairs: list[tuple[str, Any]] = []
            if isinstance(declared, Mapping):
                pairs = [(str(key), value) for key, value in declared.items()]
            elif isinstance(declared, list):
                for item in declared:
                    if isinstance(item, Mapping) and item.get("key"):
                        pairs.append((str(item["key"]), item.get("value")))
            for key, value in pairs:
                if value is None or not key.strip():
                    continue
                fact = VerifiedFact(
                    key=key.strip(),
                    value=str(value),
                    source_tool=str(getattr(result, "name", "") or "tool"),
                    source_call_id=str(
                        getattr(result, "tool_call_id", "")
                        or metadata.get("tool_call_id", "")
                    ),
                    updated_at=time.time(),
                )
                if self._facts.get(fact.key) != fact:
                    self._facts[fact.key] = fact
                    changed += 1
        return changed

    def render(self, *, max_facts: int = 40) -> str:
        facts = sorted(
            self._facts.values(), key=lambda fact: fact.updated_at, reverse=True
        )[:max_facts]
        if not facts:
            return ""
        lines = [
            "Verified session facts supplied explicitly by completed tools:",
        ]
        for fact in facts:
            source = fact.source_tool
            if fact.source_call_id:
                source += f"/{fact.source_call_id}"
            lines.append(f"- {fact.key} = {fact.value} (source: {source})")
        return "\n".join(lines)

    def to_list(self) -> list[dict[str, Any]]:
        return [asdict(fact) for fact in self._facts.values()]

    def __len__(self) -> int:
        return len(self._facts)


__all__ = ["FactLedger", "VerifiedFact"]
