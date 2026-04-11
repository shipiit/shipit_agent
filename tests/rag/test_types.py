from datetime import datetime, timedelta

from shipit_agent.rag.types import (
    Chunk,
    Document,
    IndexFilters,
    RAGContext,
    RAGSource,
    SearchResult,
)


def _chunk(cid: str = "d1::0", **overrides) -> Chunk:
    defaults: dict = dict(
        id=cid,
        document_id="d1",
        chunk_index=0,
        text="hello world",
        source="readme",
        metadata={"tag": "x"},
    )
    defaults.update(overrides)
    return Chunk(**defaults)


def test_chunk_defaults_text_for_embedding_to_text():
    c = _chunk()
    assert c.text_for_embedding == "hello world"


def test_chunk_preserves_explicit_text_for_embedding():
    c = _chunk(text_for_embedding="augmented: hello world")
    assert c.text_for_embedding == "augmented: hello world"


def test_index_filters_document_ids():
    f = IndexFilters(document_ids=["d1"])
    assert f.matches(_chunk(cid="d1::0"))
    assert not f.matches(_chunk(cid="d2::0", document_id="d2"))


def test_index_filters_source():
    f = IndexFilters(sources=["readme"])
    assert f.matches(_chunk(source="readme"))
    assert not f.matches(_chunk(source="manual"))


def test_index_filters_metadata_match():
    f = IndexFilters(metadata_match={"tag": "x"})
    assert f.matches(_chunk())
    assert not f.matches(_chunk(metadata={"tag": "y"}))


def test_index_filters_time_window():
    now = datetime(2026, 4, 11, 12, 0, 0)
    f = IndexFilters(time_min=now - timedelta(days=1), time_max=now + timedelta(days=1))
    assert f.matches(_chunk(created_at=now))
    assert not f.matches(_chunk(created_at=now + timedelta(days=2)))
    # Missing created_at + a time filter → does not match.
    assert not f.matches(_chunk(created_at=None))


def test_document_to_dict_roundtrip_fields():
    doc = Document(id="d1", content="hi", source="readme", title="Readme")
    d = doc.to_dict()
    assert d["id"] == "d1"
    assert d["source"] == "readme"
    assert d["title"] == "Readme"
    assert d["created_at"] is None


def test_rag_context_empty_prompt_context():
    ctx = RAGContext(query="python")
    text = ctx.to_prompt_context()
    assert "no results" in text
    assert "python" in text


def test_rag_context_prompt_context_renders_indexed_chunks():
    chunks = [
        _chunk(cid="d1::0", text="alpha"),
        _chunk(cid="d1::1", chunk_index=1, text="beta"),
    ]
    results = [SearchResult(chunk=c, score=0.9) for c in chunks]
    ctx = RAGContext(query="q", results=results, total_found=2)
    text = ctx.to_prompt_context()
    assert "[1]" in text and "[2]" in text
    assert "alpha" in text and "beta" in text
    assert "chunk_id=d1::0" in text


def test_rag_context_prompt_context_truncates_to_max_chars():
    big = _chunk(text="x" * 500)
    ctx = RAGContext(
        query="q", results=[SearchResult(chunk=big, score=1.0)], total_found=1
    )
    text = ctx.to_prompt_context(max_chars=120)
    assert len(text) <= 120
    assert "chunk_id=d1::0" in text


def test_rag_source_to_dict():
    src = RAGSource(
        index=1,
        chunk_id="d1::0",
        document_id="d1",
        text="alpha",
        score=0.87,
        source="readme",
        metadata={"kb": 1},
    )
    d = src.to_dict()
    assert d["index"] == 1
    assert d["chunk_id"] == "d1::0"
    assert d["metadata"] == {"kb": 1}
