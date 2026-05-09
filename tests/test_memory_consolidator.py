"""Tests for ``MemoryConsolidator`` — episodic memory consolidation.

≥10 tests per public method:
- ``consolidate``       → 12
- ``decay``             → 11
- ``core_memory``       → 10
- ``record_retrieval``  → 10
- ``DistilledFact``     → 7
- Public-import surface → 4
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from shipit_agent.memory import (
    AgentMemory,
    ConsolidationResult,
    DistilledFact,
    InMemoryVectorStore,
    MemoryConsolidator,
    SemanticMemory,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@dataclass
class StubLLM:
    responses: list[str] = field(default_factory=list)
    calls: list[list[dict[str, Any]]] = field(default_factory=list)
    _i: int = 0

    def complete(self, *, messages: list[dict[str, Any]], **_: Any) -> str:
        self.calls.append(list(messages))
        if self._i >= len(self.responses):
            raise RuntimeError("StubLLM exhausted")
        out = self.responses[self._i]
        self._i += 1
        return out


@dataclass
class FailingLLM:
    def complete(self, **_: Any) -> str:
        raise RuntimeError("network down")


def _facts_payload(facts: list[dict[str, Any]]) -> str:
    return json.dumps({"facts": facts})


def _msg(role: str, content: str) -> dict[str, str]:
    return {"role": role, "content": content}


def _conversation(n: int = 8) -> list[dict[str, str]]:
    out = []
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        out.append(_msg(role, f"turn-{i}: lorem ipsum dolor sit amet"))
    return out


def _entries(memory: AgentMemory) -> list[dict[str, Any]]:
    """Pull the underlying entry list from the AgentMemory."""
    return memory.knowledge.vector_store._entries  # noqa: SLF001


# ===========================================================================
# consolidate (≥10 tests)
# ===========================================================================


class TestConsolidate:
    def _memory(self) -> AgentMemory:
        return AgentMemory(
            knowledge=SemanticMemory(vector_store=InMemoryVectorStore()),
        )

    def test_writes_facts_to_knowledge(self) -> None:
        llm = StubLLM(
            [
                _facts_payload(
                    [
                        {"text": "user prefers brief answers", "category": "preference"},
                        {"text": "auth uses Argon2", "category": "project"},
                    ]
                )
            ]
        )
        c = MemoryConsolidator(llm=llm, min_messages=2)
        memory = self._memory()
        result = c.consolidate(memory=memory, recent_messages=_conversation(8))
        assert isinstance(result, ConsolidationResult)
        assert len(result.facts) == 2
        assert len(_entries(memory)) == 2

    def test_skips_when_no_messages(self) -> None:
        c = MemoryConsolidator(llm=StubLLM())
        memory = self._memory()
        result = c.consolidate(memory=memory, recent_messages=[])
        assert result.facts == []
        assert result.skipped_reason == "no messages"

    def test_skips_when_below_min_messages(self) -> None:
        c = MemoryConsolidator(llm=StubLLM(), min_messages=10)
        memory = self._memory()
        result = c.consolidate(memory=memory, recent_messages=_conversation(3))
        assert result.facts == []
        assert "min" in (result.skipped_reason or "")

    def test_caps_facts_per_pass(self) -> None:
        many = [{"text": f"fact-{i}", "category": "other"} for i in range(20)]
        llm = StubLLM([_facts_payload(many)])
        c = MemoryConsolidator(llm=llm, min_messages=2, max_facts_per_pass=5)
        memory = self._memory()
        result = c.consolidate(memory=memory, recent_messages=_conversation(8))
        assert len(result.facts) == 5

    def test_filters_by_confidence(self) -> None:
        llm = StubLLM(
            [
                _facts_payload(
                    [
                        {"text": "high", "confidence": 0.9},
                        {"text": "low", "confidence": 0.2},
                    ]
                )
            ]
        )
        c = MemoryConsolidator(llm=llm, min_messages=2, confidence_threshold=0.5)
        memory = self._memory()
        result = c.consolidate(memory=memory, recent_messages=_conversation(8))
        assert len(result.facts) == 1
        assert result.facts[0].text == "high"

    def test_handles_llm_failure_gracefully(self) -> None:
        c = MemoryConsolidator(llm=FailingLLM())
        memory = self._memory()
        result = c.consolidate(memory=memory, recent_messages=_conversation(8))
        assert result.facts == []
        assert "unavailable" in (result.skipped_reason or "")

    def test_handles_unparseable_response(self) -> None:
        c = MemoryConsolidator(
            llm=StubLLM(["not json at all"]), min_messages=2
        )
        memory = self._memory()
        result = c.consolidate(memory=memory, recent_messages=_conversation(8))
        assert result.facts == []

    def test_handles_response_without_facts_key(self) -> None:
        c = MemoryConsolidator(
            llm=StubLLM([json.dumps({"other": "stuff"})]), min_messages=2
        )
        memory = self._memory()
        result = c.consolidate(memory=memory, recent_messages=_conversation(8))
        assert result.facts == []

    def test_skips_facts_with_empty_text(self) -> None:
        llm = StubLLM(
            [_facts_payload([{"text": "", "category": "other"}, {"text": "real fact"}])]
        )
        c = MemoryConsolidator(llm=llm, min_messages=2)
        memory = self._memory()
        result = c.consolidate(memory=memory, recent_messages=_conversation(8))
        assert len(result.facts) == 1
        assert result.facts[0].text == "real fact"

    def test_default_confidence_when_missing(self) -> None:
        llm = StubLLM([_facts_payload([{"text": "no confidence given"}])])
        c = MemoryConsolidator(llm=llm, min_messages=2, confidence_threshold=0.5)
        memory = self._memory()
        result = c.consolidate(memory=memory, recent_messages=_conversation(8))
        assert len(result.facts) == 1

    def test_metadata_attached_to_written_fact(self) -> None:
        llm = StubLLM(
            [_facts_payload([{"text": "stored", "category": "person", "confidence": 0.8}])]
        )
        c = MemoryConsolidator(llm=llm, min_messages=2)
        memory = self._memory()
        c.consolidate(memory=memory, recent_messages=_conversation(8))
        entry = _entries(memory)[0]
        assert entry["metadata"]["category"] == "person"
        assert entry["metadata"]["consolidated"] is True

    def test_recent_messages_passed_to_llm(self) -> None:
        llm = StubLLM([_facts_payload([])])
        c = MemoryConsolidator(llm=llm, min_messages=2)
        memory = self._memory()
        c.consolidate(memory=memory, recent_messages=_conversation(6))
        user_msg = llm.calls[0][-1]["content"]
        assert "turn-0" in user_msg
        assert "turn-5" in user_msg


# ===========================================================================
# decay (≥10 tests)
# ===========================================================================


class TestDecay:
    def _store_with_facts(self, ages_seconds: list[float], strengths: list[float] | None = None) -> InMemoryVectorStore:
        store = InMemoryVectorStore()
        now = time.time()
        if strengths is None:
            strengths = [1.0] * len(ages_seconds)
        for i, (age, strength) in enumerate(zip(ages_seconds, strengths)):
            store._entries.append(  # noqa: SLF001
                {
                    "id": f"e{i}",
                    "text": f"fact-{i}",
                    "embedding": None,
                    "metadata": {"timestamp": now - age, "strength": strength},
                }
            )
        return store

    def test_strength_decreases_over_time(self) -> None:
        store = self._store_with_facts([14 * 86400])
        c = MemoryConsolidator(llm=StubLLM())
        c.decay(store, half_life_days=14, prune=False)
        s = store._entries[0]["metadata"]["strength"]  # noqa: SLF001
        assert 0.45 < s < 0.55

    def test_prunes_below_threshold(self) -> None:
        store = self._store_with_facts([100 * 86400])
        c = MemoryConsolidator(llm=StubLLM(), forgetting_threshold=0.1)
        pruned = c.decay(store, half_life_days=14)
        assert pruned == 1
        assert len(store._entries) == 0  # noqa: SLF001

    def test_prune_false_keeps_all(self) -> None:
        store = self._store_with_facts([100 * 86400])
        c = MemoryConsolidator(llm=StubLLM())
        pruned = c.decay(store, half_life_days=14, prune=False)
        assert pruned == 0
        assert len(store._entries) == 1  # noqa: SLF001

    def test_keeps_recent_facts(self) -> None:
        store = self._store_with_facts([1, 2, 3])
        c = MemoryConsolidator(llm=StubLLM())
        pruned = c.decay(store, half_life_days=14)
        assert pruned == 0
        assert len(store._entries) == 3  # noqa: SLF001

    def test_zero_half_life_is_noop(self) -> None:
        store = self._store_with_facts([14 * 86400])
        c = MemoryConsolidator(llm=StubLLM())
        pruned = c.decay(store, half_life_days=0)
        assert pruned == 0

    def test_negative_half_life_is_noop(self) -> None:
        store = self._store_with_facts([14 * 86400])
        c = MemoryConsolidator(llm=StubLLM())
        pruned = c.decay(store, half_life_days=-7)
        assert pruned == 0

    def test_decay_preserves_text(self) -> None:
        store = self._store_with_facts([1])
        c = MemoryConsolidator(llm=StubLLM())
        c.decay(store, half_life_days=14)
        assert store._entries[0]["text"] == "fact-0"  # noqa: SLF001

    def test_decay_handles_missing_timestamp(self) -> None:
        store = InMemoryVectorStore()
        store._entries.append(  # noqa: SLF001
            {"id": "x", "text": "a", "embedding": None, "metadata": {}}
        )
        c = MemoryConsolidator(llm=StubLLM())
        c.decay(store, half_life_days=14)
        assert "strength" in store._entries[0]["metadata"]  # noqa: SLF001

    def test_decay_handles_missing_strength(self) -> None:
        store = InMemoryVectorStore()
        store._entries.append(  # noqa: SLF001
            {
                "id": "x",
                "text": "a",
                "embedding": None,
                "metadata": {"timestamp": time.time() - 86400 * 7},
            }
        )
        c = MemoryConsolidator(llm=StubLLM())
        c.decay(store, half_life_days=14, prune=False)
        s = store._entries[0]["metadata"]["strength"]  # noqa: SLF001
        assert 0.65 < s < 0.75

    def test_returns_pruned_count(self) -> None:
        store = self._store_with_facts([100 * 86400, 100 * 86400, 1])
        c = MemoryConsolidator(llm=StubLLM(), forgetting_threshold=0.1)
        assert c.decay(store, half_life_days=14) == 2

    def test_decay_works_on_plain_list(self) -> None:
        store = [
            {"text": "old", "metadata": {"timestamp": time.time() - 100 * 86400, "strength": 1.0}},
            {"text": "new", "metadata": {"timestamp": time.time(), "strength": 1.0}},
        ]
        c = MemoryConsolidator(llm=StubLLM())
        pruned = c.decay(store, half_life_days=14)
        assert pruned == 1
        assert store[0]["text"] == "new"


# ===========================================================================
# core_memory (≥10 tests)
# ===========================================================================


class TestCoreMemory:
    def _store(self, items: list[tuple[str, float, int]]) -> InMemoryVectorStore:
        store = InMemoryVectorStore()
        for i, (text, strength, retrievals) in enumerate(items):
            store._entries.append(  # noqa: SLF001
                {
                    "id": f"e{i}",
                    "text": text,
                    "embedding": None,
                    "metadata": {
                        "strength": strength,
                        "retrievals": retrievals,
                        "timestamp": time.time(),
                    },
                }
            )
        return store

    def test_returns_top_k_by_strength(self) -> None:
        store = self._store([("a", 0.9, 0), ("b", 0.5, 0), ("c", 0.1, 0)])
        c = MemoryConsolidator(llm=StubLLM())
        out = c.core_memory(store, top_k=2)
        assert out == ["a", "b"]

    def test_top_k_limit(self) -> None:
        store = self._store([(f"t{i}", 0.9 - 0.01 * i, 0) for i in range(10)])
        c = MemoryConsolidator(llm=StubLLM())
        out = c.core_memory(store, top_k=3)
        assert len(out) == 3

    def test_retrievals_boost_score(self) -> None:
        store = self._store([("a", 0.5, 0), ("b", 0.5, 100)])
        c = MemoryConsolidator(llm=StubLLM())
        out = c.core_memory(store, top_k=1)
        assert out == ["b"]

    def test_min_retrievals_filter(self) -> None:
        store = self._store([("a", 0.9, 0), ("b", 0.5, 5)])
        c = MemoryConsolidator(llm=StubLLM())
        out = c.core_memory(store, top_k=5, min_retrievals=1)
        assert out == ["b"]

    def test_empty_store_returns_empty(self) -> None:
        c = MemoryConsolidator(llm=StubLLM())
        assert c.core_memory(InMemoryVectorStore(), top_k=5) == []

    def test_top_k_zero_returns_empty(self) -> None:
        store = self._store([("a", 0.9, 0)])
        c = MemoryConsolidator(llm=StubLLM())
        assert c.core_memory(store, top_k=0) == []

    def test_skips_empty_text(self) -> None:
        store = self._store([("", 0.9, 0), ("real", 0.5, 0)])
        c = MemoryConsolidator(llm=StubLLM())
        out = c.core_memory(store, top_k=5)
        assert out == ["real"]

    def test_handles_missing_strength_default_one(self) -> None:
        store = InMemoryVectorStore()
        store._entries.append(  # noqa: SLF001
            {"id": "x", "text": "a", "embedding": None, "metadata": {}}
        )
        c = MemoryConsolidator(llm=StubLLM())
        out = c.core_memory(store, top_k=1)
        assert out == ["a"]

    def test_handles_missing_retrievals_default_zero(self) -> None:
        store = InMemoryVectorStore()
        store._entries.append(  # noqa: SLF001
            {"id": "x", "text": "a", "embedding": None, "metadata": {"strength": 0.5}}
        )
        c = MemoryConsolidator(llm=StubLLM())
        out = c.core_memory(store, top_k=1)
        assert out == ["a"]

    def test_works_on_plain_list(self) -> None:
        store = [
            {"text": "high", "metadata": {"strength": 0.9, "retrievals": 0}},
            {"text": "low", "metadata": {"strength": 0.1, "retrievals": 0}},
        ]
        c = MemoryConsolidator(llm=StubLLM())
        assert c.core_memory(store, top_k=1) == ["high"]


# ===========================================================================
# record_retrieval (≥10 tests)
# ===========================================================================


class TestRecordRetrieval:
    def _store(self, texts: list[str]) -> InMemoryVectorStore:
        store = InMemoryVectorStore()
        for i, t in enumerate(texts):
            store._entries.append(  # noqa: SLF001
                {
                    "id": f"e{i}",
                    "text": t,
                    "embedding": None,
                    "metadata": {"retrievals": 0},
                }
            )
        return store

    def test_increments_retrievals(self) -> None:
        store = self._store(["a", "b"])
        c = MemoryConsolidator(llm=StubLLM())
        c.record_retrieval(store, ["a"])
        assert store._entries[0]["metadata"]["retrievals"] == 1  # noqa: SLF001
        assert store._entries[1]["metadata"]["retrievals"] == 0  # noqa: SLF001

    def test_increments_multiple(self) -> None:
        store = self._store(["a", "b", "c"])
        c = MemoryConsolidator(llm=StubLLM())
        bumped = c.record_retrieval(store, ["a", "c"])
        assert bumped == 2

    def test_no_match_returns_zero(self) -> None:
        store = self._store(["a"])
        c = MemoryConsolidator(llm=StubLLM())
        assert c.record_retrieval(store, ["does-not-exist"]) == 0

    def test_empty_input_returns_zero(self) -> None:
        store = self._store(["a"])
        c = MemoryConsolidator(llm=StubLLM())
        assert c.record_retrieval(store, []) == 0

    def test_repeated_call_increments_again(self) -> None:
        store = self._store(["a"])
        c = MemoryConsolidator(llm=StubLLM())
        c.record_retrieval(store, ["a"])
        c.record_retrieval(store, ["a"])
        assert store._entries[0]["metadata"]["retrievals"] == 2  # noqa: SLF001

    def test_handles_missing_retrievals_field(self) -> None:
        store = InMemoryVectorStore()
        store._entries.append(  # noqa: SLF001
            {"id": "x", "text": "a", "embedding": None, "metadata": {}}
        )
        c = MemoryConsolidator(llm=StubLLM())
        c.record_retrieval(store, ["a"])
        assert store._entries[0]["metadata"]["retrievals"] == 1  # noqa: SLF001

    def test_returns_count_of_bumped(self) -> None:
        store = self._store(["a", "b", "c"])
        c = MemoryConsolidator(llm=StubLLM())
        n = c.record_retrieval(store, ["a", "missing", "c"])
        assert n == 2

    def test_handles_empty_store(self) -> None:
        c = MemoryConsolidator(llm=StubLLM())
        assert c.record_retrieval(InMemoryVectorStore(), ["a"]) == 0

    def test_works_with_duplicate_texts(self) -> None:
        store = self._store(["dup", "dup"])
        c = MemoryConsolidator(llm=StubLLM())
        bumped = c.record_retrieval(store, ["dup"])
        assert bumped == 2

    def test_works_on_plain_list(self) -> None:
        store = [{"text": "x", "metadata": {"retrievals": 0}}]
        c = MemoryConsolidator(llm=StubLLM())
        assert c.record_retrieval(store, ["x"]) == 1
        assert store[0]["metadata"]["retrievals"] == 1


# ===========================================================================
# DistilledFact + import surface
# ===========================================================================


class TestDistilledFact:
    def test_required_text_only(self) -> None:
        f = DistilledFact(text="hello")
        assert f.text == "hello"

    def test_default_category(self) -> None:
        assert DistilledFact(text="x").category == "other"

    def test_default_confidence(self) -> None:
        assert DistilledFact(text="x").confidence == 1.0

    def test_default_strength(self) -> None:
        assert DistilledFact(text="x").strength == 1.0

    def test_default_retrievals(self) -> None:
        assert DistilledFact(text="x").retrievals == 0

    def test_timestamp_auto_set(self) -> None:
        f = DistilledFact(text="x")
        assert f.timestamp > 0

    def test_custom_fields(self) -> None:
        f = DistilledFact(text="x", category="goal", confidence=0.5, strength=0.8)
        assert f.category == "goal"
        assert f.confidence == 0.5
        assert f.strength == 0.8


class TestPublicSurface:
    def test_top_level_imports(self) -> None:
        from shipit_agent import (
            ConsolidationResult,
            DistilledFact,
            MemoryConsolidator,
        )

        assert MemoryConsolidator is not None
        assert DistilledFact is not None
        assert ConsolidationResult is not None

    def test_memory_subpackage_imports(self) -> None:
        from shipit_agent.memory import MemoryConsolidator

        assert MemoryConsolidator is not None

    def test_consolidator_takes_llm(self) -> None:
        c = MemoryConsolidator(llm=StubLLM())
        assert c.llm is not None

    def test_consolidator_default_caps(self) -> None:
        c = MemoryConsolidator(llm=StubLLM())
        assert c.max_facts_per_pass == 8
        assert c.min_messages == 6
