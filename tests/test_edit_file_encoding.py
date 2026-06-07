"""Encoding-corruption regression tests for EditFileTool / FileReadTool (SEC-6).

Reading with errors="replace" then writing back turned invalid bytes into
U+FFFD while reporting "File patched". edit_file now refuses to edit
non-UTF-8 files; file_read stays lossy for display but flags the replacement.
"""

from __future__ import annotations

from pathlib import Path

from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.edit_file.edit_file_tool import EditFileTool
from shipit_agent.tools.file_read.file_read_tool import FileReadTool


def _ctx(state: dict) -> ToolContext:
    return ToolContext(prompt="t", state=state)


class TestEditFileRefusesNonUtf8:
    def test_non_utf8_file_is_not_corrupted(self, tmp_path: Path) -> None:
        target = tmp_path / "bin.dat"
        original = b"hello \xff\xfe world"
        target.write_bytes(original)

        state = {"read_files": [str(target)]}
        tool = EditFileTool(root_dir=tmp_path)
        out = tool.run(
            _ctx(state),
            path=str(target),
            old_text="hello",
            new_text="HELLO",
        )

        # Refused, with a clear error and no mutation.
        assert out.metadata.get("error") == "not_utf8"
        assert "refused" in out.text.lower()
        assert target.read_bytes() == original

    def test_valid_utf8_still_edits(self, tmp_path: Path) -> None:
        target = tmp_path / "ok.txt"
        target.write_text("hello world", encoding="utf-8")
        state = {"read_files": [str(target)]}
        tool = EditFileTool(root_dir=tmp_path)
        out = tool.run(
            _ctx(state),
            path=str(target),
            old_text="hello",
            new_text="HELLO",
        )
        assert "patched" in out.text.lower()
        assert target.read_text(encoding="utf-8") == "HELLO world"


class TestFileReadFlagsReplacement:
    def test_non_utf8_read_flags_replacement(self, tmp_path: Path) -> None:
        target = tmp_path / "bin.dat"
        target.write_bytes(b"hello \xff\xfe world")
        tool = FileReadTool(root_dir=tmp_path)
        out = tool.run(_ctx({}), path=str(target))
        assert out.metadata.get("utf8_replacement") is True
        assert "not valid utf-8" in out.text.lower()

    def test_valid_utf8_read_not_flagged(self, tmp_path: Path) -> None:
        target = tmp_path / "ok.txt"
        target.write_text("plain ascii", encoding="utf-8")
        tool = FileReadTool(root_dir=tmp_path)
        out = tool.run(_ctx({}), path=str(target))
        assert out.metadata.get("utf8_replacement") is False
