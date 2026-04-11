from shipit_agent.rag.embedder import HashingEmbedder
from shipit_agent.rag.types import Chunk, IndexFilters
from shipit_agent.rag.vector_store import InMemoryVectorStore


def _chunk(cid: str, doc_id: str, index: int, text: str, embedder: HashingEmbedder,
           source: str | None = None, metadata: dict | None = None) -> Chunk:
    return Chunk(
        id=cid,
        document_id=doc_id,
        chunk_index=index,
        text=text,
        embedding=embedder.embed([text])[0],
        source=source,
        metadata=metadata or {},
    )


def test_add_and_count():
    emb = HashingEmbedder(dimension=64)
    store = InMemoryVectorStore()
    store.add([
        _chunk("d1::0", "d1", 0, "alpha", emb),
        _chunk("d1::1", "d1", 1, "beta", emb),
    ])
    assert store.count() == 2


def test_get_and_get_many():
    emb = HashingEmbedder(dimension=64)
    store = InMemoryVectorStore()
    store.add([
        _chunk("d1::0", "d1", 0, "alpha", emb),
        _chunk("d1::1", "d1", 1, "beta", emb),
    ])
    assert store.get("d1::0").text == "alpha"
    assert store.get("missing") is None
    rows = store.get_many(["d1::0", "missing", "d1::1"])
    assert [r.id for r in rows] == ["d1::0", "d1::1"]


def test_list_chunks_sorted_by_index():
    emb = HashingEmbedder(dimension=32)
    store = InMemoryVectorStore()
    store.add([
        _chunk("d1::2", "d1", 2, "third", emb),
        _chunk("d1::0", "d1", 0, "first", emb),
        _chunk("d1::1", "d1", 1, "second", emb),
    ])
    ordered = store.list_chunks("d1")
    assert [c.text for c in ordered] == ["first", "second", "third"]


def test_delete_by_id():
    emb = HashingEmbedder(dimension=32)
    store = InMemoryVectorStore()
    store.add([
        _chunk("d1::0", "d1", 0, "alpha", emb),
        _chunk("d1::1", "d1", 1, "beta", emb),
    ])
    store.delete(["d1::0"])
    assert store.get("d1::0") is None
    assert [c.id for c in store.list_chunks("d1")] == ["d1::1"]


def test_delete_document():
    emb = HashingEmbedder(dimension=32)
    store = InMemoryVectorStore()
    store.add([
        _chunk("d1::0", "d1", 0, "alpha", emb),
        _chunk("d1::1", "d1", 1, "beta", emb),
        _chunk("d2::0", "d2", 0, "gamma", emb),
    ])
    store.delete_document("d1")
    assert store.count() == 1
    assert store.get("d2::0") is not None
    assert store.list_chunks("d1") == []


def test_search_returns_top_k_ordered():
    emb = HashingEmbedder(dimension=256)
    store = InMemoryVectorStore()
    store.add([
        _chunk("d1::0", "d1", 0, "python programming language", emb),
        _chunk("d1::1", "d1", 1, "rust programming language", emb),
        _chunk("d1::2", "d1", 2, "sailing across the ocean", emb),
    ])
    q = emb.embed(["python language"])[0]
    results = store.search(q, top_k=2)
    assert len(results) == 2
    assert results[0][0].id == "d1::0"
    # Scores descending
    assert results[0][1] >= results[1][1]


def test_search_applies_filters():
    emb = HashingEmbedder(dimension=256)
    store = InMemoryVectorStore()
    store.add([
        _chunk("d1::0", "d1", 0, "python language", emb, source="readme"),
        _chunk("d2::0", "d2", 0, "python language", emb, source="manual"),
    ])
    q = emb.embed(["python"])[0]
    filters = IndexFilters(sources=["manual"])
    results = store.search(q, top_k=5, filters=filters)
    assert [r[0].id for r in results] == ["d2::0"]


def test_search_skips_chunks_without_embeddings():
    store = InMemoryVectorStore()
    store.add([Chunk(id="d1::0", document_id="d1", chunk_index=0, text="no embedding")])
    results = store.search([0.1, 0.2, 0.3], top_k=5)
    assert results == []


def test_list_sources_returns_sorted_unique():
    emb = HashingEmbedder(dimension=32)
    store = InMemoryVectorStore()
    store.add([
        _chunk("d1::0", "d1", 0, "a", emb, source="readme"),
        _chunk("d2::0", "d2", 0, "b", emb, source="manual"),
        _chunk("d3::0", "d3", 0, "c", emb, source="readme"),
    ])
    assert store.list_sources() == ["manual", "readme"]


def test_add_reinserting_preserves_order():
    emb = HashingEmbedder(dimension=32)
    store = InMemoryVectorStore()
    store.add([_chunk("d1::0", "d1", 0, "a", emb)])
    store.add([_chunk("d1::0", "d1", 0, "a updated", emb)])
    assert store.count() == 1
    assert store.get("d1::0").text == "a updated"
