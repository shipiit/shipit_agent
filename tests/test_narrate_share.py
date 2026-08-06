"""Shareable transcripts — a run as one self-contained HTML file."""

from __future__ import annotations

import json
import re

import pytest

from shipit_agent.models import AgentEvent
from shipit_agent.narrate.share import (
    render_transcript_html,
    transcript_json,
    write_transcript,
)


def called(tool, call_id, **arguments):
    return AgentEvent(type="tool_called", message="", payload={
        "tool": tool, "call_id": call_id, "arguments": arguments})


def completed(tool, call_id, output="ok"):
    return AgentEvent(type="tool_completed", message="", payload={
        "tool": tool, "call_id": call_id, "output": output, "duration_ms": 12})


def text(chunk):
    return AgentEvent(type="text_delta", message="", payload={"chunk": chunk})


def done(output="", **usage):
    return AgentEvent(type="run_completed", message="",
                      payload={"output": output, "usage": usage})


RUN = [
    AgentEvent(type="run_started", message="", payload={"prompt": "Fix the login bug"}),
    called("read_file", "1", path="auth.py"),
    completed("read_file", "1", output="def login(): ..."),
    called("read_file", "2", path="views.py"),
    completed("read_file", "2"),
    text("The session cookie was never set on redirect."),
    called("edit_file", "3", path="auth.py"),
    completed("edit_file", "3", output="1 replacement"),
    AgentEvent(type="action_queued", message="", payload={
        "tool": "slack", "action_id": 1, "title": "Used Slack #eng",
        "tag": "comms.send", "auto_approved": False}),
    text("Fixed. Told the team."),
    done(total_tokens=18_240),
]


class TestStructure:
    def test_it_is_one_self_contained_document(self) -> None:
        page = render_transcript_html(RUN)
        assert page.startswith("<!doctype html>")
        assert "</html>" in page
        # No network: it must open from file:// and survive being emailed.
        assert "<script src=" not in page
        assert "<link rel=" not in page
        assert not re.search(r'(src|href)=["\']https?://', page)

    def test_styles_are_inlined(self) -> None:
        assert "<style>" in render_transcript_html(RUN)

    def test_no_javascript_beyond_native_disclosure(self) -> None:
        page = render_transcript_html(RUN)
        assert "<script" not in page
        assert "<details" in page  # the toggles are native

    def test_it_renders_in_both_themes(self) -> None:
        assert "prefers-color-scheme: dark" in render_transcript_html(RUN)


class TestContent:
    def test_work_runs_collapse_the_same_way(self) -> None:
        page = render_transcript_html(RUN)
        assert "Read 2 files" in page  # not two separate rows
        assert "auth.py · views.py" in page

    def test_prose_is_included(self) -> None:
        assert "session cookie was never set" in render_transcript_html(RUN)

    def test_tool_output_is_in_the_disclosure(self) -> None:
        assert "def login()" in render_transcript_html(RUN)

    def test_queued_approvals_are_shown(self) -> None:
        page = render_transcript_html(RUN)
        assert "Used Slack #eng" in page
        assert "comms.send" in page
        assert "awaiting approval" in page

    def test_the_footer_carries_the_bill(self) -> None:
        page = render_transcript_html(RUN, model="claude-opus-5")
        assert "18,240 tokens" in page
        assert "claude-opus-5" in page

    def test_the_prompt_is_shown(self) -> None:
        assert "Fix the login bug" in render_transcript_html(RUN)

    def test_title_is_used(self) -> None:
        assert "<title>Nightly run</title>" in render_transcript_html(
            RUN, title="Nightly run"
        )

    def test_errors_are_marked(self) -> None:
        page = render_transcript_html([
            called("bash", "1", command="ls /nope"),
            AgentEvent(type="tool_failed", message="", payload={
                "tool": "bash", "call_id": "1", "error": "no such directory"}),
            done(),
        ])
        assert "error" in page and "no such directory" in page


class TestEscaping:
    def test_tool_output_cannot_inject_markup(self) -> None:
        page = render_transcript_html([
            called("read_file", "1", path="x.html"),
            completed("read_file", "1", output="<script>alert(1)</script>"),
            done(),
        ])
        assert "<script>alert(1)</script>" not in page
        assert "&lt;script&gt;" in page

    def test_prose_cannot_inject_markup(self) -> None:
        page = render_transcript_html([text("<img src=x onerror=alert(1)>"), done()])
        assert "onerror=alert(1)>" not in page
        assert "&lt;img" in page

    def test_a_malicious_filename_cannot_break_out(self) -> None:
        page = render_transcript_html([
            called("read_file", "1", path='"><script>x</script>'),
            completed("read_file", "1"),
            done(),
        ])
        assert "<script>x</script>" not in page

    def test_the_prompt_is_escaped(self) -> None:
        page = render_transcript_html([
            AgentEvent(type="run_started", message="",
                       payload={"prompt": "<b>bold</b>"}),
            done(),
        ])
        assert "<b>bold</b>" not in page


class TestWriting:
    def test_writes_a_file(self, tmp_path) -> None:
        target = write_transcript(tmp_path / "run.html", RUN)
        assert target.exists()
        assert target.read_text().startswith("<!doctype html>")

    def test_extension_is_added(self, tmp_path) -> None:
        assert write_transcript(tmp_path / "run", RUN).suffix == ".html"

    def test_parent_directories_are_created(self, tmp_path) -> None:
        target = write_transcript(tmp_path / "a" / "b" / "run.html", RUN)
        assert target.exists()

    def test_returns_a_resolved_path(self, tmp_path) -> None:
        assert write_transcript(tmp_path / "run.html", RUN).is_absolute()


class TestJson:
    def test_rows_serialize(self) -> None:
        rows = json.loads(transcript_json(RUN))
        kinds = [r["type"] for r in rows]
        assert kinds == ["work", "prose", "work", "approval", "prose"]

    def test_work_rows_carry_their_calls(self) -> None:
        rows = json.loads(transcript_json(RUN))
        work = rows[0]
        assert work["label"] == "Read 2 files"
        assert [c["tool"] for c in work["calls"]] == ["read_file", "read_file"]


class TestRobustness:
    def test_an_empty_run_still_renders(self) -> None:
        assert render_transcript_html([]).startswith("<!doctype html>")

    def test_it_accepts_an_agent_result(self) -> None:
        class FakeResult:
            events = RUN

        assert "Read 2 files" in render_transcript_html(FakeResult())

    @pytest.mark.parametrize("bad", [None, 42, {"a": 1}])
    def test_odd_payload_values_do_not_raise(self, bad) -> None:
        event = AgentEvent(type="tool_called", message="", payload={
            "tool": "x", "call_id": "1", "arguments": {"v": bad}})
        assert render_transcript_html([event, done()])

    def test_very_long_output_is_truncated(self) -> None:
        page = render_transcript_html([
            called("bash", "1", command="yes"),
            completed("bash", "1", output="x" * 100_000),
            done(),
        ])
        assert len(page) < 40_000
