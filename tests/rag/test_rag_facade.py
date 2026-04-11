from shipit_agent.rag.embedder import HashingEmbedder
from shipit_agent.rag.rag import RAG
from shipit_agent.rag.types import Document


def test_index_text_and_search_roundtrip():
    rag = RAG.default(embedder=HashingEmbedder(dimension=256))
    rag.index_text("Shipit supports Python 3.10+.", source="readme")
    rag.index_text("The agent streams events in real time.", source="readme")
    ctx = rag.search("python version", top_k=2)
    assert ctx.results
    assert ctx.results[0].chunk.source == "readme"
    assert "python" in ctx.results[0].chunk.text.lower()


def test_index_file_reads_and_chunks(tmp_path):
    path = tmp_path / "notes.md"
    path.write_text("First line here.\n\nSecond line about Python.", encoding="utf-8")
    rag = RAG.default(embedder=HashingEmbedder(dimension=128))
    chunks = rag.index_file(str(path))
    assert chunks
    assert chunks[0].source == str(path)
    ctx = rag.search("python", top_k=1)
    assert ctx.results


def test_index_document_preserves_id():
    rag = RAG.default(embedder=HashingEmbedder(dimension=64))
    rag.index_document(Document(id="my-doc", content="Alpha sentence. Beta sentence."))
    assert rag.vector_store.list_chunks("my-doc")
    chunk = rag.fetch_chunk("my-doc::0")
    assert chunk is not None
    assert chunk.document_id == "my-doc"


def test_delete_document_removes_from_stores():
    rag = RAG.default(embedder=HashingEmbedder(dimension=64))
    rag.index_text("alpha content", document_id="a")
    rag.index_text("beta content", document_id="b")
    rag.delete_document("a")
    assert rag.count() == 1
    assert rag.fetch_chunk("a::0") is None


def test_reindex_replaces_old_chunks():
    rag = RAG.default(embedder=HashingEmbedder(dimension=64))
    rag.index_text("original content here", document_id="d1")
    rag.reindex("d1", content="rewritten body of text")
    ctx = rag.search("rewritten", top_k=1)
    assert ctx.results
    assert "rewritten" in ctx.results[0].chunk.text.lower()
    ctx_old = rag.search("original", top_k=1)
    assert (
        not ctx_old.results or "original" not in ctx_old.results[0].chunk.text.lower()
    )


def test_list_sources():
    rag = RAG.default(embedder=HashingEmbedder(dimension=64))
    rag.index_text("a", source="readme")
    rag.index_text("b", source="manual")
    assert rag.list_sources() == ["manual", "readme"]


def test_begin_end_run_captures_sources():
    rag = RAG.default(embedder=HashingEmbedder(dimension=256))
    rag.index_text("alpha fact one", document_id="d1", source="readme")
    rag.index_text("beta fact two", document_id="d2", source="manual")
    rag.begin_run()
    rag.search("alpha", top_k=1)
    rag.search("beta", top_k=1)
    sources = rag.end_run()
    assert {s.source for s in sources} == {"readme", "manual"}
    assert [s.index for s in sources] == [1, 2]
    # After end_run, another cycle starts fresh.
    assert rag.current_sources() == []


def test_search_outside_run_records_nothing():
    rag = RAG.default(embedder=HashingEmbedder(dimension=64))
    rag.index_text("alpha", source="readme")
    rag.search("alpha", top_k=1)
    assert rag.current_sources() == []


def test_fetch_chunk_records_source():
    rag = RAG.default(embedder=HashingEmbedder(dimension=64))
    rag.index_text("alpha content", document_id="d1", source="readme")
    rag.begin_run()
    chunk = rag.fetch_chunk("d1::0")
    assert chunk is not None
    sources = rag.end_run()
    assert len(sources) == 1
    assert sources[0].chunk_id == "d1::0"


def test_fetch_chunk_missing_returns_none():
    rag = RAG.default(embedder=HashingEmbedder(dimension=64))
    assert rag.fetch_chunk("missing") is None


def test_fetch_chunk_dedupe_on_same_run():
    rag = RAG.default(embedder=HashingEmbedder(dimension=64))
    rag.index_text("alpha", document_id="d1", source="readme")
    rag.begin_run()
    rag.search("alpha", top_k=1)
    rag.fetch_chunk("d1::0")
    sources = rag.end_run()
    assert len(sources) == 1


def test_prompt_section_mentions_tools():
    rag = RAG.default(embedder=HashingEmbedder(dimension=64))
    section = rag.prompt_section()
    assert "rag_search" in section
    assert "[N]" in section


def test_as_tools_returns_three_tools():
    rag = RAG.default(embedder=HashingEmbedder(dimension=64))
    tools = rag.as_tools()
    assert len(tools) == 3
    names = {t.name for t in tools}
    assert names == {"rag_search", "rag_fetch_chunk", "rag_list_sources"}
