"""Work runs — consecutive tool calls collapse; prose breaks the run."""

from __future__ import annotations

import pytest

from shipit_agent.models import AgentEvent
from shipit_agent.narrate.grouping import (
    CallRecord,
    NoticeRow,
    ProseRow,
    WorkRow,
    WorkRunAccumulator,
    build_group,
    build_transcript,
)


def call(name: str, call_id: str = "", **arguments) -> CallRecord:
    return CallRecord(
        call_id=call_id or f"c{name}{len(arguments)}",
        name=name,
        arguments=arguments,
        status="ok",
    )


def called(tool: str, call_id: str, **arguments) -> AgentEvent:
    return AgentEvent(
        type="tool_called",
        message="",
        payload={"tool": tool, "call_id": call_id, "arguments": arguments},
    )


def completed(tool: str, call_id: str, output: str = "ok", ms: float = 10) -> AgentEvent:
    return AgentEvent(
        type="tool_completed",
        message="",
        payload={
            "tool": tool,
            "call_id": call_id,
            "output": output,
            "duration_ms": ms,
        },
    )


def failed(tool: str, call_id: str, error: str = "boom") -> AgentEvent:
    return AgentEvent(
        type="tool_failed",
        message="",
        payload={"tool": tool, "call_id": call_id, "error": error},
    )


def text(chunk: str) -> AgentEvent:
    return AgentEvent(type="text_delta", message="", payload={"chunk": chunk})


def done(output: str = "", **usage) -> AgentEvent:
    return AgentEvent(
        type="run_completed", message="", payload={"output": output, "usage": usage}
    )


class TestLabels:
    def test_one_call_reads_as_a_sentence(self) -> None:
        group = build_group([call("read_file", path="app.py")])
        assert group.label == "Read app.py"

    def test_repeated_tool_becomes_a_count(self) -> None:
        group = build_group(
            [
                call("read_file", "a", path="app.py"),
                call("read_file", "b", path="models.py"),
                call("read_file", "c", path="views.py"),
            ]
        )
        assert group.label == "Read 3 files"

    def test_repeated_tool_on_one_target_keeps_the_target(self) -> None:
        # Three edits to the same file read better as the file than as a count.
        group = build_group([call("edit_file", str(i), path="app.py") for i in range(3)])
        assert group.label == "Edited app.py"

    def test_mixed_tools_compose_as_a_sentence(self) -> None:
        group = build_group(
            [
                call("read_file", "a", path="app.py"),
                call("read_file", "b", path="models.py"),
                call("read_file", "c", path="views.py"),
                call("edit_file", "d", path="app.py"),
                call("edit_file", "e", path="urls.py"),
            ]
        )
        # First part keeps its capital; the rest are lower-cased.
        assert group.label == "Read 3 files, made 2 edits"

    def test_lone_call_in_a_mixed_run_keeps_its_target(self) -> None:
        # "searched for" alone dangles; it needs its object.
        group = build_group(
            [
                call("read_file", "a", path="accounts.py"),
                call("read_file", "b", path="usage.py"),
                call("grep_files", "c", pattern="renewal_date"),
            ]
        )
        assert group.label == "Read 2 files, searched for renewal_date"

    def test_no_composite_label_ends_in_a_preposition(self) -> None:
        from shipit_agent.narrate.verbs import VERBS

        dangling = ("for", "at", "to", "the", "of", "in", "on", "you")
        for name in VERBS:
            group = build_group(
                [call("read_file", "a", path="x.py"), call(name, "b", query="q", path="p")]
            )
            assert group.label.split()[-1].lower().strip(",") not in dangling, (
                f"{name}: {group.label!r}"
            )

    def test_more_than_three_distinct_tools_collapses_to_a_count(self) -> None:
        group = build_group(
            [
                call("read_file", "a", path="a"),
                call("write_file", "b", path="b"),
                call("bash", "c", command="ls"),
                call("sql", "d", query="select 1"),
                call("build_document", "e", title="t"),
            ]
        )
        assert group.label == "5 tool calls"

    def test_many_read_only_tools_read_as_resource_reads(self) -> None:
        group = build_group(
            [
                call("read_file", "a", path="a"),
                call("web_search", "b", query="q"),
                call("grep_files", "c", pattern="p"),
                call("glob_files", "d", pattern="g"),
                call("deep_research", "e", query="r"),
            ]
        )
        assert group.label == "5 resource reads"

    def test_present_tense_variant(self) -> None:
        group = build_group(
            [call("write_file", str(i), path=f"{i}.py") for i in range(5)],
            present=True,
        )
        assert group.label == "Writing 5 files"

    def test_empty_returns_none(self) -> None:
        assert build_group([]) is None


class TestDetailLines:
    def test_single_target_is_not_repeated_below_the_label(self) -> None:
        group = build_group([call("read_file", path="app.py")])
        assert group.detail_lines == []

    def test_multiple_targets_are_listed(self) -> None:
        group = build_group(
            [
                call("read_file", "a", path="app.py"),
                call("read_file", "b", path="models.py"),
            ]
        )
        assert group.detail_lines == ["app.py", "models.py"]

    def test_targets_are_deduplicated_in_first_seen_order(self) -> None:
        group = build_group(
            [
                call("read_file", "a", path="app.py"),
                call("edit_file", "b", path="app.py"),
                call("read_file", "c", path="zzz.py"),
            ]
        )
        assert group.detail_lines == ["app.py", "zzz.py"]


class TestIcons:
    def test_a_run_of_one_tool_keeps_that_tools_glyph(self) -> None:
        from shipit_agent.narrate.verbs import FILE

        group = build_group([call("read_file", str(i), path=f"{i}.py") for i in range(3)])
        assert group.icon == FILE

    def test_a_single_call_keeps_its_glyph(self) -> None:
        from shipit_agent.narrate.verbs import LINK

        assert build_group([call("connections", action="list")]).icon == LINK

    def test_a_sweep_across_different_read_only_tools_uses_search(self) -> None:
        from shipit_agent.narrate.verbs import SEARCH

        group = build_group([
            call("read_file", "a", path="x"),
            call("web_search", "b", query="y"),
            call("grep_files", "c", pattern="z"),
        ])
        assert group.icon == SEARCH

    def test_a_mixed_run_with_an_action_uses_the_first_tools_glyph(self) -> None:
        from shipit_agent.narrate.verbs import FILE

        group = build_group([
            call("read_file", "a", path="x"),
            call("bash", "b", command="ls"),
        ])
        assert group.icon == FILE


class TestLoopMechanicsAreHidden:
    def test_healing_and_nudging_produce_no_row(self) -> None:
        """The user is never shown the loop's internal structure.

        "Recovered a tool call" after a good final answer reads as though
        something went wrong, and the nudge heuristic fires on ordinary
        phrasing like "I'll post it".
        """
        rows = build_transcript([
            text("Connect Slack and I'll post it."),
            AgentEvent(type="tool_call_healed", message="",
                       payload={"nudge": True}),
            done(),
        ])
        assert [type(r).__name__ for r in rows] == ["ProseRow"]


class TestGroupState:
    def test_error_is_flagged(self) -> None:
        records = [call("bash", "a", command="ls")]
        records[0].status = "error"
        assert build_group(records).has_error

    def test_denial_counts_as_an_error(self) -> None:
        records = [call("bash", "a", command="rm -rf /")]
        records[0].status = "denied"
        assert build_group(records).has_error

    def test_key_is_the_first_call_id(self) -> None:
        group = build_group(
            [call("read_file", "first", path="a"), call("read_file", "second", path="b")]
        )
        assert group.key == "first"

    def test_duration_sums_across_the_run(self) -> None:
        records = [call("read_file", "a", path="x"), call("read_file", "b", path="y")]
        records[0].duration_ms, records[1].duration_ms = 10.0, 32.5
        assert build_group(records).duration_ms == 42.5

    def test_all_read_only_run_is_marked(self) -> None:
        assert build_group(
            [call("read_file", "a", path="x"), call("web_search", "b", query="y")]
        ).read_only
        assert not build_group(
            [call("read_file", "a", path="x"), call("bash", "b", command="ls")]
        ).read_only


class TestTranscript:
    def test_prose_breaks_the_run(self) -> None:
        rows = build_transcript(
            [
                called("read_file", "1", path="a.py"),
                completed("read_file", "1"),
                text("Here is what I found."),
                called("edit_file", "2", path="a.py"),
                completed("edit_file", "2"),
                done(),
            ]
        )
        kinds = [type(r).__name__ for r in rows]
        assert kinds == ["WorkRow", "ProseRow", "WorkRow"]
        assert rows[0].group.label == "Read a.py"
        assert rows[1].text == "Here is what I found."
        assert rows[2].group.label == "Edited a.py"

    def test_uninterrupted_calls_stay_one_row(self) -> None:
        events = []
        for i in range(4):
            events += [called("read_file", str(i), path=f"{i}.py"), completed("read_file", str(i))]
        events.append(done())
        rows = build_transcript(events)
        assert [type(r).__name__ for r in rows] == ["WorkRow"]
        assert rows[0].group.label == "Read 4 files"

    def test_text_deltas_are_joined(self) -> None:
        rows = build_transcript([text("Hello "), text("there"), done()])
        assert rows == [ProseRow("Hello there")]

    def test_final_output_used_when_the_adapter_never_streamed(self) -> None:
        rows = build_transcript([done("The answer.")])
        assert rows == [ProseRow("The answer.")]

    def test_final_output_not_duplicated_when_it_did_stream(self) -> None:
        rows = build_transcript([text("The answer."), done("The answer.")])
        assert rows == [ProseRow("The answer.")]

    def test_failure_is_carried_into_the_row(self) -> None:
        rows = build_transcript(
            [called("bash", "1", command="ls"), failed("bash", "1", "no such dir"), done()]
        )
        assert rows[0].group.has_error
        assert rows[0].group.calls[0].error == "no such dir"

    def test_denial_without_a_prior_call_event_is_still_shown(self) -> None:
        # The permission gate can block before `tool_called` is emitted.
        rows = build_transcript(
            [
                AgentEvent(
                    type="tool_denied",
                    message="Tool blocked: bash",
                    payload={"tool": "bash", "reason": "on the deny list"},
                ),
                done(),
            ]
        )
        assert isinstance(rows[0], WorkRow)
        assert rows[0].group.calls[0].status == "denied"
        assert rows[0].group.has_error

    def test_notices_are_their_own_rows(self) -> None:
        rows = build_transcript(
            [
                AgentEvent(
                    type="context_compacted", message="", payload={"before": 40, "after": 8}
                ),
                done(),
            ]
        )
        assert isinstance(rows[0], NoticeRow)
        assert rows[0].kind == "context_compacted"

    def test_usage_is_captured(self) -> None:
        accumulator = WorkRunAccumulator()
        for event in [done("hi", total_tokens=18_240, prompt_tokens=17_000)]:
            accumulator.feed(event)
        assert accumulator.usage["total_tokens"] == 18_240

    def test_accepts_an_agent_result_shape(self) -> None:
        class FakeResult:
            events = [text("hi"), done()]

        assert build_transcript(FakeResult()) == [ProseRow("hi")]

    def test_empty_stream_yields_nothing(self) -> None:
        assert build_transcript([]) == []


class TestLiveAccumulator:
    def test_pending_group_is_present_tense(self) -> None:
        accumulator = WorkRunAccumulator()
        accumulator.feed(called("read_file", "1", path="app.py"))
        assert accumulator.pending.label == "Reading app.py"
        assert accumulator.pending.running

    def test_pending_clears_once_the_run_closes(self) -> None:
        accumulator = WorkRunAccumulator()
        accumulator.feed(called("read_file", "1", path="app.py"))
        accumulator.feed(completed("read_file", "1"))
        accumulator.feed(text("Done."))
        assert accumulator.pending is None

    def test_feed_returns_only_newly_settled_rows(self) -> None:
        accumulator = WorkRunAccumulator()
        assert accumulator.feed(called("read_file", "1", path="a")) == []
        assert accumulator.feed(completed("read_file", "1")) == []
        settled = accumulator.feed(text("Found it."))
        assert len(settled) == 1 and isinstance(settled[0], WorkRow)

    def test_finish_flushes_the_tail(self) -> None:
        accumulator = WorkRunAccumulator()
        accumulator.feed(called("read_file", "1", path="a"))
        accumulator.feed(completed("read_file", "1"))
        assert len(accumulator.finish()) == 1

    @pytest.mark.parametrize("bad", [None, "", 0, [], {}])
    def test_malformed_duration_does_not_raise(self, bad) -> None:
        accumulator = WorkRunAccumulator()
        accumulator.feed(called("read_file", "1", path="a"))
        accumulator.feed(
            AgentEvent(
                type="tool_completed",
                message="",
                payload={"tool": "read_file", "call_id": "1", "duration_ms": bad},
            )
        )
        assert accumulator.finish()[0].group.duration_ms == 0.0


def queued(tool: str, action_id: int = 1, tag: str = "comms.send", auto: bool = False):
    return AgentEvent(
        type="action_queued",
        message="",
        payload={
            "tool": tool,
            "action_id": action_id,
            "title": f"Used {tool}",
            "tag": tag,
            "auto_approved": auto,
        },
    )


class TestApprovalRows:
    def test_a_queued_action_is_its_own_row(self) -> None:
        from shipit_agent.narrate.grouping import ApprovalRow

        rows = build_transcript([queued("slack"), done()])
        assert isinstance(rows[0], ApprovalRow)
        assert rows[0].tag == "comms.send"
        assert rows[0].action_id == 1

    def test_prose_announcing_the_action_lands_first(self) -> None:
        # A deferred call never emits `tool_called`, so the approval row is the
        # only thing that can close the sentence introducing it.
        rows = build_transcript(
            [text("I'll send the venue notice."), queued("slack"), done()]
        )
        assert [type(r).__name__ for r in rows] == ["ProseRow", "ApprovalRow"]
        assert rows[0].text == "I'll send the venue notice."

    def test_an_approval_closes_the_preceding_work_run(self) -> None:
        rows = build_transcript(
            [
                called("read_file", "1", path="guests.csv"),
                completed("read_file", "1"),
                queued("slack"),
                done(),
            ]
        )
        assert [type(r).__name__ for r in rows] == ["WorkRow", "ApprovalRow"]

    def test_prose_on_both_sides_stays_separate(self) -> None:
        rows = build_transcript(
            [text("Before."), queued("slack"), text("After."), done()]
        )
        assert [getattr(r, "text", None) for r in rows] == ["Before.", None, "After."]

    def test_auto_approved_actions_are_marked(self) -> None:
        rows = build_transcript([queued("slack", auto=True), done()])
        assert rows[0].auto_approved

    def test_missing_payload_fields_do_not_raise(self) -> None:
        bare = AgentEvent(type="action_queued", message="", payload={})
        rows = build_transcript([bare, done()])
        assert rows[0].action_id == 0 and rows[0].tool == "?"


def denied(tool: str, call_id: str = "1", reason: str = "not permitted"):
    return AgentEvent(type="tool_denied", message="", payload={
        "tool": tool, "call_id": call_id, "reason": reason})


class TestDenialOrdering:
    def test_prose_announcing_a_denied_call_lands_first(self) -> None:
        # A denied call may never emit `tool_called` — the gate can fire
        # first — so the denial is the only thing that can close the sentence.
        rows = build_transcript(
            [text("Sharing it with the team."), denied("slack"), done()]
        )
        assert [type(r).__name__ for r in rows] == ["ProseRow", "WorkRow"]
        assert rows[0].text == "Sharing it with the team."
        assert rows[1].group.has_error

    def test_a_notice_between_call_and_completion_does_not_duplicate_the_row(
        self,
    ) -> None:
        """Regression: a notice mid-call flushed the run, and the completion
        then synthesized a second phantom row for the same call."""
        rows = build_transcript(
            [
                called("read_file", "1", path="a.py"),
                completed("read_file", "1"),
                AgentEvent(type="lockdown_engaged", message="",
                           payload={"reason": "customer PII"}),
                done(),
            ]
        )
        work = [r for r in rows if isinstance(r, WorkRow)]
        assert len(work) == 1, "the call was rendered twice"

    def test_lockdown_renders_as_a_notice(self) -> None:
        rows = build_transcript([
            AgentEvent(type="lockdown_engaged", message="",
                       payload={"reason": "the customer list"}),
            done(),
        ])
        assert isinstance(rows[0], NoticeRow)
        assert "Lockdown" in rows[0].text
        assert "the customer list" in rows[0].text
