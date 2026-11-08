"""Reading and writing consolidated facts in the knowledge store."""

from __future__ import annotations

import time
from typing import Any

from shipit_agent.parsers.streaming_json import parse_partial_json

from .facts import DistilledFact


class _KnowledgeEntries:
    """Reading and writing consolidated facts in the knowledge store."""

    def _parse_facts(self, text: str) -> list[DistilledFact]:
        parsed = parse_partial_json(text) or {}
        if not isinstance(parsed, dict):
            return []
        raw = parsed.get("facts", [])
        if not isinstance(raw, list):
            return []
        out: list[DistilledFact] = []
        now = time.time()
        for item in raw:
            if not isinstance(item, dict):
                continue
            text_val = str(item.get("text", "")).strip()
            if not text_val:
                continue
            category = str(item.get("category", "other"))
            conf = item.get("confidence", 0.7)
            try:
                confidence = max(0.0, min(1.0, float(conf)))
            except (TypeError, ValueError):
                confidence = 0.7
            out.append(
                DistilledFact(
                    text=text_val,
                    category=category,
                    confidence=confidence,
                    timestamp=now,
                    strength=1.0,
                )
            )
        return out

    def _write_fact(self, knowledge: Any, fact: DistilledFact) -> None:
        metadata = {
            "category": fact.category,
            "confidence": fact.confidence,
            "timestamp": fact.timestamp,
            "strength": fact.strength,
            "retrievals": fact.retrievals,
            "consolidated": True,
        }
        if hasattr(knowledge, "add"):
            try:
                knowledge.add(fact.text, metadata)
                return
            except TypeError:
                # Some stores expect (texts: list, metadatas: list) instead
                try:
                    knowledge.add([fact.text], [metadata])
                    return
                except Exception:
                    pass
        # Fall back to direct list manipulation if knowledge is a list
        if isinstance(knowledge, list):
            knowledge.append({"text": fact.text, "metadata": metadata})

    def _knowledge_entries(self, knowledge: Any) -> list[Any]:
        """Resolve to the list of entry dicts.

        Accepts:
        - ``InMemoryVectorStore`` (direct)         → ``_entries``
        - ``SemanticMemory`` (the AgentMemory shape) → ``.vector_store._entries``
        - plain list                               → returned as-is
        - any object with ``entries`` attribute    → ``.entries``
        """
        # SemanticMemory wraps a vector_store
        if hasattr(knowledge, "vector_store"):
            inner = knowledge.vector_store
            if hasattr(inner, "_entries"):
                return inner._entries  # noqa: SLF001
            if hasattr(inner, "entries"):
                return inner.entries
        entries = getattr(knowledge, "_entries", None)
        if entries is None:
            entries = getattr(knowledge, "entries", None)
        if entries is None and isinstance(knowledge, list):
            return knowledge
        return entries if entries is not None else []

    def _set_knowledge_entries(self, knowledge: Any, entries: list[Any]) -> None:
        if hasattr(knowledge, "vector_store"):
            inner = knowledge.vector_store
            if hasattr(inner, "_entries"):
                inner._entries = entries  # noqa: SLF001
                return
            if hasattr(inner, "entries"):
                inner.entries = entries
                return
        if hasattr(knowledge, "_entries"):
            knowledge._entries = entries  # noqa: SLF001
        elif hasattr(knowledge, "entries"):
            knowledge.entries = entries
        elif isinstance(knowledge, list):
            knowledge[:] = entries

    def _entry_metadata(self, entry: Any) -> dict[str, Any]:
        if isinstance(entry, dict):
            md = entry.setdefault("metadata", {})
            if not isinstance(md, dict):
                md = {}
                entry["metadata"] = md
            return md
        # Object-shaped entry — has attribute
        if hasattr(entry, "metadata"):
            md = getattr(entry, "metadata") or {}
            if not isinstance(md, dict):
                md = {}
            entry.metadata = md  # type: ignore[attr-defined]
            return md
        return {}

    def _entry_text(self, entry: Any) -> str:
        if isinstance(entry, dict):
            return str(entry.get("text", ""))
        return str(getattr(entry, "text", ""))
