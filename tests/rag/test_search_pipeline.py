from datetime import datetime, timedelta, timezone

from shipit_agent.rag.embedder import HashingEmbedder
from shipit_agent.rag.keyword_store import InMemoryBM25Store
from shipit_agent.rag.reranker import LLMReranker
from shipit_agent.rag.search_pipeline import HybridSearchPipeline
from shipit_agent.rag.types import Chunk, SearchQuery
from shipit_agent.rag.vector_store import InMemoryVectorStore


def _make_store(corpus: list[tuple[str, str]], embedder: HashingEmbedder):
    vec = InMemoryVectorStore()
    kw = InMemoryBM25Store()
    chunks = [
        Chunk(
            id=f"d1::{i}",
            document_id="d1",
            chunk_index=i,
            text=text,
            source=source,
            embedding=embedder.embed([text])[0],
        )
        for i, (source, text) in enumerate(corpus)
    ]
    vec.add(chunks)
    kw.add(chunks)
    return vec, kw, chunks


def test_hybrid_search_returns_top_k():
    emb = HashingEmbedder(dimension=256)
    vec, kw, _ = _make_store(
        [
            ("readme", "python programming language"),
            ("readme", "rust programming language"),
            ("readme", "sailing the ocean"),
        ],
        emb,
    )
    pipeline = HybridSearchPipeline(vector_store=vec, embedder=emb, keyword_store=kw)
    ctx = pipeline.search(SearchQuery(query="python language", top_k=2))
    assert len(ctx.results) == 2
    assert ctx.results[0].chunk.id == "d1::0"
    assert ctx.timing_ms["total_ms"] > 0
    assert "embed_ms" in ctx.timing_ms
    assert "vector_ms" in ctx.timing_ms
    assert "keyword_ms" in ctx.timing_ms


def test_hybrid_search_without_keyword_store_falls_back_to_vector_only():
    emb = HashingEmbedder(dimension=256)
    vec, _, _ = _make_store(
        [("r", "python language"), ("r", "rust language")],
        emb,
    )
    pipeline = HybridSearchPipeline(vector_store=vec, embedder=emb)
    ctx = pipeline.search(SearchQuery(query="python", top_k=2))
    assert [r.chunk.id for r in ctx.results] == ["d1::0", "d1::1"]
    # Only vector branch recorded — no keyword timing entry.
    assert "keyword_ms" not in ctx.timing_ms


def test_hybrid_search_populates_component_scores():
    emb = HashingEmbedder(dimension=256)
    vec, kw, _ = _make_store(
        [("r", "python programming"), ("r", "rust programming")],
        emb,
    )
    pipeline = HybridSearchPipeline(vector_store=vec, embedder=emb, keyword_store=kw)
    ctx = pipeline.search(SearchQuery(query="python", top_k=1))
    result = ctx.results[0]
    assert result.vector_score is not None
    assert result.keyword_score is not None


def test_recency_bias_prefers_newer_chunks():
    emb = HashingEmbedder(dimension=256)
    vec = InMemoryVectorStore()
    now = datetime.now(tz=timezone.utc)
    old = Chunk(
        id="d1::0",
        document_id="d1",
        chunk_index=0,
        text="python language",
        embedding=emb.embed(["python language"])[0],
        created_at=now - timedelta(days=365),
    )
    new = Chunk(
        id="d2::0",
        document_id="d2",
        chunk_index=0,
        text="python language",
        embedding=emb.embed(["python language"])[0],
        created_at=now - timedelta(days=1),
    )
    vec.add([old, new])
    pipeline = HybridSearchPipeline(vector_store=vec, embedder=emb)
    ctx_no = pipeline.search(
        SearchQuery(query="python", top_k=2, enable_recency_bias=False)
    )
    ctx_yes = pipeline.search(
        SearchQuery(
            query="python",
            top_k=2,
            enable_recency_bias=True,
            recency_half_life_days=30.0,
        )
    )
    assert ctx_yes.results[0].chunk.id == "d2::0"
    # Without bias, either order is possible (scores tied) — just confirm both present.
    assert {r.chunk.id for r in ctx_no.results} == {"d1::0", "d2::0"}


def test_reranker_reorders_results():
    emb = HashingEmbedder(dimension=256)
    vec, kw, _ = _make_store(
        [
            ("r", "python programming language"),
            ("r", "rust programming language"),
            ("r", "go programming language"),
        ],
        emb,
    )

    class FakeLLM:
        def complete(self, messages):
            # Rank third chunk highest, second next, first last.
            class R:
                content = "[1, 5, 9]"

            return R()

    pipeline = HybridSearchPipeline(
        vector_store=vec,
        embedder=emb,
        keyword_store=kw,
        reranker=LLMReranker(llm=FakeLLM()),
    )
    ctx = pipeline.search(
        SearchQuery(query="programming", top_k=3, enable_reranking=True)
    )
    assert [r.chunk.id for r in ctx.results] == ["d1::2", "d1::1", "d1::0"]
    assert ctx.results[0].rerank_score == 0.9


def test_context_expansion_returns_neighbours():
    emb = HashingEmbedder(dimension=256)
    vec, kw, _ = _make_store(
        [
            ("r", "intro to python"),
            ("r", "python variables"),
            ("r", "python functions"),
            ("r", "python classes"),
            ("r", "conclusion"),
        ],
        emb,
    )
    pipeline = HybridSearchPipeline(vector_store=vec, embedder=emb, keyword_store=kw)
    ctx = pipeline.search(
        SearchQuery(query="python functions", top_k=1, chunks_above=1, chunks_below=1)
    )
    result = ctx.results[0]
    assert result.chunk.id == "d1::2"
    assert [c.id for c in result.expanded_above] == ["d1::1"]
    assert [c.id for c in result.expanded_below] == ["d1::3"]


def test_empty_store_returns_empty_context():
    emb = HashingEmbedder(dimension=64)
    pipeline = HybridSearchPipeline(
        vector_store=InMemoryVectorStore(),
        embedder=emb,
        keyword_store=InMemoryBM25Store(),
    )
    ctx = pipeline.search(SearchQuery(query="anything", top_k=5))
    assert ctx.results == []
    assert ctx.total_found == 0
