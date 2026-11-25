"""The PDF tool reads local files only inside the project, refuses internal URLs, and obeys Read rules."""

from __future__ import annotations

from pathlib import Path

import pytest

from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.pdf import PDFTool


@pytest.fixture
def ctx() -> ToolContext:
    return ToolContext(prompt="")


class TestStaysInTheProject:
    def test_a_local_pdf_outside_the_project_is_refused(self, ctx: ToolContext, tmp_path: Path) -> None:
        project, outside = tmp_path / "project", tmp_path / "outside"
        project.mkdir()
        outside.mkdir()
        (outside / "statement.pdf").write_bytes(b"%PDF-1.4\n")
        tool = PDFTool(root_dir=project)
        for source in (str(outside / "statement.pdf"), "../outside/statement.pdf"):
            out = tool.run(ctx, action="page_count", source=source)
            assert out.metadata.get("error") == "path_outside_project"

    def test_an_internal_url_is_refused(self, ctx: ToolContext, tmp_path: Path) -> None:
        out = PDFTool(root_dir=tmp_path).run(ctx, action="page_count", source="http://127.0.0.1:9/x.pdf")
        assert out.metadata.get("error") == "url_fetch_failed" and "blocked" in out.text


def test_read_rules_cover_the_pdf_tool(tmp_path: Path) -> None:
    from shipit_agent.safety.permissions import PermissionDecision, PermissionEngine

    engine = PermissionEngine(deny=["Read(secrets/**)"], root=str(tmp_path))
    assert engine.check("pdf", {"action": "extract_text", "source": "secrets/plan.pdf"}).decision == PermissionDecision.DENY
    assert engine.check("pdf", {"action": "extract_text", "source": "docs/plan.pdf"}).decision == PermissionDecision.ALLOW
    assert engine.check("pdf", {"action": "extract_text", "source": "https://x/secrets/a.pdf"}).decision == PermissionDecision.ALLOW
