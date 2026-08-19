"""The run loop, tool contracts, tool-call pairing, and delegation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from shipit_agent.graph import AgentGraph, RunSpec, StopReason, run_to_result
from shipit_agent.models import (
    Message,
    ToolCall,
    ToolResult,
    new_tool_call_id,
    pair_calls_and_results,
)
from shipit_agent.subagents import READ_ONLY_TOOLS, SubagentSpec, SubagentTool
from shipit_agent.toolkit.contracts import (
    MatchError,
    ReadTracker,
    StaleReadError,
    UnreadFileError,
    apply_unique_edit,
    run_tool_safely,
    safe_error_text,
    truncate_output,
    value_shape,
)
from shipit_agent.usage import Purpose, UsageLedger


# --------------------------------------------------------------------------- #
# Doubles
# --------------------------------------------------------------------------- #


@dataclass
class Reply:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    reasoning_content: str | None = None


class ScriptedLLM:
    """Returns queued replies, recording what it was asked."""

    def __init__(self, *replies: Reply) -> None:
        self._replies = list(replies)
        self.calls: list[dict[str, Any]] = []

    def complete(self, **kwargs: Any) -> Reply:
        self.calls.append(kwargs)
        callback = kwargs.get("text_delta_callback")
        reply = self._replies.pop(0) if self._replies else Reply(content="done")
        if callback and reply.content:
            for word in reply.content.split(" "):
                callback(word + " ")
        return reply


class EchoTool:
    name = "echo"
    description = "Echoes its input."
    prompt_instructions = ""

    def __init__(self, streaming: bool = False, fail: bool = False) -> None:
        self.streaming = streaming
        self.fail = fail
        self.seen: list[dict[str, Any]] = []

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
            },
        }

    def run(self, context: Any = None, **kwargs: Any) -> Any:
        self.seen.append(kwargs)
        if self.fail:
            raise RuntimeError("tool exploded")
        text = str(kwargs.get("text", ""))
        if self.streaming:
            return [f"{text}-{i}" for i in range(3)]
        return text


@dataclass
class FakeSkill:
    id: str
    name: str
    description: str
    body: str = "guidance"
    tools: list[str] = field(default_factory=list)

    def prompt_text(self) -> str:
        return self.body


def spec(llm: Any, **kwargs: Any) -> RunSpec:
    kwargs.setdefault("model", "google.gemma-4-31b")
    return RunSpec(llm=llm, **kwargs)


# --------------------------------------------------------------------------- #
# Tool call identity and pairing
# --------------------------------------------------------------------------- #


def test_every_tool_call_gets_an_id():
    call = ToolCall(name="echo").ensure_id()
    assert call.id
    assert call.id != ToolCall(name="echo").ensure_id().id


def test_ids_are_readable_rather_than_bare_uuids():
    assert new_tool_call_id().startswith("call_")


def test_parallel_calls_to_one_tool_stay_distinguishable():
    calls = [ToolCall(name="echo", index=i).ensure_id() for i in range(2)]
    assert calls[0].id != calls[1].id


def test_pairing_passes_for_a_correct_exchange():
    call = ToolCall(name="echo").ensure_id()
    messages = [
        Message(role="assistant", content="", tool_calls=[call]),
        Message.from_tool_result(ToolResult("echo", "hi", tool_call_id=call.id)),
    ]
    ok, problems = pair_calls_and_results(messages)
    assert ok and problems == []


def test_pairing_names_an_unanswered_call():
    call = ToolCall(name="echo").ensure_id()
    ok, problems = pair_calls_and_results(
        [Message(role="assistant", content="", tool_calls=[call])]
    )
    assert not ok
    assert "unanswered" in problems[0]


def test_pairing_names_an_orphan_result():
    ok, problems = pair_calls_and_results(
        [Message.from_tool_result(ToolResult("echo", "hi", tool_call_id="ghost"))]
    )
    assert not ok
    assert "unknown call id" in problems[0]


def test_messages_round_trip_with_ids_intact():
    call = ToolCall(name="echo", arguments={"text": "x"}).ensure_id()
    original = Message(role="assistant", content="", tool_calls=[call])
    restored = Message.from_dict(original.to_dict())
    assert restored.tool_calls[0].id == call.id
    assert restored.tool_calls[0].arguments == {"text": "x"}


def test_legacy_metadata_shape_still_loads():
    """Adapters written against the old shape keep working for one release."""
    legacy = {
        "role": "assistant",
        "content": "",
        "metadata": {"tool_calls": [{"id": "c1", "name": "echo", "arguments": {}}]},
    }
    restored = Message.from_dict(legacy)
    assert restored.tool_calls[0].id == "c1"
    assert "tool_calls" not in restored.metadata


# --------------------------------------------------------------------------- #
# Tool contracts
# --------------------------------------------------------------------------- #


def test_editing_an_unread_file_is_refused():
    tracker = ReadTracker()
    with pytest.raises(UnreadFileError, match="has not been read"):
        tracker.check_writable("/tmp/a.py", "content")


def test_editing_a_file_that_changed_since_the_read_is_refused():
    tracker = ReadTracker()
    tracker.record_read("/tmp/a.py", "original")
    with pytest.raises(StaleReadError, match="changed on disk"):
        tracker.check_writable("/tmp/a.py", "modified")


def test_path_spelling_does_not_bypass_the_read_check(tmp_path):
    tracker = ReadTracker()
    target = tmp_path / "a.py"
    target.write_text("x", encoding="utf-8")
    tracker.record_read(str(target), "x")
    tracker.check_writable(f"{tmp_path}/./a.py", "x")  # must not raise


def test_unique_edit_replaces_exactly_one_occurrence():
    assert apply_unique_edit("a\nb\nc", "b", "B") == "a\nB\nc"


def test_zero_matches_reports_the_nearest_near_miss():
    with pytest.raises(MatchError) as excinfo:
        apply_unique_edit("def run(self):\n    pass\n", "def run(self) :", "x")
    assert "Closest text found" in str(excinfo.value)


def test_ambiguous_edit_refuses_rather_than_guessing():
    with pytest.raises(MatchError, match="matched 2 times"):
        apply_unique_edit("x = 1\nx = 1\n", "x = 1", "x = 2")


def test_empty_old_str_is_rejected():
    with pytest.raises(MatchError, match="empty"):
        apply_unique_edit("abc", "", "x")


def test_truncation_keeps_head_and_tail_and_says_so():
    text = "HEAD" + ("m" * 5000) + "TAIL"
    result, cut = truncate_output(text, limit=1000)
    assert cut
    assert result.startswith("HEAD") and result.endswith("TAIL")
    assert "characters omitted" in result
    assert len(result) < 1200


def test_short_output_is_never_touched():
    assert truncate_output("short", limit=1000) == ("short", False)


def test_truncation_marker_can_carry_a_recovery_hint():
    result, _ = truncate_output("x" * 5000, limit=800, recovery_hint="Use a filter.")
    assert "Use a filter." in result


def test_a_failing_tool_returns_a_result_not_an_exception():
    call = ToolCall(name="echo").ensure_id()

    def boom() -> str:
        raise RuntimeError("disk on fire")

    result = run_tool_safely(call, boom)
    assert result.is_error
    assert result.tool_call_id == call.id
    assert "disk on fire" in result.output


def test_argument_values_never_reach_a_log_shape():
    shape = value_shape({"token": "sk-secret-value", "n": 3, "items": [1, 2]})
    rendered = repr(shape)
    assert "sk-secret" not in rendered
    assert "str[15]" in rendered


def test_error_text_is_bounded():
    long_error = RuntimeError("x" * 5000)
    assert len(safe_error_text(long_error, tool_name="echo")) < 600


# --------------------------------------------------------------------------- #
# The run loop
# --------------------------------------------------------------------------- #


def test_a_plain_answer_ends_the_run_in_one_iteration():
    graph = AgentGraph(spec(ScriptedLLM(Reply(content="the answer"))))
    kinds = [e.type for e in graph.run("hi")]
    assert "final_answer" in kinds
    assert kinds[-1] == "run_completed"
    assert graph.stop_reason == StopReason.FINISHED


def test_text_streams_as_deltas_before_the_final_answer():
    graph = AgentGraph(spec(ScriptedLLM(Reply(content="one two three"))))
    events = list(graph.run("hi"))
    deltas = [e.payload["chunk"] for e in events if e.type == "text_delta"]
    assert "".join(deltas).strip() == "one two three"


def test_a_tool_call_runs_and_the_loop_continues():
    tool = EchoTool()
    llm = ScriptedLLM(
        Reply(tool_calls=[ToolCall(name="echo", arguments={"text": "hello"})]),
        Reply(content="finished"),
    )
    graph = AgentGraph(spec(llm, tools=[tool]))
    events = list(graph.run("go"))

    assert tool.seen == [{"text": "hello"}]
    assert [e.type for e in events].count("tool_completed") == 1
    assert graph.result().output == "finished"


def test_tool_output_streams_live_with_its_call_id():
    tool = EchoTool(streaming=True)
    llm = ScriptedLLM(
        Reply(tool_calls=[ToolCall(name="echo", arguments={"text": "x"})]),
        Reply(content="done"),
    )
    graph = AgentGraph(spec(llm, tools=[tool]))
    deltas = [e for e in graph.run("go") if e.type == "tool_output_delta"]

    assert [d.payload["chunk"] for d in deltas] == ["x-0", "x-1", "x-2"]
    assert all(d.payload["tool_call_id"] for d in deltas)


def test_history_is_paired_after_a_tool_round_trip():
    llm = ScriptedLLM(
        Reply(tool_calls=[ToolCall(name="echo", arguments={"text": "a"})]),
        Reply(content="done"),
    )
    result = run_to_result(spec(llm, tools=[EchoTool()]), "go")
    assert result.metadata["pairing_ok"] is True
    assert result.metadata["pairing_problems"] == []


def test_a_failing_tool_does_not_end_the_run():
    llm = ScriptedLLM(
        Reply(tool_calls=[ToolCall(name="echo", arguments={"text": "a"})]),
        Reply(content="recovered"),
    )
    result = run_to_result(spec(llm, tools=[EchoTool(fail=True)]), "go")
    assert result.output == "recovered"
    assert result.tool_results[0].is_error


def test_an_unknown_tool_is_a_recoverable_result():
    llm = ScriptedLLM(
        Reply(tool_calls=[ToolCall(name="nope")]), Reply(content="ok")
    )
    result = run_to_result(spec(llm, tools=[EchoTool()]), "go")
    assert "No tool named" in result.tool_results[0].output
    assert result.output == "ok"


def test_the_prefix_is_built_once_and_stays_stable():
    tool = EchoTool()
    llm = ScriptedLLM(
        Reply(tool_calls=[ToolCall(name="echo", arguments={"text": "a"})]),
        Reply(tool_calls=[ToolCall(name="echo", arguments={"text": "b"})]),
        Reply(content="done"),
    )
    graph = AgentGraph(spec(llm, tools=[tool]))
    list(graph.run("go"))

    prompts = {call["system_prompt"] for call in llm.calls}
    assert len(prompts) == 1
    assert graph.result().metadata["stop_reason"] == StopReason.FINISHED


def test_blocked_parameters_never_reach_the_model():
    llm = ScriptedLLM(Reply(content="ok"))
    graph = AgentGraph(
        spec(llm, model_parameters={"temperature": 0.2, "top_k": 40, "n": 3})
    )
    list(graph.run("hi"))
    sent = llm.calls[0]
    assert "top_k" not in sent and "n" not in sent
    assert sent["temperature"] == 0.2
    assert sent["top_p"] == 0.95  # recommended value filled in


def test_tool_schemas_reach_the_model_already_prepared():
    class RefTool(EchoTool):
        def schema(self) -> dict[str, Any]:
            return {
                "type": "function",
                "function": {
                    "name": "echo",
                    "description": "",
                    "parameters": {
                        "type": "object",
                        "properties": {"f": {"$ref": "#/$defs/F"}},
                        "$defs": {"F": {"type": "string"}},
                    },
                },
            }

    llm = ScriptedLLM(Reply(content="ok"))
    list(AgentGraph(spec(llm, tools=[RefTool()])).run("hi"))
    assert "$ref" not in repr(llm.calls[0]["tools"])


def test_the_loop_stops_at_max_iterations():
    llm = ScriptedLLM(
        *[Reply(tool_calls=[ToolCall(name="echo", arguments={"text": "x"})]) for _ in range(5)]
    )
    graph = AgentGraph(spec(llm, tools=[EchoTool()], max_iterations=2))
    list(graph.run("go"))
    assert graph.stop_reason == StopReason.MAX_ITERATIONS
    assert len(llm.calls) == 2


def test_cancellation_is_observed_between_iterations():
    flag = {"stop": False}
    llm = ScriptedLLM(
        Reply(tool_calls=[ToolCall(name="echo", arguments={"text": "x"})]),
        Reply(content="never"),
    )

    def should_cancel() -> bool:
        was = flag["stop"]
        flag["stop"] = True
        return was

    graph = AgentGraph(spec(llm, tools=[EchoTool()], should_cancel=should_cancel))
    kinds = [e.type for e in graph.run("go")]
    assert "run_cancelled" in kinds
    assert graph.stop_reason == StopReason.CANCELLED


def test_a_denied_tool_pauses_the_run_for_approval():
    llm = ScriptedLLM(Reply(tool_calls=[ToolCall(name="echo", arguments={"text": "rm"})]))
    graph = AgentGraph(spec(llm, tools=[EchoTool()], approve=lambda call: False))
    kinds = [e.type for e in graph.run("go")]
    assert "approval_required" in kinds
    assert graph.stop_reason == StopReason.APPROVAL_REQUIRED
    assert graph.pending_call is not None


def test_usage_is_recorded_for_every_model_call():
    ledger = UsageLedger()
    llm = ScriptedLLM(
        Reply(
            tool_calls=[ToolCall(name="echo", arguments={"text": "a"})],
            usage={"input_tokens": 100, "output_tokens": 10},
        ),
        Reply(content="done", usage={"input_tokens": 120, "output_tokens": 8}),
    )
    list(AgentGraph(spec(llm, tools=[EchoTool()], ledger=ledger)).run("go"))
    assert ledger.totals()["calls"] == 2
    assert ledger.by_purpose()["main"]["output_tokens"] == 18


def test_compaction_is_reported_when_it_happens():
    llm = ScriptedLLM(Reply(content="ok"))
    graph = AgentGraph(
        spec(llm, compact=lambda messages: [Message(role="user", content="compacted")])
    )
    assert "context_compacted" in [e.type for e in graph.run("go")]


# --------------------------------------------------------------------------- #
# Skills inside a run
# --------------------------------------------------------------------------- #


def test_the_catalog_is_in_the_prefix_but_bodies_are_not():
    skills = [FakeSkill(f"s{i}", f"S{i}", "summary", body="BODY" * 500) for i in range(10)]
    graph = AgentGraph(spec(ScriptedLLM(Reply(content="ok")), skills=skills))
    assert "BODY" not in graph.prefix.system_text
    assert graph.prefix.system_text.count("- s") == 10


def test_a_skill_loads_mid_run_and_unlocks_its_tool():
    skill = FakeSkill("echoer", "Echoer", "uses echo", body="USE ECHO", tools=["echo"])
    llm = ScriptedLLM(
        Reply(tool_calls=[ToolCall(name="load_skill", arguments={"skill_id": "echoer"})]),
        Reply(tool_calls=[ToolCall(name="echo", arguments={"text": "now allowed"})]),
        Reply(content="done"),
    )
    tool = EchoTool()
    graph = AgentGraph(spec(llm, tools=[tool], skills=[skill]))
    events = list(graph.run("go"))

    assert "skill_loaded" in [e.type for e in events]
    assert graph.skill_session.is_primed("echoer")
    assert tool.seen == [{"text": "now allowed"}]


def test_always_apply_skills_are_primed_before_the_first_turn():
    skill = FakeSkill("base", "Base", "always", body="ALWAYS")
    graph = AgentGraph(
        spec(ScriptedLLM(Reply(content="ok")), always_apply_skills=[skill])
    )
    assert graph.skill_session.is_primed("base")


# --------------------------------------------------------------------------- #
# Sub-agents
# --------------------------------------------------------------------------- #


def test_a_subagent_gets_a_narrowed_tool_set():
    class Reader(EchoTool):
        name = "file_read"

    class Writer(EchoTool):
        name = "file_write"

    sub = SubagentSpec(llm=ScriptedLLM(), model="m", tools=[Reader(), Writer()])
    assert [t.name for t in sub.narrowed_tools()] == ["file_read"]
    assert "file_write" not in READ_ONLY_TOOLS


def test_only_the_answer_returns_to_the_parent():
    sub = SubagentSpec(llm=ScriptedLLM(Reply(content="the finding")), model="m")
    output = SubagentTool(sub).run(task="investigate")
    assert output.text == "the finding"
    assert "investigate" not in output.text  # no transcript came back


def test_subagent_tokens_reach_the_parent_ledger():
    ledger = UsageLedger()
    sub = SubagentSpec(
        llm=ScriptedLLM(Reply(content="done", usage={"input_tokens": 90, "output_tokens": 9})),
        model="m",
    )
    SubagentTool(sub, ledger=ledger).run(task="work", label="research")
    purposes = ledger.by_purpose()
    assert "subagent" in purposes
    assert purposes["subagent"]["total_tokens"] > 0


def test_delegation_depth_is_bounded():
    sub = SubagentSpec(llm=ScriptedLLM(), model="m", max_depth=1, depth=1)
    output = SubagentTool(sub).run(task="recurse")
    assert "depth limit" in output.text


def test_an_empty_task_is_refused_clearly():
    sub = SubagentSpec(llm=ScriptedLLM(), model="m")
    assert "No task given" in SubagentTool(sub).run(task="  ").text


def test_child_events_are_wrapped_not_interleaved():
    sub = SubagentSpec(llm=ScriptedLLM(Reply(content="x")), model="m")
    seen: list[Any] = []
    SubagentTool(sub, emit=seen.append).run(task="work")
    assert {e.type for e in seen} <= {
        "subagent_started",
        "subagent_event",
        "subagent_completed",
    }


# --------------------------------------------------------------------------- #
# Regressions caught by running the whole thing together
# --------------------------------------------------------------------------- #


def test_a_tools_own_metadata_reaches_the_result():
    """It used to be dropped, so skill_loaded reported an empty skill_id and no
    unlocked tools — the runtime read 'missing' as 'empty'."""

    class Annotating(EchoTool):
        def run(self, context=None, **kwargs):
            from shipit_agent.tools_compat import make_output

            return make_output("done", metadata={"skill_id": "review", "count": 3})

    llm = ScriptedLLM(
        Reply(tool_calls=[ToolCall(name="echo", arguments={"text": "x"})]),
        Reply(content="ok"),
    )
    result = run_to_result(spec(llm, tools=[Annotating()]), "go")
    assert result.tool_results[0].metadata["skill_id"] == "review"
    assert result.tool_results[0].metadata["count"] == 3


def test_a_tool_reporting_its_own_error_is_recorded_as_an_error():
    class Failing(EchoTool):
        def run(self, context=None, **kwargs):
            from shipit_agent.tools_compat import make_output

            return make_output("could not do it", metadata={"is_error": True})

    llm = ScriptedLLM(
        Reply(tool_calls=[ToolCall(name="echo", arguments={"text": "x"})]),
        Reply(content="ok"),
    )
    result = run_to_result(spec(llm, tools=[Failing()]), "go")
    assert result.tool_results[0].is_error


def test_expected_and_unexpected_prefix_movement_are_distinguished():
    """Discovery legitimately rebinds tools; that is not drift."""
    llm = ScriptedLLM(Reply(content="ok"))
    graph = AgentGraph(spec(llm))
    summary = next(e for e in graph.run("hi") if e.type == "run_summary")
    assert summary.payload["prefix_rebuilds"] == 0
    assert summary.payload["prefix_drifted_unexpectedly"] is False
