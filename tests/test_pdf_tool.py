"""Tests for the PDFTool + parse_pages helper.

Cover:
- tool shape (name / description / schema)
- parse_pages unit cases (comma list, ranges, mixed, empty, whitespace, clamp)
- missing pypdf → friendly error
- file_not_found
- integration: page_count / extract_text / extract_pages / metadata
- max_chars truncation marker
- URL fetch via mocked urlopen
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pytest

from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.pdf import PDFTool
from shipit_agent.tools.pdf.pdf_tool import parse_pages


# ──────────────────────────── fixtures ──────────────────────────────


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    reportlab_canvas = pytest.importorskip("reportlab.pdfgen.canvas")
    path = tmp_path / "sample.pdf"
    c = reportlab_canvas.Canvas(str(path))
    c.drawString(100, 750, "Page one hello")
    c.showPage()
    c.drawString(100, 750, "Page two world")
    c.showPage()
    c.drawString(100, 750, "Page three end")
    c.showPage()
    c.save()
    return path


@pytest.fixture
def ctx() -> ToolContext:
    return ToolContext(prompt="extract pdf")


# ──────────────────────────── unit: shape ───────────────────────────


class TestToolShape:
    def test_default_name_and_description(self) -> None:
        tool = PDFTool()
        assert tool.name == "pdf"
        assert "PDF" in tool.description
        assert tool.prompt_instructions

    def test_schema_lists_four_actions(self) -> None:
        schema = PDFTool().schema()
        params = schema["function"]["parameters"]
        assert params["required"] == ["action", "source"]
        actions = params["properties"]["action"]["enum"]
        assert set(actions) == {
            "extract_text",
            "extract_pages",
            "metadata",
            "page_count",
        }

    def test_custom_prompt_is_respected(self) -> None:
        tool = PDFTool(prompt="custom-prompt-body")
        assert tool.prompt == "custom-prompt-body"


# ──────────────────────────── unit: parse_pages ─────────────────────


class TestParsePages:
    def test_empty_string_returns_empty(self) -> None:
        assert parse_pages("") == []
        assert parse_pages(None) == []

    def test_whitespace_only_returns_empty(self) -> None:
        assert parse_pages("   ") == []

    def test_single_comma_list(self) -> None:
        assert parse_pages("1,3,5") == [0, 2, 4]

    def test_single_range(self) -> None:
        assert parse_pages("2-4") == [1, 2, 3]

    def test_mixed_ranges_and_singletons(self) -> None:
        assert parse_pages("1-3,5,7-9") == [0, 1, 2, 4, 6, 7, 8]

    def test_whitespace_tolerance(self) -> None:
        assert parse_pages("  1 - 3 ,  5 ") == [0, 1, 2, 4]

    def test_out_of_range_clamped(self) -> None:
        # total_pages=3 → valid indices 0,1,2. Anything else is dropped.
        assert parse_pages("1-5,7", total_pages=3) == [0, 1, 2]

    def test_dedupes_across_ranges(self) -> None:
        assert parse_pages("1-3,2-4") == [0, 1, 2, 3]


# ──────────────────────────── pypdf_missing ─────────────────────────


class TestPypdfMissing:
    def test_pypdf_missing_returns_friendly_error(
        self, ctx: ToolContext, tmp_path: Path
    ) -> None:
        tool = PDFTool()
        fake = tmp_path / "x.pdf"
        fake.write_bytes(b"%PDF-1.4\n")

        import builtins

        real_import = builtins.__import__

        def fake_import(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
            if name == "pypdf":
                raise ImportError("no pypdf here")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            out = tool.run(ctx, action="page_count", source=str(fake))
        assert out.metadata.get("error") == "pypdf_missing"
        assert "pip install" in out.metadata.get("install", "")


# ──────────────────────────── error paths ───────────────────────────


class TestErrors:
    def test_unknown_action(self, ctx: ToolContext) -> None:
        out = PDFTool().run(ctx, action="nope", source="whatever.pdf")
        assert out.metadata.get("error") == "unknown_action"

    def test_missing_source(self, ctx: ToolContext) -> None:
        out = PDFTool().run(ctx, action="extract_text", source="")
        assert out.metadata.get("error") == "missing_source"

    def test_file_not_found(self, ctx: ToolContext, tmp_path: Path) -> None:
        pytest.importorskip("pypdf")
        missing = tmp_path / "does-not-exist.pdf"
        out = PDFTool().run(ctx, action="page_count", source=str(missing))
        assert out.metadata.get("error") == "file_not_found"


# ──────────────────────────── integration ───────────────────────────


class TestIntegration:
    def test_page_count(self, ctx: ToolContext, sample_pdf: Path) -> None:
        pytest.importorskip("pypdf")
        out = PDFTool().run(ctx, action="page_count", source=str(sample_pdf))
        assert out.metadata["page_count"] == 3
        assert out.text == "3 pages."

    def test_extract_text_full_document(
        self, ctx: ToolContext, sample_pdf: Path
    ) -> None:
        pytest.importorskip("pypdf")
        out = PDFTool().run(ctx, action="extract_text", source=str(sample_pdf))
        assert "Page one hello" in out.text
        assert "Page two world" in out.text
        assert "Page three end" in out.text
        assert out.metadata["pages_extracted"] == 3
        assert out.metadata["truncated"] is False

    def test_extract_text_single_page(
        self, ctx: ToolContext, sample_pdf: Path
    ) -> None:
        pytest.importorskip("pypdf")
        out = PDFTool().run(
            ctx, action="extract_text", source=str(sample_pdf), pages="1"
        )
        assert "Page one hello" in out.text
        assert "Page two world" not in out.text
        assert "Page three end" not in out.text

    def test_extract_text_range(
        self, ctx: ToolContext, sample_pdf: Path
    ) -> None:
        pytest.importorskip("pypdf")
        out = PDFTool().run(
            ctx, action="extract_text", source=str(sample_pdf), pages="1-2"
        )
        assert "Page one hello" in out.text
        assert "Page two world" in out.text
        assert "Page three end" not in out.text

    def test_extract_text_truncation_marker(
        self, ctx: ToolContext, sample_pdf: Path
    ) -> None:
        pytest.importorskip("pypdf")
        out = PDFTool().run(
            ctx,
            action="extract_text",
            source=str(sample_pdf),
            max_chars=5,
        )
        assert out.metadata["truncated"] is True
        assert "…(truncated)" in out.text
        # Marker plus (at most) 5 original chars → short string.
        assert len(out.text) <= 5 + len("\n…(truncated)")

    def test_extract_pages_returns_structured_list(
        self, ctx: ToolContext, sample_pdf: Path
    ) -> None:
        pytest.importorskip("pypdf")
        out = PDFTool().run(
            ctx, action="extract_pages", source=str(sample_pdf)
        )
        pages = out.metadata["pages"]
        assert isinstance(pages, list)
        assert len(pages) == 3
        for entry in pages:
            assert "page" in entry
            assert "text" in entry
        assert pages[0]["page"] == 1
        assert "Extracted 3 pages" in out.text

    def test_metadata_returns_structured_dict(
        self, ctx: ToolContext, sample_pdf: Path
    ) -> None:
        pytest.importorskip("pypdf")
        out = PDFTool().run(ctx, action="metadata", source=str(sample_pdf))
        md = out.metadata
        for key in (
            "title",
            "author",
            "subject",
            "creator",
            "producer",
            "creation_date",
            "modification_date",
            "page_count",
        ):
            assert key in md
        assert md["page_count"] == 3

    def test_url_fetch_via_mock(
        self, ctx: ToolContext, sample_pdf: Path
    ) -> None:
        pytest.importorskip("pypdf")
        raw = sample_pdf.read_bytes()

        class _FakeResponse:
            def __init__(self, data: bytes) -> None:
                self._buf = BytesIO(data)

            def read(self) -> bytes:
                return self._buf.read()

            def __enter__(self) -> "_FakeResponse":
                return self

            def __exit__(self, *exc: object) -> None:
                self._buf.close()

        def fake_urlopen(url: str, timeout: int = 30) -> _FakeResponse:
            assert url.startswith("https://")
            return _FakeResponse(raw)

        with patch(
            "shipit_agent.tools.pdf.pdf_tool.urllib.request.urlopen",
            side_effect=fake_urlopen,
        ):
            out = PDFTool().run(
                ctx,
                action="extract_text",
                source="https://example.com/sample.pdf",
            )
        assert "Page one hello" in out.text
        assert out.metadata["pages_extracted"] == 3
