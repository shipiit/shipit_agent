"""Advanced file reading — the extractor registry and read_file's routing.

Real documents are generated on the fly (python-docx / openpyxl / python-pptx)
so the tests exercise the actual parsers, not mocks. Each parser test skips
cleanly when its library isn't installed, keeping CI green without the extras.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.file_extract import (
    available_suffixes,
    extract_file,
    extractor_for,
    register_extractor,
    supported_suffixes,
)
from shipit_agent.tools.file_extract import extractors as ex
from shipit_agent.tools.file_read import FileReadTool


# ── registry ──────────────────────────────────────────────────────────────────


def test_builtin_extractors_registered():
    assert {".docx", ".xlsx", ".pptx", ".html", ".csv", ".pdf"} <= supported_suffixes()


def test_csv_always_available_even_without_extras():
    assert ".csv" in available_suffixes()          # stdlib — no dependency


def test_extractor_for_is_suffix_and_availability_aware():
    assert extractor_for(".csv").name == "csv"
    assert extractor_for(".nope") is None


def test_unsupported_suffix_returns_none():
    # A plain-text suffix has no extractor → read_file reads it as text.
    assert extract_file(Path("x.py")) is None


def test_a_broken_probe_reads_as_unavailable():
    class Boom:
        name = "boom"
        suffixes = (".boom",)
        def is_available(self):
            raise RuntimeError("probe blew up")
        def extract(self, path):
            return "x"

    register_extractor(Boom())
    try:
        assert extractor_for(".boom") is None      # broken probe → skipped
    finally:
        ex._REGISTRY.pop("boom", None)


# ── CSV / TSV (stdlib, always on) ─────────────────────────────────────────────


def test_csv_becomes_a_markdown_table(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("name,age\nAda,36\nGrace,44\n", encoding="utf-8")
    markdown, backend = extract_file(path)
    assert backend == "csv"
    assert "| name | age |" in markdown and "| Ada | 36 |" in markdown


def test_tsv_uses_tab_delimiter(tmp_path):
    path = tmp_path / "data.tsv"
    path.write_text("a\tb\n1\t2\n", encoding="utf-8")
    markdown, _ = extract_file(path)
    assert "| a | b |" in markdown and "| 1 | 2 |" in markdown


def test_row_cap_is_reported(tmp_path):
    path = tmp_path / "big.csv"
    path.write_text("h\n" + "\n".join(str(i) for i in range(600)), encoding="utf-8")
    markdown, _ = extract_file(path)
    assert "cap reached" in markdown


# ── HTML (stdlib fallback always works) ───────────────────────────────────────


def test_html_extracts_readable_text(tmp_path):
    path = tmp_path / "page.html"
    path.write_text(
        "<html><head><style>.x{}</style></head><body>"
        "<h1>Title</h1><p>Hello world</p><script>ignore()</script></body></html>",
        encoding="utf-8",
    )
    markdown, backend = extract_file(path)
    assert backend == "html"
    assert "Title" in markdown and "Hello world" in markdown
    assert "ignore()" not in markdown            # script content dropped


# ── DOCX / XLSX / PPTX (real parsers; skip without the extra) ─────────────────


def test_docx_extraction(tmp_path):
    docx = pytest.importorskip("docx")
    path = tmp_path / "doc.docx"
    document = docx.Document()
    document.add_heading("My Heading", level=1)
    document.add_paragraph("A body paragraph.")
    table = document.add_table(rows=2, cols=2)
    table.rows[0].cells[0].text = "k"
    table.rows[0].cells[1].text = "v"
    table.rows[1].cells[0].text = "1"
    table.rows[1].cells[1].text = "2"
    document.save(str(path))

    markdown, backend = extract_file(path)
    assert backend == "docx"
    assert "# My Heading" in markdown
    assert "A body paragraph." in markdown
    assert "| k | v |" in markdown


def test_xlsx_extraction(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    path = tmp_path / "book.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Sales"
    sheet.append(["Region", "Total"])
    sheet.append(["EU", 100])
    workbook.save(str(path))

    markdown, backend = extract_file(path)
    assert backend == "xlsx"
    assert "## Sales" in markdown
    assert "| Region | Total |" in markdown and "| EU | 100 |" in markdown


def test_pptx_extraction(tmp_path):
    pptx = pytest.importorskip("pptx")
    path = tmp_path / "deck.pptx"
    presentation = pptx.Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[5])
    slide.shapes.title.text = "Slide One Title"
    presentation.save(str(path))

    markdown, backend = extract_file(path)
    assert backend == "pptx"
    assert "## Slide 1" in markdown and "Slide One Title" in markdown


# ── read_file routing ─────────────────────────────────────────────────────────


def test_read_file_routes_a_csv_through_extraction(tmp_path):
    (tmp_path / "t.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    out = FileReadTool(root_dir=tmp_path).run(ToolContext(prompt=""), path="t.csv")
    assert out.metadata.get("extracted_by") == "csv"
    assert "| a | b |" in out.text


def test_read_file_still_reads_plain_text_line_numbered(tmp_path):
    (tmp_path / "code.py").write_text("print('hi')\n", encoding="utf-8")
    out = FileReadTool(root_dir=tmp_path).run(ToolContext(prompt=""), path="code.py")
    assert "extracted_by" not in out.metadata     # text path, not extraction
    assert "1: print('hi')" in out.text


def test_read_file_surfaces_a_corrupt_document_cleanly(tmp_path):
    # A .docx that isn't a real zip → the parser raises → readable error, no crash.
    pytest.importorskip("docx")
    bad = tmp_path / "broken.docx"
    bad.write_text("this is not a docx", encoding="utf-8")
    out = FileReadTool(root_dir=tmp_path).run(ToolContext(prompt=""), path="broken.docx")
    assert out.metadata.get("ok") is False and "Could not extract" in out.text
