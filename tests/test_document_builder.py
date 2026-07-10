"""Tests for DocumentBuilderTool — polished PDF/XLSX/DOCX/PPTX/HTML output."""

from __future__ import annotations

import pytest

from shipit_agent.tools import DocumentBuilderTool
from shipit_agent.tools.base import ToolContext

CTX = ToolContext(prompt="", system_prompt="", state={})

SECTIONS = [
    {
        "heading": "Q2 Highlights",
        "body": "Revenue grew 24% quarter over quarter.",
        "bullets": ["ARR up 24%", "Churn down to 1.1%"],
        "table": {
            "headers": ["Metric", "Q1", "Q2"],
            "rows": [["Revenue", 100, 124], ["Churn %", 1.4, 1.1]],
        },
    },
    {"heading": "Risks", "bullets": ["FX exposure", "Hiring pace"]},
]


def _tool(tmp_path):
    return DocumentBuilderTool(workspace_root=tmp_path)


class TestHTML:
    def test_builds_styled_html(self, tmp_path) -> None:
        out = _tool(tmp_path).run(
            CTX, kind="html", title="Q2 Report", sections=SECTIONS
        )
        assert out.metadata["ok"] is True
        content = open(out.metadata["path"], encoding="utf-8").read()
        assert "<h1>Q2 Report</h1>" in content
        assert "<table>" in content and "Churn" in content
        assert "ARR up 24%" in content

    def test_escapes_html_in_content(self, tmp_path) -> None:
        out = _tool(tmp_path).run(
            CTX,
            kind="html",
            title="<script>x</script>",
            sections=[{"body": "<b>raw</b>"}],
        )
        content = open(out.metadata["path"], encoding="utf-8").read()
        assert "<script>x</script>" not in content
        assert "&lt;b&gt;raw&lt;/b&gt;" in content


class TestPDF:
    def test_builds_pdf(self, tmp_path) -> None:
        pytest.importorskip("reportlab")
        out = _tool(tmp_path).run(
            CTX, kind="pdf", title="Q2 Report", sections=SECTIONS
        )
        assert out.metadata["ok"] is True
        assert open(out.metadata["path"], "rb").read(5) == b"%PDF-"
        assert out.metadata["bytes"] > 1000


class TestXLSX:
    def test_builds_workbook_with_styles_and_formulas(self, tmp_path) -> None:
        openpyxl = pytest.importorskip("openpyxl")
        out = _tool(tmp_path).run(
            CTX,
            kind="xlsx",
            title="Model",
            sheets=[
                {
                    "name": "P&L",
                    "headers": ["Item", "Amount"],
                    "rows": [["Revenue", 124], ["Costs", -80], ["Net", "=B2+B3"]],
                }
            ],
        )
        assert out.metadata["ok"] is True
        wb = openpyxl.load_workbook(out.metadata["path"])
        ws = wb["P&L"]
        assert ws["A1"].value == "Item"
        assert ws["A1"].font.bold
        assert ws.freeze_panes == "A2"
        assert ws["B4"].value == "=B2+B3"  # live formula


class TestDOCXAndPPTX:
    def test_builds_docx(self, tmp_path) -> None:
        docx = pytest.importorskip("docx")
        out = _tool(tmp_path).run(
            CTX, kind="docx", title="Spec", sections=SECTIONS
        )
        assert out.metadata["ok"] is True
        doc = docx.Document(out.metadata["path"])
        texts = [p.text for p in doc.paragraphs]
        assert "Spec" in texts and "Q2 Highlights" in texts

    def test_builds_pptx_one_slide_per_section(self, tmp_path) -> None:
        pptx = pytest.importorskip("pptx")
        out = _tool(tmp_path).run(
            CTX, kind="pptx", title="Board Deck", sections=SECTIONS
        )
        assert out.metadata["ok"] is True
        prs = pptx.Presentation(out.metadata["path"])
        assert len(prs.slides) == 1 + len(SECTIONS)  # title + sections


class TestErrorsAndPaths:
    def test_unknown_kind(self, tmp_path) -> None:
        out = _tool(tmp_path).run(CTX, kind="gif", title="x")
        assert out.metadata["ok"] is False
        assert "Choose one of" in out.text

    def test_title_slug_and_suffix(self, tmp_path) -> None:
        out = _tool(tmp_path).run(
            CTX, kind="html", title="My Q2: Report!", sections=[]
        )
        assert out.metadata["path"].endswith("my_q2_report.html")

    def test_explicit_path_gets_correct_suffix(self, tmp_path) -> None:
        out = _tool(tmp_path).run(
            CTX,
            kind="html",
            title="T",
            sections=[],
            path=str(tmp_path / "report.txt"),
        )
        assert out.metadata["path"].endswith("report.html")

    def test_schema_lists_all_kinds(self, tmp_path) -> None:
        schema = _tool(tmp_path).schema()
        kinds = schema["function"]["parameters"]["properties"]["kind"]["enum"]
        assert kinds == ["docx", "html", "pdf", "pptx", "xlsx"]


class TestForRole:
    def test_for_role_builds_sector_agent(self) -> None:
        from shipit_agent import Agent

        class _L:
            def complete(self, **_kwargs):
                return None

        agent = Agent.for_role("finance-analyst", llm=_L())
        assert agent.name == "finance-analyst"
        assert agent.tools  # definition tools resolved from builtins
        assert "Finance Analyst" in agent.prompt

    def test_for_role_unknown_suggests(self) -> None:
        from shipit_agent import Agent

        class _L:
            def complete(self, **_kwargs):
                return None

        with pytest.raises(ValueError, match="finance-analyst"):
            Agent.for_role("finance", llm=_L())
