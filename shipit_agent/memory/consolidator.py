"""Episodic memory consolidation — turn raw conversations into long-term knowledge.

After every N agent turns (or once a session closes), the consolidator runs
a small distillation pass:

1. Read the most recent conversation turns
2. Ask an LLM "what did we learn that's worth remembering?"
3. Write the extracted facts into ``SemanticMemory`` with a strength score
4. Apply a forgetting curve to existing facts (gentle decay over time)
5. Promote frequently-retrieved facts to a "core memory" set that's
   always present in the system prompt

Why this matters: today, an agent restarted next week starts cold even if
you kept ``SessionStore``. RAG over old transcripts is high-noise. With
consolidation, the agent carries forward distilled facts ("user prefers
brief answers", "the auth service uses Argon2", "Q3 release deadline is
Oct 14") that survive across sessions.

Quick start::

    from shipit_agent.memory import AgentMemory, MemoryConsolidator

    consolidator = MemoryConsolidator(llm=cheap_llm, max_facts_per_pass=8)
    memory = AgentMemory.default(llm=llm)

    # Run it on demand — or schedule it from your own loop / cron
    distilled = consolidator.consolidate(
        memory=memory,
        recent_messages=memory.conversation.get_messages(),
    )
    print([f.text for f in distilled])

    # Apply decay — typically once a day
    consolidator.decay(memory.knowledge, half_life_days=14)

    # Promote frequently-retrieved facts to "core memory"
    core = consolidator.core_memory(memory.knowledge, top_k=5)
    print(core)  # join into system prompt
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any

from shipit_agent.parsers.streaming_json import parse_partial_json


_CONSOLIDATION_SYSTEM_PROMPT = (
    "You distill an agent's recent conversation into 3-8 durable facts worth "
    "remembering across sessions. Focus on:\n"
    "- User preferences (writing style, format, pacing)\n"
    "- Project / domain facts (system names, constraints, decisions)\n"
    "- People and their roles\n"
    "- Recurring goals or deadlines\n\n"
    "Skip:\n"
    "- One-off questions and their answers\n"
    "- Generic pleasantries\n"
    "- Information already obvious from the agent's tools\n\n"
    'Reply with a JSON object EXACTLY of shape: {"facts": [{"text": "...", '
    '"category": "preference"|"project"|"person"|"goal"|"other", '
    '"confidence": 0.0-1.0}, ...]}\n'
    "Output ONLY the JSON, no prose."
)


@dataclass(slots=True)
class DistilledFact:
    """A single fact extracted by consolidation."""

    text: str
    category: str = "other"
    confidence: float = 1.0
    timestamp: float = field(default_factory=time.time)
    strength: float = 1.0
    """Decays over time. Below ``forgetting_threshold`` the fact may be pruned."""
    retrievals: int = 0
    """How many times this fact was returned by ``search_knowledge``."""


@dataclass(slots=True)
class ConsolidationResult:
    """Return value of ``MemoryConsolidator.consolidate``."""

    facts: list[DistilledFact]
    raw_text: str = ""
    skipped_reason: str | None = None


class MemoryConsolidator:
    """Run distillation, decay, and core-memory promotion on an ``AgentMemory``.

    Args:
        llm: any object with ``.complete(messages=...)``. A cheap model is
            ideal — distillation is bulk-summarisation, not deep reasoning.
        max_facts_per_pass: cap on facts written per consolidation. Stops
            the model from spamming the memory store.
        min_messages: don't consolidate unless at least this many recent
            messages exist (avoids "we had a 2-turn chat — what did we learn?").
        confidence_threshold: facts below this confidence are dropped.
        forgetting_threshold: facts whose ``strength`` decays below this
            during ``decay()`` are pruned by default.
    """

    def __init__(
        self,
        *,
        llm: Any,
        max_facts_per_pass: int = 8,
        min_messages: int = 6,
        confidence_threshold: float = 0.5,
        forgetting_threshold: float = 0.1,
    ) -> None:
        self.llm = llm
        self.max_facts_per_pass = max_facts_per_pass
        self.min_messages = min_messages
        self.confidence_threshold = confidence_threshold
        self.forgetting_threshold = forgetting_threshold

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def consolidate(
        self,
        *,
        memory: Any,
        recent_messages: list[Any],
    ) -> ConsolidationResult:
        """Distill recent messages and write the facts into ``memory.knowledge``.

        Returns the list of facts that were written (may be empty if the
        input was too short or the LLM produced unparseable output).
        """
        if not recent_messages:
            return ConsolidationResult(facts=[], skipped_reason="no messages")
        if len(recent_messages) < self.min_messages:
            return ConsolidationResult(
                facts=[],
                skipped_reason=f"only {len(recent_messages)} messages (min {self.min_messages})",
            )

        try:
            text = _invoke(self.llm, recent_messages)
        except Exception as exc:
            return ConsolidationResult(
                facts=[], skipped_reason=f"llm unavailable: {exc}"
            )

        facts = self._parse_facts(text)
        # Filter by confidence + cap
        facts = [f for f in facts if f.confidence >= self.confidence_threshold]
        facts = facts[: self.max_facts_per_pass]

        # Write to semantic memory
        knowledge = getattr(memory, "knowledge", None) or memory
        for f in facts:
            self._write_fact(knowledge, f)
        return ConsolidationResult(facts=facts, raw_text=text)

    def decay(
        self,
        knowledge: Any,
        *,
        half_life_days: float = 14.0,
        prune: bool = True,
    ) -> int:
        """Apply exponential decay to every fact's ``strength``.

        ``strength *= exp(-ln(2) * elapsed_days / half_life_days)``. Facts
        whose strength drops below ``forgetting_threshold`` are pruned when
        ``prune=True``. Returns the number of facts pruned.

        Designed to be called once a day (or however often you like). Cheap
        — pure local arithmetic, no LLM call.
        """
        if half_life_days <= 0:
            return 0
        now = time.time()
        decay_constant = math.log(2.0) / (half_life_days * 86_400.0)

        pruned = 0
        entries = self._knowledge_entries(knowledge)
        new_entries: list[Any] = []
        for entry in entries:
            metadata = self._entry_metadata(entry)
            ts = float(metadata.get("timestamp", now))
            elapsed = max(0.0, now - ts)
            strength = float(metadata.get("strength", 1.0))
            new_strength = strength * math.exp(-decay_constant * elapsed)
            metadata["strength"] = new_strength
            if prune and new_strength < self.forgetting_threshold:
                pruned += 1
                continue
            new_entries.append(entry)

        if pruned:
            self._set_knowledge_entries(knowledge, new_entries)
        return pruned

    def core_memory(
        self,
        knowledge: Any,
        *,
        top_k: int = 5,
        min_retrievals: int = 0,
    ) -> list[str]:
        """Return the top-K "core" facts — high-strength + frequently retrieved.

        These should be appended to the agent's system prompt every turn so
        the model always sees them, regardless of RAG retrieval results.
        """
        entries = self._knowledge_entries(knowledge)
        scored: list[tuple[float, str]] = []
        for entry in entries:
            metadata = self._entry_metadata(entry)
            strength = float(metadata.get("strength", 1.0))
            retrievals = int(metadata.get("retrievals", 0))
            if retrievals < min_retrievals:
                continue
            # Composite score — strength weights more, but retrievals
            # bump well-loved facts up.
            score = strength + 0.1 * math.log1p(retrievals)
            text = self._entry_text(entry)
            if text:
                scored.append((score, text))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [text for _score, text in scored[:top_k]]

    def record_retrieval(self, knowledge: Any, fact_texts: list[str]) -> int:
        """Bump the retrieval counter for facts that were just returned.

        Pass the ``.text`` of each ``SearchResult`` from a successful search.
        Returns the number of facts whose counter was incremented.
        """
        bumped = 0
        if not fact_texts:
            return 0
        wanted = set(fact_texts)
        for entry in self._knowledge_entries(knowledge):
            text = self._entry_text(entry)
            if text in wanted:
                metadata = self._entry_metadata(entry)
                metadata["retrievals"] = int(metadata.get("retrievals", 0)) + 1
                bumped += 1
        return bumped

    # ------------------------------------------------------------------
    # Internals — handle both InMemoryVectorStore and direct dict-list shapes
    # ------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _invoke(llm: Any, recent_messages: list[Any]) -> str:
    transcript = "\n".join(_format_message(m) for m in recent_messages[-30:])
    user_msg = f"Recent conversation:\n{transcript}\n\nDistill into facts."
    messages = [
        {"role": "system", "content": _CONSOLIDATION_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]
    result = llm.complete(messages=messages)
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        return result.get("content") or result.get("text") or ""
    return getattr(result, "content", None) or getattr(result, "text", None) or ""


def _format_message(m: Any) -> str:
    role = getattr(m, "role", None) or (m.get("role") if isinstance(m, dict) else "?")
    content = getattr(m, "content", None) or (
        m.get("content") if isinstance(m, dict) else ""
    )
    return f"[{role}] {str(content)[:400]}"


__all__ = [
    "ConsolidationResult",
    "DistilledFact",
    "MemoryConsolidator",
]
