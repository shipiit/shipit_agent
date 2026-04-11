from shipit_agent.rag.keyword_store import InMemoryBM25Store, _tokenize
from shipit_agent.rag.types import Chunk, IndexFilters


def _chunk(
    cid: str, doc_id: str, index: int, text: str, source: str | None = None
) -> Chunk:
    return Chunk(
        id=cid,
        document_id=doc_id,
        chunk_index=index,
        text=text,
        source=source,
    )


def test_tokenize_drops_stopwords_and_lowercases():
    tokens = _tokenize("The quick Brown fox is on a log")
    assert "the" not in tokens
    assert "is" not in tokens
    assert "brown" in tokens
    assert "fox" in tokens


def test_search_ranks_exact_matches_higher():
    store = InMemoryBM25Store()
    store.add(
        [
            _chunk("d1::0", "d1", 0, "python programming language"),
            _chunk("d1::1", "d1", 1, "rust programming language"),
            _chunk("d1::2", "d1", 2, "sailing across the ocean"),
        ]
    )
    results = store.search("python language", top_k=3)
    assert results[0][0].id == "d1::0"
    # Unrelated chunk (sailing) should not appear
    ids = [r[0].id for r in results]
    assert "d1::2" not in ids


def test_search_respects_top_k():
    store = InMemoryBM25Store()
    store.add(
        [
            _chunk(f"d1::{i}", "d1", i, "python programming snippet example")
            for i in range(10)
        ]
    )
    results = store.search("python", top_k=3)
    assert len(results) == 3


def test_search_applies_filters():
    store = InMemoryBM25Store()
    store.add(
        [
            _chunk("d1::0", "d1", 0, "python language", source="readme"),
            _chunk("d2::0", "d2", 0, "python language", source="manual"),
        ]
    )
    results = store.search("python", top_k=5, filters=IndexFilters(sources=["manual"]))
    assert [r[0].id for r in results] == ["d2::0"]


def test_empty_store_returns_empty():
    assert InMemoryBM25Store().search("anything", top_k=5) == []


def test_empty_query_returns_empty():
    store = InMemoryBM25Store()
    store.add([_chunk("d1::0", "d1", 0, "python")])
    assert store.search("", top_k=5) == []
    # All-stopword query → also empty
    assert store.search("the a of", top_k=5) == []


def test_delete_removes_from_index():
    store = InMemoryBM25Store()
    store.add(
        [
            _chunk("d1::0", "d1", 0, "python programming"),
            _chunk("d1::1", "d1", 1, "python scripting"),
        ]
    )
    store.delete(["d1::0"])
    results = store.search("programming", top_k=5)
    assert all(r[0].id != "d1::0" for r in results)


def test_delete_document_removes_all_chunks():
    store = InMemoryBM25Store()
    store.add(
        [
            _chunk("d1::0", "d1", 0, "python"),
            _chunk("d1::1", "d1", 1, "python"),
            _chunk("d2::0", "d2", 0, "python"),
        ]
    )
    store.delete_document("d1")
    assert store.count() == 1
    results = store.search("python", top_k=5)
    assert len(results) == 1
    assert results[0][0].id == "d2::0"


def test_readd_updates_in_place():
    store = InMemoryBM25Store()
    store.add([_chunk("d1::0", "d1", 0, "original text")])
    store.add([_chunk("d1::0", "d1", 0, "rewritten version")])
    assert store.count() == 1
    assert store.search("rewritten", top_k=1)[0][0].text == "rewritten version"
    # Original token is gone
    assert store.search("original", top_k=1) == []
