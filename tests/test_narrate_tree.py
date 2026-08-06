"""The tree renderer — structure over prose."""

from __future__ import annotations

import io
import re

import pytest

from shipit_agent.models import AgentEvent
from shipit_agent.narrate.tree import TreeRenderer, render_tree


def called(tool, call_id, **arguments):
    return AgentEvent(type="tool_called", message="", payload={
        "tool": tool, "call_id": call_id, "arguments": arguments})


def completed(tool, call_id, ms=12):
    return AgentEvent(type="tool_completed", message="", payload={
        "tool": tool, "call_id": call_id, "output": "ok", "duration_ms": ms})


def failed(tool, call_id, error="boom"):
    return AgentEvent(type="tool_failed", message="", payload={
        "tool": tool, "call_id": call_id, "error": error})


def denied(tool, call_id, reason="on the deny list"):
    return AgentEvent(type="tool_denied", message="", payload={
        "tool": tool, "call_id": call_id, "reason": reason})


def text(chunk):
    return AgentEvent(type="text_delta", message="", payload={"chunk": chunk})


def queued(tool="slack", action_id=1, tag="comms.send", auto=False):
    return AgentEvent(type="action_queued", message="", payload={
        "tool": tool, "action_id": action_id, "title": f"Used {tool}",
        "tag": tag, "auto_approved": auto})


def done(output="", **usage):
    return AgentEvent(type="run_completed", message="",
                      payload={"output": output, "usage": usage})


RUN = [
    text("The RSVP details were extracted. Now check for an existing record."),
    called("read_file", "1", path="guests.csv"),
    completed("read_file", "1", ms=4),
    called("read_file", "2", path="events.csv"),
    completed("read_file", "2", ms=6),
    text("Guest was not found. Create a new RSVP record."),
    queued(),
    text("RSVP successfully recorded."),
    done(total_tokens=15_470),
]


class TestShape:
    def test_it_opens_with_a_root(self) -> None:
        assert render_tree(RUN).startswith("Agent started")

    def test_branches_and_a_final_corner(self) -> None:
        out = render_tree(RUN)
        assert "├─" in out
        assert "└─" in out
        # Exactly one corner: the last branch.
        assert out.count("└─ ") == 1 or "└─ Final answer" in out

    def test_the_last_prose_is_the_answer(self) -> None:
        out = render_tree(RUN)
        assert "└─ Final answer" in out
        assert "RSVP successfully recorded." in out

    def test_earlier_prose_is_a_decision(self) -> None:
        out = render_tree(RUN)
        # The opening prose is the agent saying what it is about to do; every
        # later one is a decision it reached along the way.
        assert out.count("Understanding request") == 1
        assert out.count("Decision") == 1
        assert out.index("Understanding request") < out.index("Decision")

    def test_the_only_prose_in_a_run_is_the_answer(self) -> None:
        out = render_tree([text("Done."), done("Done.")])
        assert "Final answer" in out
        assert "Understanding request" not in out

    def test_a_work_run_becomes_a_tool_group(self) -> None:
        out = render_tree(RUN)
        assert "Tool group: Read 2 files" in out

    def test_each_call_is_named_with_its_status(self) -> None:
        out = render_tree(RUN)
        assert out.count("read_file") >= 2
        assert out.count("completed") == 2

    def test_durations_are_shown(self) -> None:
        out = render_tree(RUN)
        assert "4ms" in out and "6ms" in out

    def test_an_approval_is_its_own_branch(self) -> None:
        out = render_tree(RUN)
        assert "Approval required" in out
        assert "comms.send" in out

    def test_the_footer_carries_the_bill(self) -> None:
        assert "15,470 tokens" in render_tree(RUN, model="gemma-4")
        assert "gemma-4" in render_tree(RUN, model="gemma-4")


class TestStatuses:
    @pytest.mark.parametrize("events,expected", [
        ([called("bash", "1"), completed("bash", "1")], "completed"),
        ([called("bash", "1"), failed("bash", "1")], "failed"),
        ([called("bash", "1"), denied("bash", "1")], "blocked"),
    ])
    def test_each_outcome_reads_plainly(self, events, expected) -> None:
        assert expected in render_tree([*events, done()])


class TestAlignment:
    def test_statuses_line_up_regardless_of_depth(self) -> None:
        """A nested row starts further right; without accounting for the tree
        drawing, the status column drifts and the fixed column is pointless."""
        out = render_tree(RUN)
        columns = {
            line.index(word)
            for line in out.splitlines()
            for word in ("completed", "comms.send")
            if word in line
        }
        assert len(columns) == 1, f"statuses at differing columns: {columns}"

    def test_colour_does_not_shift_the_column(self) -> None:
        buffer = io.StringIO()
        renderer = TreeRenderer(file=buffer, color=True)
        for event in RUN:
            renderer.feed(event)
        renderer.close()
        plain = re.sub(r"\033\[[0-9;]*m", "", buffer.getvalue())
        columns = {
            line.index("completed") for line in plain.splitlines()
            if "completed" in line
        }
        assert len(columns) == 1


class TestRobustness:
    def test_an_empty_run_still_renders(self) -> None:
        assert render_tree([]).startswith("Agent started")

    def test_a_run_with_no_prose(self) -> None:
        out = render_tree([called("read_file", "1", path="a"),
                           completed("read_file", "1"), done()])
        assert "Tool group" in out

    def test_a_run_with_no_tools(self) -> None:
        assert "Final answer" in render_tree([text("Just an answer."), done()])

    def test_empty_prose_is_not_rendered(self) -> None:
        out = render_tree([text("   "), called("read_file", "1", path="a"),
                           completed("read_file", "1"), done()])
        assert "Decision" not in out

    def test_notices_appear(self) -> None:
        out = render_tree([
            AgentEvent(type="lockdown_engaged", message="",
                       payload={"reason": "customer PII"}),
            done(),
        ])
        assert "Note" in out and "customer PII" in out

    def test_sub_agent_work_is_attributed(self) -> None:
        out = render_tree([
            AgentEvent(type="sub_agent_event", message="", payload={
                "agent": "researcher", "task": "Summarize auth",
                "inner_type": "tool_called",
                "inner": {"tool": "read_file", "call_id": "c1",
                          "arguments": {"path": "auth.py"}}}),
            done(),
        ])
        assert "Delegated" in out and "Summarize auth" in out

    def test_ascii_fallback(self) -> None:
        class AsciiBuffer(io.StringIO):
            encoding = "ascii"

        buffer = AsciiBuffer()
        renderer = TreeRenderer(file=buffer, color=False)
        for event in RUN:
            renderer.feed(event)
        renderer.close()
        out = buffer.getvalue()
        assert "|" in out and "+-" in out
        for glyph in ("│", "├─", "└─"):
            assert glyph not in out

    def test_no_escape_codes_when_colour_is_off(self) -> None:
        assert "\033" not in render_tree(RUN)


class TestAgentIntegration:
    def test_run_live_style_tree(self) -> None:
        from shipit_agent import Agent
        from shipit_agent.llms.base import LLMResponse

        class L:
            model = "m"

            def complete(self, **kw):
                return LLMResponse(content="done", usage={"total_tokens": 10})

        buffer = io.StringIO()
        Agent(llm=L(), auto_use_skills=False).run_live("x", file=buffer, style="tree")
        out = buffer.getvalue()
        assert out.startswith("Agent started")
        assert "Final answer" in out

    def test_an_unknown_style_is_an_error_not_a_silent_fallback(self) -> None:
        import pytest

        from shipit_agent import Agent
        from shipit_agent.llms.base import LLMResponse

        class L:
            model = "m"

            def complete(self, **kw):
                return LLMResponse(content="done", usage={})

        with pytest.raises(ValueError, match="tree"):
            Agent(llm=L(), auto_use_skills=False).run_live("x", style="treee")


class TestDetailMode:
    def test_detail_shows_arguments_and_output(self) -> None:
        out = render_tree(RUN, detail=True)
        assert "↳ " in out, "arguments should be visible"
        plain = render_tree(RUN)
        assert len(out.splitlines()) > len(plain.splitlines())

    def test_detail_is_off_by_default(self) -> None:
        assert "↳ " not in render_tree(RUN)

    def test_long_output_is_truncated_with_a_count(self) -> None:
        events = [
            called("read_file", "1", path="a"),
            AgentEvent(type="tool_completed", message="", payload={
                "tool": "read_file", "call_id": "1",
                "output": "\n".join(f"line {n}" for n in range(40))}),
            done("ok"),
        ]
        out = render_tree(events, detail=True, output_lines=3)
        assert "line 2" in out and "line 30" not in out
        assert "… 37 more lines" in out


class TestLiveTree:
    def test_it_redraws_in_place_on_a_terminal(self) -> None:
        buffer = io.StringIO()
        renderer = TreeRenderer(file=buffer, color=False, live=True)
        renderer.feed(called("read_file", "1", path="a.py"))
        first = buffer.getvalue()
        renderer.feed(completed("read_file", "1"))
        out = buffer.getvalue()
        assert "\033[" in out, "a live tree rewinds over what it drew"
        assert len(out) > len(first)

    def test_the_finished_tree_is_written_once(self) -> None:
        buffer = io.StringIO()
        renderer = TreeRenderer(file=buffer, color=False, live=True)
        for event in RUN:
            renderer.feed(event)
        renderer.close()
        # The drafts are erased; exactly one finished tree remains at the end.
        tail = buffer.getvalue().split("\033[J")[-1]
        assert tail.count("Agent started") == 1
        assert "working…" not in tail
        assert "└─ Final answer" in tail

    def test_a_live_render_never_claims_the_run_is_over(self) -> None:
        renderer = TreeRenderer(file=io.StringIO(), color=False, live=False)
        for event in RUN[:4]:
            renderer.feed(event)
        live = renderer.render(live=True)
        assert "working…" in live
        assert "Final answer" not in live

    def test_piped_output_does_not_animate(self) -> None:
        buffer = io.StringIO()          # not a TTY → live defaults off
        renderer = TreeRenderer(file=buffer, color=False)
        for event in RUN:
            renderer.feed(event)
        assert buffer.getvalue() == ""  # nothing until close()
        renderer.close()
        assert "\033[" not in buffer.getvalue()

    def test_in_flight_calls_show_as_running(self) -> None:
        renderer = TreeRenderer(file=io.StringIO(), color=False, live=False)
        renderer.feed(called("read_file", "1", path="a.py"))
        assert "running" in renderer.render(live=True)
