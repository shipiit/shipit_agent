"""Extended RAG coverage: concurrency, deep-agent wiring, prompt injection, edge cases."""
from __future__ import annotations

import threading
from dataclasses import dataclass

import pytest

from shipit_agent.agent import Agent
from shipit_agent.deep.adaptive_agent import AdaptiveAgent
from shipit_agent.deep.goal_agent import Goal, GoalAgent
from shipit_agent.deep.persistent_agent import PersistentAgent
from shipit_agent.deep.reflective_agent import ReflectiveAgent
from shipit_agent.deep.supervisor import Supervisor, Worker
from shipit_agent.llms.base import LLMResponse
from shipit_agent.rag.chunker import DocumentChunker
from shipit_agent.rag.embedder import HashingEmbedder
from shipit_agent.rag.keyword_store import InMemoryBM25Store
from shipit_agent.rag.rag import RAG
from shipit_agent.rag.types import Chunk, Document, IndexFilters, RAGContext, SearchResult
from shipit_agent.rag.vector_store import InMemoryVectorStore


class _DummyLLM:
    def complete(self, messages, **kwargs):
        return LLMResponse(
            content="done",
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        )


def _seeded_rag() -> RAG:
    rag = RAG.default(embedder=HashingEmbedder(dimension=256))
    rag.index_text("python is a programming language", document_id="d1", source="readme")
    rag.index_text("rust is a systems language", document_id="d2", source="readme")
    return rag


# ---------------------------------------------------------------------------
# Concurrent run isolation (thread-local SourceTracker)
# ---------------------------------------------------------------------------


def test_concurrent_runs_do_not_leak_sources():
    rag = _seeded_rag()

    captured_a: list[int] = []
    captured_b: list[int] = []
    barrier = threading.Barrier(2)

    def worker_a():
        rag.begin_run()
        barrier.wait()
        rag.search("python", top_k=1)
        captured_a.append(len(rag.end_run()))

    def worker_b():
        rag.begin_run()
        barrier.wait()
        rag.search("rust", top_k=1)
        captured_b.append(len(rag.end_run()))

    t1 = threading.Thread(target=worker_a)
    t2 = threading.Thread(target=worker_b)
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert captured_a == [1]
    assert captured_b == [1]


def test_end_run_without_begin_returns_empty_list():
    rag = _seeded_rag()
    assert rag.end_run() == []


# ---------------------------------------------------------------------------
# Deep-agent wiring smoke tests
# ---------------------------------------------------------------------------


def test_supervisor_stores_rag_on_agent_kwargs():
    rag = _seeded_rag()
    dummy_agent = Agent(llm=_DummyLLM())
    supervisor = Supervisor(
        llm=_DummyLLM(),
        workers=[Worker(name="research", agent=dummy_agent)],
        rag=rag,
    )
    assert supervisor.rag is rag
    assert supervisor.agent_kwargs.get("rag") is rag


def test_supervisor_with_builtins_wires_rag_into_every_worker():
    rag = _seeded_rag()
    supervisor = Supervisor.with_builtins(
        llm=_DummyLLM(),
        worker_configs=[
            {"name": "alpha", "prompt": "You research."},
            {"name": "beta", "prompt": "You write."},
        ],
        rag=rag,
    )
    for worker in supervisor.workers.values():
        tool_names = {t.name for t in worker.agent.tools}
        assert "rag_search" in tool_names


def test_adaptive_agent_rag_kwarg_propagates():
    rag = _seeded_rag()
    agent = AdaptiveAgent(llm=_DummyLLM(), rag=rag)
    # AdaptiveAgent stashes extras in agent_kwargs.
    assert agent.agent_kwargs.get("rag") is rag


def test_persistent_agent_rag_kwarg_propagates():
    rag = _seeded_rag()
    agent = PersistentAgent(llm=_DummyLLM(), rag=rag)
    assert agent.agent_kwargs.get("rag") is rag


def test_reflective_agent_inner_agent_has_rag_tools():
    rag = _seeded_rag()
    agent = ReflectiveAgent(llm=_DummyLLM(), rag=rag)
    inner = agent._build_agent()
    assert any(t.name == "rag_search" for t in inner.tools)


def test_goal_agent_inner_agent_has_rag_tools():
    rag = _seeded_rag()
    ga = GoalAgent(
        llm=_DummyLLM(),
        goal=Goal(objective="x", success_criteria=["y"]),
        rag=rag,
    )
    inner = ga._build_agent()
    assert any(t.name == "rag_search" for t in inner.tools)


# ---------------------------------------------------------------------------
# Agent prompt + tool wiring invariants
# ---------------------------------------------------------------------------


def test_agent_prompt_section_is_additive_not_replacement():
    rag = _seeded_rag()
    agent = Agent(llm=_DummyLLM(), prompt="You are an expert.", rag=rag)
    assert "You are an expert." in agent.prompt
    assert "rag_search" in agent.prompt


def test_agent_rag_none_keeps_default_prompt():
    agent = Agent(llm=_DummyLLM())
    assert "rag_search" not in agent.prompt
    assert all("rag_" not in t.name for t in agent.tools)


def test_agent_run_wraps_begin_and_end_run_even_on_empty_corpus():
    rag = RAG.default(embedder=HashingEmbedder(dimension=64))
    agent = Agent(llm=_DummyLLM(), rag=rag)
    result = agent.run("hi")
    assert isinstance(result.rag_sources, list)
    assert result.rag_sources == []


# ---------------------------------------------------------------------------
# Chunker edge cases
# ---------------------------------------------------------------------------


def test_chunker_ignores_only_whitespace_doc():
    chunker = DocumentChunker()
    assert chunker.chunk(Document(id="d1", content="   \n\n  \t")) == []


def test_chunker_handles_unicode():
    chunker = DocumentChunker()
    doc = Document(id="d1", content="Ça va? Très bien. 日本語も.")
    chunks = chunker.chunk(doc)
    assert chunks
    assert "日本語" in chunks[0].text


def test_chunker_custom_target_tokens():
    chunker = DocumentChunker(target_tokens=50, overlap_tokens=0)
    doc = Document(id="d1", content=". ".join(f"sentence number {i}" for i in range(30)))
    chunks = chunker.chunk(doc)
    assert len(chunks) >= 2


# ---------------------------------------------------------------------------
# Vector store filter + embedding edge cases
# ---------------------------------------------------------------------------


def test_vector_store_search_empty_top_k_returns_empty():
    emb = HashingEmbedder(dimension=64)
    store = InMemoryVectorStore()
    store.add([
        Chunk(
            id="d1::0",
            document_id="d1",
            chunk_index=0,
            text="x",
            embedding=emb.embed(["x"])[0],
        )
    ])
    q = emb.embed(["x"])[0]
    assert store.search(q, top_k=0) == []


def test_index_filters_time_min_without_created_at_rejects():
    from datetime import datetime, timezone

    f = IndexFilters(time_min=datetime(2025, 1, 1, tzinfo=timezone.utc))
    chunk = Chunk(id="d1::0", document_id="d1", chunk_index=0, text="x")
    assert not f.matches(chunk)


# ---------------------------------------------------------------------------
# Keyword store resilience
# ---------------------------------------------------------------------------


def test_keyword_store_handles_unicode_and_punctuation():
    store = InMemoryBM25Store()
    store.add([
        Chunk(id="d1::0", document_id="d1", chunk_index=0, text="Python! Python? Python."),
    ])
    results = store.search("python", top_k=1)
    assert results
    assert results[0][1] > 0


# ---------------------------------------------------------------------------
# RAG facade high-level invariants
# ---------------------------------------------------------------------------


def test_rag_count_matches_chunks_indexed():
    rag = RAG.default(embedder=HashingEmbedder(dimension=64))
    rag.index_text("alpha beta gamma", document_id="d1")
    count_one = rag.count()
    rag.index_text("more content here", document_id="d2")
    assert rag.count() > count_one


def test_rag_list_sources_unique_and_sorted():
    rag = RAG.default(embedder=HashingEmbedder(dimension=64))
    rag.index_text("a", document_id="d1", source="z")
    rag.index_text("b", document_id="d2", source="a")
    rag.index_text("c", document_id="d3", source="m")
    assert rag.list_sources() == ["a", "m", "z"]


def test_rag_search_hybrid_alpha_extremes():
    rag = RAG.default(embedder=HashingEmbedder(dimension=256))
    rag.index_text("python programming", document_id="d1")
    rag.index_text("rust programming", document_id="d2")
    # Pure vector
    ctx_v = rag.search("python", top_k=2, hybrid_alpha=1.0)
    # Pure keyword
    ctx_k = rag.search("python", top_k=2, hybrid_alpha=0.0)
    assert ctx_v.results and ctx_k.results
    # Both should surface the python chunk first.
    assert ctx_v.results[0].chunk.document_id == "d1"
    assert ctx_k.results[0].chunk.document_id == "d1"


def test_rag_context_to_dict_round_trip():
    ctx = RAGContext(query="python", total_found=0, timing_ms={"total_ms": 1.0})
    d = ctx.to_dict()
    assert d["query"] == "python"
    assert d["results"] == []
    assert d["timing_ms"] == {"total_ms": 1.0}


def test_rag_reindex_on_missing_doc_and_no_content_is_noop():
    rag = RAG.default(embedder=HashingEmbedder(dimension=64))
    assert rag.reindex("never-existed") == []
