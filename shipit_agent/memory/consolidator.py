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
from dataclasses import dataclass
from typing import Any

from .facts import DistilledFact as DistilledFact
from .knowledge import _KnowledgeEntries

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
class ConsolidationResult:
    """Return value of ``MemoryConsolidator.consolidate``."""

    facts: list[DistilledFact]
    raw_text: str = ""
    skipped_reason: str | None = None


class MemoryConsolidator(_KnowledgeEntries):
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
