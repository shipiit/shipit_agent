"""The UI timeline — runtime events translated into what a frontend draws."""

from __future__ import annotations

import json

from shipit_agent.models import AgentEvent
from shipit_agent.narrate.timeline import (
    TimelineBuilder,
    render_markdown,
    stream_timeline,
    timeline,
)


def event(kind: str, **payload) -> AgentEvent:
    return AgentEvent(type=kind, message="", payload=payload)


RUN = [
    event("run_started", prompt="Process the latest RSVP"),
    event("tool_called", call_id="1", tool="read_file", arguments={"path": "in.eml"}),
    event(
        "tool_completed",
        call_id="1",
        tool="read_file",
        output='{"from": "jordan@acme.com"}',
        duration_ms=420,
    ),
    event("text_delta", chunk="No existing record. "),
    event("text_delta", chunk="Creating one."),
    event("tool_called", call_id="2", tool="write_file", arguments={"path": "r.csv"}),
    event(
        "tool_completed",
        call_id="2",
        tool="write_file",
        output="written",
        duration_ms=270,
    ),
    event("run_completed", output="RSVP recorded.", usage={"total_tokens": 1180}),
]


def kinds(steps) -> list[str]:
    return [step["type"] for step in steps]


class TestShape:
    def test_the_documented_flow(self) -> None:
        assert kinds(timeline(RUN)) == [
            "run_started",
            "tool_group_started",
            "tool_call_started",
            "tool_call_completed",
            "tool_group_completed",
            "agent_decision",
            "tool_group_started",
            "tool_call_started",
            "tool_call_completed",
            "tool_group_completed",
            "final_response",
        ]

    def test_prose_between_calls_becomes_a_decision(self) -> None:
        decision = next(s for s in timeline(RUN) if s["type"] == "agent_decision")
        assert decision["content"] == "No existing record. Creating one."
        assert decision["next_action"] == "call_tool"

    def test_calls_carry_their_group(self) -> None:
        steps = timeline(RUN)
        started = [s for s in steps if s["type"] == "tool_call_started"]
        assert started[0]["group_id"] != started[1]["group_id"]
        completed = [s for s in steps if s["type"] == "tool_call_completed"]
        assert completed[0]["group_id"] == started[0]["group_id"]

    def test_ids_survive_the_translation(self) -> None:
        started = next(s for s in timeline(RUN) if s["type"] == "tool_call_started")
        assert started["tool_call_id"] == "1"

    def test_the_final_response_counts_the_work(self) -> None:
        final = timeline(RUN)[-1]
        assert final["content"] == "RSVP recorded."
        assert final["tool_calls"] == 2
        assert final["usage"]["total_tokens"] == 1180

    def test_declared_groups_keep_their_runtime_ids_and_tools(self) -> None:
        steps = timeline(
            [
                event(
                    "tool_group_started",
                    group_id="tool_group_7",
                    tools=[
                        {"name": "read_file", "call_id": "1"},
                        {"name": "grep_files", "call_id": "2"},
                    ],
                ),
                event(
                    "tool_called",
                    call_id="1",
                    tool="read_file",
                    arguments={"path": "a.py"},
                    group_id="tool_group_7",
                ),
                event(
                    "tool_completed",
                    call_id="1",
                    tool="read_file",
                    output="x",
                    group_id="tool_group_7",
                ),
                event(
                    "tool_called",
                    call_id="2",
                    tool="grep_files",
                    arguments={"pattern": "TODO"},
                    group_id="tool_group_7",
                ),
                event(
                    "tool_completed",
                    call_id="2",
                    tool="grep_files",
                    output="1 match",
                    group_id="tool_group_7",
                ),
                event("tool_group_completed", group_id="tool_group_7"),
                event("run_completed", output="done", usage={}),
            ]
        )
        started = next(s for s in steps if s["type"] == "tool_group_started")
        assert started["group_id"] == "tool_group_7"
        assert [tool["tool"] for tool in started["tools"]] == [
            "read_file",
            "grep_files",
        ]
        completed = next(s for s in steps if s["type"] == "tool_group_completed")
        assert completed["group_id"] == "tool_group_7"
        assert completed["tool_calls"] == 2
        assert [tool["tool"] for tool in completed["tools"]] == [
            "read_file",
            "grep_files",
        ]

    def test_declared_groups_do_not_split_on_mid_group_narration(self) -> None:
        steps = timeline(
            [
                event(
                    "tool_group_started",
                    group_id="g1",
                    tools=[
                        {"name": "read_file", "call_id": "1"},
                        {"name": "read_file", "call_id": "2"},
                    ],
                ),
                event(
                    "tool_called",
                    call_id="1",
                    tool="read_file",
                    arguments={"path": "a.py"},
                    group_id="g1",
                ),
                event(
                    "tool_completed",
                    call_id="1",
                    tool="read_file",
                    output="x",
                    group_id="g1",
                ),
                event("text_delta", chunk="Still working."),
                event(
                    "tool_called",
                    call_id="2",
                    tool="read_file",
                    arguments={"path": "b.py"},
                    group_id="g1",
                ),
                event(
                    "tool_completed",
                    call_id="2",
                    tool="read_file",
                    output="y",
                    group_id="g1",
                ),
                event("tool_group_completed", group_id="g1"),
                event("run_completed", output="done", usage={}),
            ]
        )
        assert kinds(steps).count("tool_group_started") == 1
        assert kinds(steps).count("tool_group_completed") == 1


class TestFidelity:
    def test_every_step_is_json(self) -> None:
        # It goes on a socket; a dataclass or a datetime would break that.
        json.dumps(timeline(RUN))

    def test_json_output_is_parsed_so_a_ui_can_table_it(self) -> None:
        completed = next(s for s in timeline(RUN) if s["type"] == "tool_call_completed")
        assert completed["output"] == {"from": "jordan@acme.com"}

    def test_plain_text_output_stays_text(self) -> None:
        completed = [s for s in timeline(RUN) if s["type"] == "tool_call_completed"]
        assert completed[1]["output"] == "written"

    def test_unparseable_json_falls_back_to_text(self) -> None:
        steps = timeline(
            [
                event("tool_called", call_id="1", tool="read_file", arguments={}),
                event(
                    "tool_completed", call_id="1", tool="read_file", output="{not json"
                ),
                event("run_completed", output="", usage={}),
            ]
        )
        completed = next(s for s in steps if s["type"] == "tool_call_completed")
        assert completed["output"] == "{not json"


class TestOutcomes:
    def test_a_failure_carries_the_error_not_an_output(self) -> None:
        steps = timeline(
            [
                event("tool_called", call_id="1", tool="bash", arguments={}),
                event("tool_failed", call_id="1", tool="bash", error="boom"),
                event("run_completed", output="", usage={}),
            ]
        )
        failed = next(s for s in steps if s["type"] == "tool_call_completed")
        assert failed["status"] == "failed" and failed["error"] == "boom"
        assert "output" not in failed

    def test_a_denial_is_its_own_status(self) -> None:
        steps = timeline(
            [
                event("tool_denied", call_id="1", tool="bash", reason="deny list"),
                event("run_completed", output="", usage={}),
            ]
        )
        denied = next(s for s in steps if s["type"] == "tool_call_completed")
        assert denied["status"] == "denied" and "deny list" in denied["error"]

    def test_an_approval_interrupts_and_asks(self) -> None:
        steps = timeline(
            [
                event("text_delta", chunk="I'll send the notice."),
                event(
                    "action_queued",
                    action_id=3,
                    tool="slack",
                    title="Used Slack #events",
                    tag="comms.send",
                ),
                event("run_completed", output="", usage={}),
            ]
        )
        decision = next(s for s in steps if s["type"] == "agent_decision")
        assert decision["next_action"] == "ask_user"
        approval = next(s for s in steps if s["type"] == "approval_required")
        assert approval["title"] == "Used Slack #events"
        assert approval["tag"] == "comms.send"

    def test_sub_agent_work_is_attributed(self) -> None:
        steps = timeline(
            [
                event(
                    "sub_agent_event",
                    agent="researcher",
                    task="find the owner",
                    inner_type="tool_called",
                    inner={"tool": "read_file", "arguments": {"path": "o.md"}},
                ),
                event("run_completed", output="", usage={}),
            ]
        )
        sub = next(s for s in steps if s["type"] == "sub_agent_tool_call")
        assert sub["agent"] == "researcher" and sub["tool_name"] == "read_file"

    def test_a_notice_is_surfaced(self) -> None:
        steps = timeline(
            [
                event("lockdown_engaged", reason="read a private file"),
                event("run_completed", output="", usage={}),
            ]
        )
        assert any(s["type"] == "notice" for s in steps)

    def test_a_reasoning_summary_is_used_when_the_runtime_emits_one(self) -> None:
        steps = timeline(
            [
                event("planning_completed", summary="Read, extract, save."),
                event("run_completed", output="ok", usage={}),
            ]
        )
        assert steps[0]["type"] == "reasoning_summary"
        assert steps[0]["content"] == "Read, extract, save."


class TestLiveness:
    def test_steps_are_emitted_as_events_arrive(self) -> None:
        builder = TimelineBuilder()
        first = builder.feed(RUN[1])  # tool_called
        assert kinds(first) == ["tool_group_started", "tool_call_started"]

    def test_a_group_title_is_available_before_the_group_settles(self) -> None:
        builder = TimelineBuilder()
        started = builder.feed(RUN[1])[0]
        assert started["title"], "a UI must have something to draw immediately"

    def test_an_unfinished_run_is_still_closed_out(self) -> None:
        builder = TimelineBuilder()
        builder.feed(RUN[1])
        assert kinds(builder.finish()) == ["tool_group_completed"]

    def test_stream_timeline_drives_an_agent(self) -> None:
        class FakeAgent:
            def stream(self, prompt):
                yield from RUN

        steps = list(stream_timeline(FakeAgent(), "Process the latest RSVP"))
        assert kinds(steps)[0] == "run_started"
        assert kinds(steps)[-1] == "final_response"

    def test_a_crash_mid_run_still_closes_open_groups(self) -> None:
        class Exploding:
            def stream(self, prompt):
                yield RUN[1]
                raise RuntimeError("provider died")

        steps = []
        try:
            for step in stream_timeline(Exploding(), "go"):
                steps.append(step)
        except RuntimeError:
            pass
        assert "tool_group_completed" in kinds(steps)


class TestMarkdown:
    def test_the_report_has_the_documented_sections(self) -> None:
        report = render_markdown(RUN)
        assert report.startswith("## Agent Run")
        assert "**Goal:** Process the latest RSVP" in report
        assert "### 1. Tool calls" in report
        assert "##### `read_file`" in report
        assert "**Status:** Completed" in report
        assert "**Duration:** 420 ms" in report
        assert "### 2. Agent decision" in report
        assert "Final response" in report
        assert "**Tool calls:** 2" in report

    def test_durations_are_totalled(self) -> None:
        assert "0.69 seconds" in render_markdown(RUN)

    def test_output_is_clipped(self) -> None:
        report = render_markdown(
            [
                event("tool_called", call_id="1", tool="read_file", arguments={}),
                event(
                    "tool_completed", call_id="1", tool="read_file", output="z" * 5000
                ),
                event("run_completed", output="ok", usage={}),
            ],
            output_limit=200,
        )
        assert "z" * 5000 not in report

    def test_an_empty_run_still_renders(self) -> None:
        assert render_markdown([]).startswith("## Agent Run")
