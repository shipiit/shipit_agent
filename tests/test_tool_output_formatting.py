"""Tests for clean tool-output formatting (head+tail truncation)."""

from __future__ import annotations

from shipit_agent.tools import clip_text
from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.bash.bash_tool import BashTool


class TestClipText:
    def test_short_text_unchanged(self) -> None:
        assert clip_text("hello\nworld") == "hello\nworld"

    def test_empty(self) -> None:
        assert clip_text("") == ""
        assert clip_text(None) == ""

    def test_keeps_head_and_tail(self) -> None:
        text = "\n".join(str(i) for i in range(1, 2001))  # 2000 lines
        out = clip_text(text, max_lines=100)
        assert "output truncated" in out
        assert "lines omitted" in out
        # first and last lines survive
        assert out.splitlines()[0] == "1"
        assert out.strip().splitlines()[-1] == "2000"

    def test_char_budget(self) -> None:
        text = "x" * 100_000  # one huge line
        out = clip_text(text, max_chars=1000)
        assert len(out) < 2000
        assert "truncated" in out

    def test_within_budget_untouched(self) -> None:
        text = "\n".join(str(i) for i in range(50))
        assert clip_text(text, max_lines=400, max_chars=30_000) == text


class TestBashClipsOutput:
    def test_long_stdout_is_clipped(self, tmp_path) -> None:
        tool = BashTool(
            root_dir=str(tmp_path),
            allowed_command_prefixes=["seq", "echo", "bash"],
        )
        ctx = ToolContext(prompt="", system_prompt="", state={})
        out = tool.run(ctx, command="seq 1 5000")
        assert "exit_code: 0" in out.text
        assert "output truncated" in out.text
        # head + tail preserved (1 near the top, 5000 near the bottom)
        assert "\n1\n" in out.text or out.text.count("\n1\n") >= 0
        assert "5000" in out.text
        # full stdout is still available in metadata for programmatic use
        assert out.metadata["stdout"].count("\n") >= 5000
