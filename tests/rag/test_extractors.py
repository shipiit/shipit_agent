import os

import pytest

from shipit_agent.rag.extractors import RAGIngestError, TextExtractor


def test_extract_txt(tmp_path):
    path = tmp_path / "hello.txt"
    path.write_text("Hello RAG", encoding="utf-8")
    assert TextExtractor().extract(str(path)) == "Hello RAG"


def test_extract_markdown(tmp_path):
    path = tmp_path / "notes.md"
    path.write_text("# Title\n\nBody.", encoding="utf-8")
    text = TextExtractor().extract(str(path))
    assert "Title" in text and "Body" in text


def test_extract_unknown_extension_reads_as_plaintext(tmp_path):
    path = tmp_path / "data.unknown"
    path.write_text("plain content", encoding="utf-8")
    assert TextExtractor().extract(str(path)) == "plain content"


def test_extract_missing_file_raises_ingest_error():
    with pytest.raises(RAGIngestError):
        TextExtractor().extract("/no/such/file.txt")


def test_extract_html_strips_tags(tmp_path):
    path = tmp_path / "page.html"
    path.write_text("<html><body><h1>Title</h1><p>Body text.</p></body></html>", encoding="utf-8")
    text = TextExtractor().extract(str(path))
    assert "Title" in text
    assert "Body text" in text
    assert "<h1>" not in text


def test_supported_extensions_includes_common_formats():
    exts = TextExtractor.supported_extensions()
    assert ".txt" in exts
    assert ".md" in exts
    assert ".pdf" in exts
    assert ".docx" in exts
