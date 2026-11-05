"""Artifacts: a stable id, versions on disk, update in place, and no escaping.

Like Claude's artifacts, one deliverable keeps one identifier while it is
created, edited and rewritten; every change is a new version, earlier
versions stay readable, and nothing is written outside the artifacts folder.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shipit_agent.tools.artifact_builder.artifact_builder_tool import (
    ArtifactBuilderTool,
)
from shipit_agent.tools.base import ToolContext


@pytest.fixture
def tool_and_ctx(tmp_path: Path) -> tuple[ArtifactBuilderTool, ToolContext, Path]:
    root = tmp_path / "artifacts"
    return (
        ArtifactBuilderTool(workspace_root=root),
        ToolContext(prompt="t", state={}),
        root,
    )


def test_create_saves_version_one(tool_and_ctx) -> None:
    tool, ctx, root = tool_and_ctx
    out = tool.run(
        ctx,
        id="q3-report",
        title="Q3 report",
        type="markdown",
        content="# Q3\n\nRevenue up.\n",
    )
    assert not out.metadata.get("is_error")
    artifact = out.metadata["artifact"]
    assert artifact["id"] == "q3-report" and artifact["version"] == 1
    assert Path(artifact["path"]).read_text() == "# Q3\n\nRevenue up.\n"
    assert Path(artifact["path"]).suffix == ".md"
    assert "q3-report" in out.text and "v1" in out.text


def test_update_replaces_exact_text_as_a_new_version(tool_and_ctx) -> None:
    tool, ctx, root = tool_and_ctx
    tool.run(ctx, id="q3-report", type="markdown", content="# Q3\n\nRevenue up.\n")
    out = tool.run(
        ctx,
        id="q3-report",
        action="update",
        old_text="Revenue up.",
        new_text="Revenue up 12%.",
    )
    artifact = out.metadata["artifact"]
    assert artifact["version"] == 2
    assert Path(artifact["path"]).read_text() == "# Q3\n\nRevenue up 12%.\n"
    versions = sorted(p.name for p in (root / "q3-report").glob("v*"))
    assert versions == ["v1.md", "v2.md"]
    assert (root / "q3-report" / "v1.md").read_text() == "# Q3\n\nRevenue up.\n"


def test_rewrite_replaces_everything(tool_and_ctx) -> None:
    tool, ctx, _ = tool_and_ctx
    tool.run(ctx, id="page", type="html", content="<p>old</p>")
    out = tool.run(ctx, id="page", action="rewrite", content="<p>new</p>")
    assert out.metadata["artifact"]["version"] == 2
    assert Path(out.metadata["artifact"]["path"]).read_text() == "<p>new</p>"


def test_latest_always_points_at_the_newest_version(tool_and_ctx) -> None:
    tool, ctx, root = tool_and_ctx
    tool.run(ctx, id="page", type="html", content="<p>1</p>")
    tool.run(ctx, id="page", action="rewrite", content="<p>2</p>")
    assert (root / "page" / "latest.html").read_text() == "<p>2</p>"


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        (
            {"id": "missing", "action": "update", "old_text": "a", "new_text": "b"},
            "unknown_artifact",
        ),
        (
            {"id": "doc", "action": "update", "old_text": "zzz", "new_text": "b"},
            "old_text_not_found",
        ),
        (
            {"id": "doc", "action": "update", "old_text": "same", "new_text": "b"},
            "old_text_not_unique",
        ),
        ({"id": "doc", "action": "create", "content": "again"}, "already_exists"),
        ({"id": "doc", "action": "explode", "content": "x"}, "invalid_action"),
    ],
)
def test_mistakes_are_error_results(tool_and_ctx, kwargs, error) -> None:
    tool, ctx, _ = tool_and_ctx
    tool.run(ctx, id="doc", type="text", content="same and same")
    out = tool.run(ctx, **kwargs)
    assert out.metadata["is_error"] is True
    assert out.metadata["error"] == error


@pytest.mark.parametrize("bad_id", ["../escape", "/abs/path", "a/b", "..", ""])
def test_an_id_cannot_leave_the_artifacts_folder(tool_and_ctx, bad_id: str) -> None:
    tool, ctx, root = tool_and_ctx
    out = tool.run(ctx, id=bad_id, type="text", content="x")
    assert out.metadata["is_error"] is True
    assert not any(p.is_file() for p in root.parent.rglob("*") if root not in p.parents)


def test_the_old_export_path_cannot_escape_either(tool_and_ctx) -> None:
    tool, ctx, root = tool_and_ctx
    out = tool.run(
        ctx, name="notes", content="x", export=True, path="../../outside.txt"
    )
    assert out.metadata["is_error"] is True
    assert not (root.parent.parent / "outside.txt").exists()


def test_the_old_parameters_still_work(tool_and_ctx) -> None:
    tool, ctx, _ = tool_and_ctx
    out = tool.run(
        ctx,
        name="summary.md",
        content="# Hi\n",
        media_type="text/markdown",
        export=True,
    )
    artifact = out.metadata["artifact"]
    assert artifact["version"] == 1
    assert Path(artifact["path"]).read_text() == "# Hi\n"
    assert ctx.state["artifacts"][-1]["id"] == artifact["id"]


def test_the_run_state_records_each_version(tool_and_ctx) -> None:
    tool, ctx, _ = tool_and_ctx
    tool.run(ctx, id="doc", type="text", content="a")
    tool.run(ctx, id="doc", action="rewrite", content="b")
    assert [(a["id"], a["version"]) for a in ctx.state["artifacts"]] == [
        ("doc", 1),
        ("doc", 2),
    ]


def test_code_artifacts_use_the_languages_extension(tool_and_ctx) -> None:
    tool, ctx, _ = tool_and_ctx
    out = tool.run(
        ctx, id="parser", type="code", language="python", content="print(1)\n"
    )
    assert Path(out.metadata["artifact"]["path"]).suffix == ".py"
