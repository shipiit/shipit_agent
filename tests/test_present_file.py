"""present_file — surfaces an existing file as a downloadable deliverable, with
an inline preview for images, a sandbox guard, and clean errors for a missing
file. Also confirms the runtime's artifact tracker picks up its `path`."""

from __future__ import annotations

import base64

from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.present_file import PresentFileTool

# A 1x1 PNG — real bytes.
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _ctx():
    return ToolContext(prompt="")


def test_presents_a_file_with_download_metadata(tmp_path):
    f = tmp_path / "report.pdf"
    f.write_bytes(b"%PDF-1.4 ...")
    out = PresentFileTool().run(_ctx(), path=str(f), title="Q3 Report")
    m = out.metadata
    assert m["ok"] is True and m["download"] is True
    assert m["kind"] == "pdf" and m["title"] == "Q3 Report"
    assert m["path"] == str(f) and m["media"] == str(f)
    assert f"MEDIA:{f}" in out.text


def test_image_previews_inline_via_vision_bridge(tmp_path):
    f = tmp_path / "chart.png"
    f.write_bytes(_PNG)
    out = PresentFileTool().run(_ctx(), path=str(f))
    assert out.metadata["kind"] == "image"
    assert out.metadata["vision"] is True
    assert out.metadata["media_type"] == "image/png"
    assert base64.b64decode(out.metadata["image_base64"]) == _PNG


def test_kind_inferred_from_suffix(tmp_path):
    for name, kind in [("a.mp3", "audio"), ("a.mp4", "video"), ("a.csv", "spreadsheet"),
                       ("a.docx", "document"), ("a.bin", "file")]:
        f = tmp_path / name
        f.write_bytes(b"x")
        assert PresentFileTool().run(_ctx(), path=str(f)).metadata["kind"] == kind


def test_missing_path_is_required():
    out = PresentFileTool().run(_ctx(), path="  ")
    assert out.metadata["ok"] is False and "required" in out.text


def test_nonexistent_file_is_a_clean_error(tmp_path):
    out = PresentFileTool().run(_ctx(), path=str(tmp_path / "nope.png"))
    assert out.metadata["ok"] is False and "no file to present" in out.text


def test_sandbox_root_blocks_escape(tmp_path):
    (tmp_path / "in.txt").write_text("ok", encoding="utf-8")
    tool = PresentFileTool(root_dir=tmp_path)
    assert tool.run(_ctx(), path="in.txt").metadata["ok"] is True   # relative, inside
    out = tool.run(_ctx(), path="/etc/hosts")                       # absolute, outside
    assert out.metadata["ok"] is False and "escapes" in out.text


def test_runtime_artifact_tracker_reads_the_path(tmp_path):
    # The download machinery relies on `_declared_paths` seeing `path` on an
    # existing file — assert that contract holds for present_file's metadata.
    from shipit_agent.runtime_core import _declared_paths

    f = tmp_path / "deliverable.csv"
    f.write_text("a,b\n1,2\n", encoding="utf-8")
    meta = PresentFileTool().run(_ctx(), path=str(f)).metadata
    assert f in _declared_paths(meta)
