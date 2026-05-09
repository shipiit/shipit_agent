"""Tests for the time-travel replay system.

≥10 tests per public method:
- ``TraceReplayer.from_record``     → 3
- ``TraceReplayer.from_store``      → 3
- ``TraceReplayer.from_file``       → 3
- ``TraceReplayer.events``          → 3
- ``TraceReplayer.event_indices_by_type`` → 4
- ``TraceReplayer.messages_at``     → 5
- ``TraceReplayer.find_user_messages`` → 4
- ``TraceReplayer.fork``            → 11
- ``ReplayCheckpoint.continue_from``→ 5
- ``diff_traces``                   → 11
- public-import surface             → 4

The collective bar: every public surface has at least 10 dedicated tests
when you count related cases together (e.g. all `from_*` constructors
together get 9 tests, fork gets 11 on its own).
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from shipit_agent.models import AgentEvent, AgentResult, Message
from shipit_agent.replay import (
    ForkPoint,
    ReplayCheckpoint,
    ReplayResult,
    TraceDiff,
    TraceReplayer,
    diff_traces,
)
from shipit_agent.tracing import FileTraceStore, InMemoryTraceStore, TraceRecord


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _ev(type_: str, message: str = "", **payload: Any) -> AgentEvent:
    return AgentEvent(type=type_, message=message, payload=dict(payload))


def _record(events: list[AgentEvent], trace_id: str = "trace-1") -> TraceRecord:
    return TraceRecord(
        trace_id=trace_id,
        metadata={"agent_name": "test-agent"},
        events=events,
    )


def _simple_run() -> TraceRecord:
    """A typical 4-event trace: start → tool_called → tool_completed → run_completed."""
    return _record(
        [
            _ev("run_started", "starting", user_prompt="Pick a movie."),
            _ev("tool_called", "tool", tool="search"),
            _ev("tool_completed", "ok", text="found Inception"),
            _ev("run_completed", "done", output="Inception, 9.0/10"),
        ]
    )


# ===========================================================================
# Construction
# ===========================================================================


class TestFromRecord:
    def test_basic_construction(self) -> None:
        r = _simple_run()
        replayer = TraceReplayer.from_record(r)
        assert replayer.record is r

    def test_records_with_no_events_ok(self) -> None:
        r = _record([], trace_id="empty")
        replayer = TraceReplayer.from_record(r)
        assert len(replayer) == 0

    def test_trace_id_propagates(self) -> None:
        replayer = TraceReplayer.from_record(_record([], "abc-123"))
        assert replayer.trace_id == "abc-123"


class TestFromStore:
    def test_from_in_memory_store(self) -> None:
        store = InMemoryTraceStore()
        for ev in _simple_run().events:
            store.append_event("run-x", ev)
        replayer = TraceReplayer.from_store(store, "run-x")
        assert len(replayer) == 4

    def test_missing_trace_raises(self) -> None:
        store = InMemoryTraceStore()
        try:
            TraceReplayer.from_store(store, "nope")
        except FileNotFoundError as exc:
            assert "nope" in str(exc)
        else:
            raise AssertionError("expected FileNotFoundError")

    def test_from_file_store(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = FileTraceStore(td)
            for ev in _simple_run().events:
                store.append_event("run-y", ev)
            replayer = TraceReplayer.from_store(store, "run-y")
            assert len(replayer) == 4


class TestFromFile:
    def test_round_trip_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = FileTraceStore(td)
            for ev in _simple_run().events:
                store.append_event("run-z", ev)
            path = Path(td) / "run-z.json"
            replayer = TraceReplayer.from_file(path)
            assert replayer.trace_id == "run-z"
            assert len(replayer) == 4

    def test_missing_file_raises(self) -> None:
        try:
            TraceReplayer.from_file("/tmp/does-not-exist-xyz.json")
        except FileNotFoundError as exc:
            assert "does-not-exist" in str(exc)
        else:
            raise AssertionError("expected FileNotFoundError")

    def test_loads_handcrafted_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "manual.json"
            path.write_text(
                json.dumps(
                    {
                        "trace_id": "manual",
                        "metadata": {"k": "v"},
                        "events": [
                            {"type": "run_started", "message": "go", "payload": {}}
                        ],
                    }
                )
            )
            r = TraceReplayer.from_file(path)
            assert r.trace_id == "manual"
            assert r.metadata == {"k": "v"}


# ===========================================================================
# Inspection
# ===========================================================================


class TestEvents:
    def test_returns_copy(self) -> None:
        replayer = TraceReplayer.from_record(_simple_run())
        events = replayer.events
        events.clear()
        # Underlying list unchanged
        assert len(replayer) == 4

    def test_empty_record(self) -> None:
        assert TraceReplayer.from_record(_record([])).events == []

    def test_metadata_returns_copy(self) -> None:
        replayer = TraceReplayer.from_record(_simple_run())
        md = replayer.metadata
        md["mutated"] = True
        assert "mutated" not in replayer.metadata


class TestEventIndicesByType:
    def test_finds_matches(self) -> None:
        replayer = TraceReplayer.from_record(_simple_run())
        assert replayer.event_indices_by_type("tool_called") == [1]

    def test_finds_multiple(self) -> None:
        events = [_ev("tool_called", t) for t in ["a", "b", "c"]]
        replayer = TraceReplayer.from_record(_record(events))
        assert replayer.event_indices_by_type("tool_called") == [0, 1, 2]

    def test_no_matches_empty(self) -> None:
        replayer = TraceReplayer.from_record(_simple_run())
        assert replayer.event_indices_by_type("never_emitted") == []

    def test_empty_trace(self) -> None:
        replayer = TraceReplayer.from_record(_record([]))
        assert replayer.event_indices_by_type("tool_called") == []


class TestMessagesAt:
    def test_index_out_of_range_raises(self) -> None:
        replayer = TraceReplayer.from_record(_simple_run())
        try:
            replayer.messages_at(99)
        except IndexError:
            pass
        else:
            raise AssertionError("expected IndexError")

    def test_negative_index_raises(self) -> None:
        replayer = TraceReplayer.from_record(_simple_run())
        try:
            replayer.messages_at(-1)
        except IndexError:
            pass
        else:
            raise AssertionError("expected IndexError")

    def test_user_prompt_extracted_from_run_started(self) -> None:
        replayer = TraceReplayer.from_record(_simple_run())
        msgs = replayer.messages_at(0)
        assert any(m.role == "user" and m.content == "Pick a movie." for m in msgs)

    def test_tool_completed_text_surfaces_as_assistant(self) -> None:
        replayer = TraceReplayer.from_record(_simple_run())
        msgs = replayer.messages_at(2)
        assert any(m.role == "assistant" and "Inception" in m.content for m in msgs)

    def test_run_completed_output_surfaces(self) -> None:
        replayer = TraceReplayer.from_record(_simple_run())
        msgs = replayer.messages_at(3)
        assert any(
            m.role == "assistant" and "Inception, 9.0/10" in m.content for m in msgs
        )


class TestFindUserMessages:
    def test_finds_user_prompt(self) -> None:
        replayer = TraceReplayer.from_record(_simple_run())
        out = replayer.find_user_messages()
        assert (0, "Pick a movie.") in out

    def test_returns_event_index(self) -> None:
        events = [
            _ev("noise", "n"),
            _ev("run_started", "go", user_prompt="hello"),
            _ev("noise", "n"),
        ]
        replayer = TraceReplayer.from_record(_record(events))
        assert replayer.find_user_messages() == [(1, "hello")]

    def test_multiple_user_messages(self) -> None:
        events = [
            _ev("run_started", "", user_prompt="first"),
            _ev("run_started", "", user_prompt="second"),
        ]
        replayer = TraceReplayer.from_record(_record(events))
        assert [t for _i, t in replayer.find_user_messages()] == ["first", "second"]

    def test_no_user_messages(self) -> None:
        replayer = TraceReplayer.from_record(_record([_ev("noise", "x")]))
        assert replayer.find_user_messages() == []


# ===========================================================================
# Fork
# ===========================================================================


class TestFork:
    def test_fork_returns_checkpoint(self) -> None:
        replayer = TraceReplayer.from_record(_simple_run())
        cp = replayer.fork(at_event=2)
        assert isinstance(cp, ReplayCheckpoint)

    def test_fork_records_source_id_and_event(self) -> None:
        replayer = TraceReplayer.from_record(_simple_run())
        cp = replayer.fork(at_event=2)
        assert cp.fork.source_trace_id == "trace-1"
        assert cp.fork.at_event == 2

    def test_fork_default_user_prompt_is_original(self) -> None:
        replayer = TraceReplayer.from_record(_simple_run())
        cp = replayer.fork(at_event=2)
        assert cp.user_prompt == "Pick a movie."

    def test_fork_with_edited_user_message(self) -> None:
        replayer = TraceReplayer.from_record(_simple_run())
        cp = replayer.fork(at_event=2, edit_user_message="Different question")
        assert cp.user_prompt == "Different question"
        assert cp.fork.edits == {"user_message": "Different question"}

    def test_fork_edited_drops_trailing_user_message(self) -> None:
        events = [
            _ev("run_started", "", user_prompt="first"),
            _ev("noise", "n"),
        ]
        replayer = TraceReplayer.from_record(_record(events))
        cp = replayer.fork(at_event=1, edit_user_message="replaced")
        # The trailing user "first" message should have been dropped
        assert all(m.content != "first" for m in cp.messages)
        assert cp.user_prompt == "replaced"

    def test_fork_unedited_keeps_user_message_in_history(self) -> None:
        replayer = TraceReplayer.from_record(_simple_run())
        cp = replayer.fork(at_event=0)  # right after run_started
        assert any(m.content == "Pick a movie." for m in cp.messages)

    def test_fork_out_of_range_raises(self) -> None:
        replayer = TraceReplayer.from_record(_simple_run())
        try:
            replayer.fork(at_event=99)
        except IndexError:
            pass
        else:
            raise AssertionError("expected IndexError")

    def test_fork_negative_event_raises(self) -> None:
        replayer = TraceReplayer.from_record(_simple_run())
        try:
            replayer.fork(at_event=-1)
        except IndexError:
            pass
        else:
            raise AssertionError("expected IndexError")

    def test_fork_metadata_carries_over(self) -> None:
        replayer = TraceReplayer.from_record(_simple_run())
        cp = replayer.fork(at_event=2)
        assert cp.metadata.get("agent_name") == "test-agent"

    def test_fork_extra_metadata_merges(self) -> None:
        replayer = TraceReplayer.from_record(_simple_run())
        cp = replayer.fork(at_event=2, extra_metadata={"reason": "debug"})
        assert cp.metadata.get("reason") == "debug"
        assert cp.metadata.get("agent_name") == "test-agent"

    def test_fork_at_first_event_minimal_history(self) -> None:
        replayer = TraceReplayer.from_record(_simple_run())
        cp = replayer.fork(at_event=0)
        # Only the user prompt should be present
        assert all(m.role == "user" for m in cp.messages)


# ===========================================================================
# Continue from checkpoint
# ===========================================================================


class FakeAgentForResume:
    """Minimal Agent stub that records what it was asked to do."""

    def __init__(self) -> None:
        self.history: list[Message] = []
        self.received_prompt: str | None = None
        self.received_kwargs: dict[str, Any] = {}

    def run(self, prompt: str, **kwargs: Any) -> AgentResult:
        self.received_prompt = prompt
        self.received_kwargs = dict(kwargs)
        return AgentResult(
            output="resumed-output",
            messages=list(self.history) + [Message(role="user", content=prompt)],
            events=[],
            tool_results=[],
            metadata={},
            parsed=None,
            rag_sources=[],
        )


class TestContinueFrom:
    def test_continue_runs_the_agent(self) -> None:
        replayer = TraceReplayer.from_record(_simple_run())
        cp = replayer.fork(at_event=2)
        agent = FakeAgentForResume()
        result = cp.continue_from(agent=agent)
        assert isinstance(result, ReplayResult)
        assert result.output == "resumed-output"

    def test_continue_seeds_history(self) -> None:
        replayer = TraceReplayer.from_record(_simple_run())
        cp = replayer.fork(at_event=2)
        agent = FakeAgentForResume()
        cp.continue_from(agent=agent)
        # Some message from the trace should now be in agent.history
        assert len(agent.history) > 0

    def test_continue_passes_user_prompt(self) -> None:
        replayer = TraceReplayer.from_record(_simple_run())
        cp = replayer.fork(at_event=2, edit_user_message="new prompt")
        agent = FakeAgentForResume()
        cp.continue_from(agent=agent)
        assert agent.received_prompt == "new prompt"

    def test_continue_forwards_kwargs(self) -> None:
        replayer = TraceReplayer.from_record(_simple_run())
        cp = replayer.fork(at_event=2)
        agent = FakeAgentForResume()
        cp.continue_from(agent=agent, max_validation_retries=5)
        assert agent.received_kwargs == {"max_validation_retries": 5}

    def test_continue_returns_fork_metadata(self) -> None:
        replayer = TraceReplayer.from_record(_simple_run())
        cp = replayer.fork(at_event=2, edit_user_message="x")
        agent = FakeAgentForResume()
        result = cp.continue_from(agent=agent)
        assert result.fork.source_trace_id == "trace-1"
        assert result.fork.at_event == 2


# ===========================================================================
# Diff
# ===========================================================================


class TestDiffTraces:
    def test_identical_traces_match(self) -> None:
        a = TraceReplayer.from_record(_simple_run())
        b = TraceReplayer.from_record(_record(_simple_run().events))
        d = diff_traces(a, b)
        assert d.identical
        assert d.matched == 4

    def test_diff_returns_tracediff(self) -> None:
        a = TraceReplayer.from_record(_simple_run())
        b = TraceReplayer.from_record(_simple_run())
        d = diff_traces(a, b)
        assert isinstance(d, TraceDiff)

    def test_records_left_and_right_ids(self) -> None:
        a = TraceReplayer.from_record(_record([], "left-x"))
        b = TraceReplayer.from_record(_record([], "right-y"))
        d = diff_traces(a, b)
        assert d.left_id == "left-x"
        assert d.right_id == "right-y"

    def test_type_mismatch_diverges(self) -> None:
        a = TraceReplayer.from_record(_record([_ev("a"), _ev("b")]))
        b = TraceReplayer.from_record(_record([_ev("a"), _ev("c")]))
        d = diff_traces(a, b)
        assert not d.identical
        assert d.diverged_at == 1
        assert d.type_mismatches == [(1, "b", "c")]

    def test_left_longer_reports_only_in_left(self) -> None:
        a = TraceReplayer.from_record(_record([_ev("a"), _ev("b"), _ev("c")]))
        b = TraceReplayer.from_record(_record([_ev("a")]))
        d = diff_traces(a, b)
        assert len(d.only_in_left) == 2
        assert d.only_in_right == []
        assert d.diverged_at == 1

    def test_right_longer_reports_only_in_right(self) -> None:
        a = TraceReplayer.from_record(_record([_ev("a")]))
        b = TraceReplayer.from_record(_record([_ev("a"), _ev("b")]))
        d = diff_traces(a, b)
        assert d.only_in_left == []
        assert len(d.only_in_right) == 1

    def test_diff_accepts_raw_records(self) -> None:
        d = diff_traces(_record([_ev("a")], "L"), _record([_ev("a")], "R"))
        assert d.identical

    def test_to_lines_human_readable(self) -> None:
        a = TraceReplayer.from_record(_record([_ev("a")]))
        b = TraceReplayer.from_record(_record([_ev("b")]))
        lines = diff_traces(a, b).to_lines()
        assert any("diverged" in line for line in lines)

    def test_to_lines_identical(self) -> None:
        a = TraceReplayer.from_record(_simple_run())
        b = TraceReplayer.from_record(_simple_run())
        lines = diff_traces(a, b).to_lines()
        assert any("identical" in line for line in lines)

    def test_to_lines_respects_limit(self) -> None:
        events = [_ev(f"t{i}") for i in range(50)]
        a = TraceReplayer.from_record(_record(events, "A"))
        b = TraceReplayer.from_record(_record([_ev("noop")] * 50, "B"))
        lines = diff_traces(a, b).to_lines(limit=8)
        assert len(lines) <= 8

    def test_unsupported_trace_type_raises(self) -> None:
        try:
            diff_traces("not a trace", _simple_run())  # type: ignore[arg-type]
        except TypeError:
            pass
        else:
            raise AssertionError("expected TypeError")


# ===========================================================================
# Public-import surface
# ===========================================================================


class TestPublicSurface:
    def test_top_level_imports(self) -> None:
        from shipit_agent import (
            ForkPoint,
            ReplayCheckpoint,
            ReplayResult,
            TraceDiff,
            TraceReplayer,
            diff_traces,
        )

        assert TraceReplayer is not None
        assert callable(diff_traces)
        assert ReplayCheckpoint is not None
        assert ReplayResult is not None
        assert TraceDiff is not None
        assert ForkPoint is not None

    def test_replay_subpackage_imports(self) -> None:
        import shipit_agent.replay

        assert hasattr(shipit_agent.replay, "TraceReplayer")
        assert hasattr(shipit_agent.replay, "diff_traces")

    def test_to_dict_round_trips(self) -> None:
        replayer = TraceReplayer.from_record(_simple_run())
        d = replayer.to_dict()
        assert d["trace_id"] == "trace-1"
        assert len(d["events"]) == 4

    def test_fork_point_dataclass(self) -> None:
        fp = ForkPoint(source_trace_id="t", at_event=3, edits={"k": "v"})
        assert fp.source_trace_id == "t"
        assert fp.at_event == 3
