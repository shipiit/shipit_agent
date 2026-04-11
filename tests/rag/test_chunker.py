from shipit_agent.rag.chunker import DocumentChunker, make_document_id
from shipit_agent.rag.types import Document


def test_empty_document_yields_no_chunks():
    chunker = DocumentChunker()
    assert chunker.chunk(Document(id="d1", content="")) == []
    assert chunker.chunk(Document(id="d1", content="   \n")) == []


def test_single_sentence_document_produces_one_chunk():
    chunker = DocumentChunker(target_tokens=512, overlap_tokens=0)
    doc = Document(id="d1", content="Shipit supports Python 3.10+.")
    chunks = chunker.chunk(doc)
    assert len(chunks) == 1
    assert chunks[0].id == "d1::0"
    assert "Python 3.10" in chunks[0].text
    assert chunks[0].document_id == "d1"


def test_multi_sentence_fits_in_one_chunk():
    chunker = DocumentChunker(target_tokens=512, overlap_tokens=0)
    doc = Document(
        id="d1",
        content="Alpha is a letter. Beta is another. Gamma is third.",
    )
    chunks = chunker.chunk(doc)
    assert len(chunks) == 1
    assert "Alpha" in chunks[0].text and "Gamma" in chunks[0].text


def test_chunk_split_when_target_too_small():
    chunker = DocumentChunker(target_tokens=5, overlap_tokens=0)
    doc = Document(
        id="d1",
        content=(
            "One sentence here. Two sentence here. Three sentence here. "
            "Four sentence here. Five sentence here."
        ),
    )
    chunks = chunker.chunk(doc)
    assert len(chunks) >= 2
    # Chunks together must cover all five "sentence here" markers.
    joined = " ".join(c.text for c in chunks)
    for word in ("One", "Two", "Three", "Four", "Five"):
        assert word in joined


def test_chunk_indices_are_sequential():
    chunker = DocumentChunker(target_tokens=5, overlap_tokens=0)
    doc = Document(id="d1", content=". ".join(f"sentence {i}" for i in range(20)))
    chunks = chunker.chunk(doc)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    assert [c.id for c in chunks] == [f"d1::{i}" for i in range(len(chunks))]


def test_title_prefix_added_to_text_for_embedding():
    chunker = DocumentChunker(target_tokens=512, overlap_tokens=0, title_prefix_chars=32)
    doc = Document(
        id="d1",
        content="Body text here.",
        title="Shipit Installation Guide",
    )
    chunks = chunker.chunk(doc)
    assert chunks[0].text == "Body text here."
    assert chunks[0].text_for_embedding.startswith("Shipit Installation Guide")
    assert "Body text here." in chunks[0].text_for_embedding


def test_metadata_suffix_added_to_text_for_embedding():
    chunker = DocumentChunker(target_tokens=512, overlap_tokens=0)
    doc = Document(
        id="d1",
        content="Hello world.",
        source="readme.md",
        metadata={"tags": ["intro", "basic"]},
    )
    chunks = chunker.chunk(doc)
    emb = chunks[0].text_for_embedding
    assert "Source: readme.md" in emb
    assert "Tags: intro, basic" in emb


def test_no_title_and_no_metadata_keeps_text_clean():
    chunker = DocumentChunker(target_tokens=512, overlap_tokens=0)
    doc = Document(id="d1", content="Hello world.")
    chunks = chunker.chunk(doc)
    assert chunks[0].text_for_embedding == "Hello world."


def test_chunks_inherit_source_and_metadata():
    chunker = DocumentChunker()
    doc = Document(
        id="d1",
        content="Alpha. Beta.",
        source="readme",
        metadata={"owner": "rahul"},
    )
    chunks = chunker.chunk(doc)
    assert chunks[0].source == "readme"
    assert chunks[0].metadata == {"owner": "rahul"}


def test_oversized_single_sentence_gets_hard_split():
    chunker = DocumentChunker(target_tokens=5, overlap_tokens=0)
    long_sentence = "word " * 100
    doc = Document(id="d1", content=long_sentence.strip())
    chunks = chunker.chunk(doc)
    assert len(chunks) >= 2
    joined = " ".join(c.text for c in chunks)
    assert joined.count("word") == 100


def test_chunk_many():
    chunker = DocumentChunker()
    docs = [
        Document(id="d1", content="Alpha sentence."),
        Document(id="d2", content="Beta sentence."),
    ]
    chunks = chunker.chunk_many(docs)
    assert [c.document_id for c in chunks] == ["d1", "d2"]


def test_make_document_id_from_source():
    assert make_document_id("docs/manual.pdf") == "docs_manual.pdf"


def test_make_document_id_without_source_returns_hex():
    did = make_document_id()
    assert len(did) == 32
