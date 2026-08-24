"""A tool whose arguments keep being rejected must not be reprompted forever.

The argument guard (``check_arguments``) already stops a malformed call from
reaching ``execute()``. What it did not do was bound the *recovery*: the model
could emit a fresh malformed payload every step, receive a fresh corrective
message, and burn the whole ``max_iterations`` budget rebilling the prompt.
"""

from __future__ import annotations

import asyncio
import threading

from shipit_agent import Agent
from shipit_agent.llms.base import LLMResponse
from shipit_agent.models import ToolCall
from shipit_agent.runtime import AgentRuntime
from shipit_agent.runtime_state import RuntimeState
from shipit_agent.tools.base import ToolOutput


class RecordingTool:
    name = "recall_results"
    description = "Recall earlier results"
    prompt_instructions = ""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def schema(self):
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        }

    def run(self, context, **kwargs):
        self.calls.append(kwargs)
        return ToolOutput(text="result")


class HealthyTool(RecordingTool):
    name = "summarize"
    description = "Summarize what is already known"


def _degenerate(seed: int) -> str:
    """A different pathologically repetitive payload on every completion."""
    return " ".join([f"expand plan step {seed} repeatedly"] * 40)


class AlwaysMalformedLLM:
    """Never gives up: a new call id and a new bad payload every completion."""

    model = "test-model"
    target = "recall_results"

    def __init__(self) -> None:
        self.calls = 0
        self.tool_free_calls = 0

    def complete(self, **kwargs):
        self.calls += 1
        if not kwargs.get("tools"):
            self.tool_free_calls += 1
            return LLMResponse(content="I could not build a valid call.")
        return LLMResponse(
            tool_calls=[
                ToolCall(
                    id=f"call-{self.calls}",
                    name=self.target,
                    arguments={"query": _degenerate(self.calls)},
                )
            ]
        )


class RecoveringLLM:
    """One malformed attempt, then a valid call — recovery must still work."""

    model = "test-model"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        name="recall_results",
                        arguments={"query": _degenerate(1)},
                    )
                ]
            )
        if self.calls == 2:
            return LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="call-2", name="recall_results", arguments={"query": "Akira"}
                    )
                ]
            )
        return LLMResponse(content="Recovered cleanly.")


class ValidAfterQuarantineLLM:
    """Keeps calling the tool, with valid arguments once it is quarantined."""

    model = "test-model"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, **kwargs):
        self.calls += 1
        if self.calls <= 2:
            return LLMResponse(
                tool_calls=[
                    ToolCall(
                        id=f"call-{self.calls}",
                        name="recall_results",
                        arguments={"query": _degenerate(self.calls)},
                    )
                ]
            )
        if self.calls == 3:
            return LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="call-3",
                        name="recall_results",
                        arguments={"query": "ok"},
                    )
                ]
            )
        return LLMResponse(content="Done.")


class BrokenThenHealthyLLM:
    """Burns one tool's budget, then does the work with a different tool."""

    model = "test-model"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, **kwargs):
        self.calls += 1
        if self.calls <= 2:
            return LLMResponse(
                tool_calls=[
                    ToolCall(
                        id=f"call-{self.calls}",
                        name="recall_results",
                        arguments={"query": _degenerate(self.calls)},
                    )
                ]
            )
        if self.calls == 3:
            return LLMResponse(
                tool_calls=[
                    ToolCall(id="call-3", name="summarize", arguments={"query": "ok"})
                ]
            )
        return LLMResponse(content="Answered with the other tool.")


class ParallelMalformedLLM:
    """One completion, two malformed calls to the same tool."""

    model = "test-model"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, **kwargs):
        self.calls += 1
        if not kwargs.get("tools"):
            return LLMResponse(content="Could not build a valid call.")
        return LLMResponse(
            tool_calls=[
                ToolCall(
                    id=f"call-{self.calls}-a",
                    name="recall_results",
                    arguments={"query": _degenerate(self.calls)},
                ),
                ToolCall(
                    id=f"call-{self.calls}-b",
                    name="recall_results",
                    arguments={"query": _degenerate(self.calls + 100)},
                ),
            ]
        )


def _agent(llm, tools, **kwargs):
    return Agent(
        llm=llm,
        tools=tools if isinstance(tools, list) else [tools],
        auto_use_skills=False,
        max_iterations=8,
        **kwargs,
    )


def test_repeated_rejections_stop_within_the_budget():
    tool = RecordingTool()
    llm = AlwaysMalformedLLM()
    result = _agent(llm, tool).run("recall the earlier results")

    assert tool.calls == []
    rejected = [e for e in result.events if e.type == "tool_arguments_rejected"]
    exhausted = [
        e for e in result.events if e.type == "tool_argument_recovery_exhausted"
    ]
    assert len(rejected) == 2, f"expected 2 rejections, saw {len(rejected)}"
    assert len(exhausted) == 1
    # rejection_budget + 1: two rejected attempts, then one text-only close-out.
    assert llm.calls == 3, f"expected 3 completions, saw {llm.calls}"
    assert llm.tool_free_calls == 1
    assert result.output == "I could not build a valid call."


def test_async_runtime_bounds_recovery_identically():
    tool = RecordingTool()
    llm = AlwaysMalformedLLM()
    result = asyncio.run(_agent(llm, tool).arun("recall the earlier results"))

    assert tool.calls == []
    assert llm.calls == 3, f"expected 3 completions, saw {llm.calls}"
    assert (
        len([e for e in result.events if e.type == "tool_argument_recovery_exhausted"])
        == 1
    )
    # Same tool-side event sequence in both loops. Compared over the tool and
    # argument events only: the sync loop also emits ``final_answer``, a
    # difference that predates this policy and is not part of it.
    sync = _agent(AlwaysMalformedLLM(), RecordingTool()).run(
        "recall the earlier results"
    )

    def _tool_events(events):
        return [e.type for e in events if e.type.startswith("tool_")]

    assert _tool_events(result.events) == _tool_events(sync.events)
    assert _tool_events(sync.events) == [
        "tool_group_started",
        "tool_arguments_rejected",
        "tool_group_completed",
        "tool_group_started",
        "tool_arguments_rejected",
        "tool_argument_recovery_exhausted",
        "tool_group_completed",
    ]


def test_one_bad_attempt_followed_by_a_valid_call_still_recovers():
    tool = RecordingTool()
    llm = RecoveringLLM()
    result = _agent(llm, tool).run("recall the earlier results")

    assert tool.calls == [{"query": "Akira"}]
    assert result.output == "Recovered cleanly."
    assert [
        e for e in result.events if e.type == "tool_argument_recovery_exhausted"
    ] == []


def test_rejection_budget_is_configurable():
    tool = RecordingTool()
    llm = AlwaysMalformedLLM()
    _agent(llm, tool, max_consecutive_tool_argument_rejections=1).run("recall")

    assert tool.calls == []
    assert llm.calls == 2, f"expected 2 completions, saw {llm.calls}"


def test_required_tool_exhaustion_gives_up_truthfully():
    tool = RecordingTool()
    llm = AlwaysMalformedLLM()
    result = _agent(llm, tool, required_tools=["recall_results"]).run("recall")

    assert tool.calls == []
    assert llm.calls == 3, f"expected 3 completions, saw {llm.calls}"
    assert result.metadata.get("gave_up") is True


def test_quarantined_tool_does_not_run_even_with_valid_arguments():
    tool = RecordingTool()
    llm = ValidAfterQuarantineLLM()
    _agent(llm, tool).run("recall")

    assert tool.calls == []


def test_stream_matches_run():
    tool = RecordingTool()
    llm = AlwaysMalformedLLM()
    events = list(
        Agent(
            llm=llm, tools=[tool], auto_use_skills=False, max_iterations=8
        ).stream("recall")
    )

    assert tool.calls == []
    assert llm.calls == 3, f"expected 3 completions, saw {llm.calls}"
    assert len([e for e in events if e.type == "tool_argument_recovery_exhausted"]) == 1


def test_a_healthy_tool_survives_another_tools_quarantine():
    """`require_tool_call` means "call some tool", not "call *this* tool".

    Quarantining one tool while another is still advertised and callable is
    not a failed run, and reporting ``gave_up`` there tells the caller the
    request could not be completed when it just was.
    """
    broken, healthy = RecordingTool(), HealthyTool()
    llm = BrokenThenHealthyLLM()
    result = _agent(llm, [broken, healthy], require_tool_call=True).run("recall")

    assert broken.calls == []
    assert healthy.calls == [{"query": "ok"}]
    assert result.metadata.get("gave_up") is not True
    assert not result.metadata.get("give_up_needs")


def test_parallel_malformed_calls_cost_one_strike():
    """A batch of parallel bad calls to one tool is one completion, one strike.

    The budget counts completions, not calls — otherwise the number of
    parallel calls the model happens to emit decides how fast the tool is
    quarantined.
    """
    tool = RecordingTool()
    llm = ParallelMalformedLLM()
    result = _agent(
        llm, tool, parallel_tool_execution=True, max_tool_concurrency=4
    ).run("recall")

    assert tool.calls == []
    assert llm.calls == 3, f"expected 3 completions, saw {llm.calls}"
    assert (
        len([e for e in result.events if e.type == "tool_argument_recovery_exhausted"])
        == 1
    )


def test_the_rejection_counter_is_safe_under_concurrent_calls():
    """Threads in one completion share ``state``; the counter must not race.

    ``shared_state`` is deep-copied per call, but ``RuntimeState`` is not —
    the sync loop's ThreadPoolExecutor hands the same object to every worker,
    so the read-modify-write here has to be synchronized.
    """
    runtime = AgentRuntime(
        llm=AlwaysMalformedLLM(),
        prompt="test",
        tools=[RecordingTool()],
        max_consecutive_tool_argument_rejections=2,
    )
    state = RuntimeState()
    barrier = threading.Barrier(8)
    exhausted: list[bool] = []
    lock = threading.Lock()

    def strike() -> None:
        barrier.wait()
        hit = runtime.note_argument_rejection(state, "recall_results", 1)
        with lock:
            exhausted.append(hit)

    threads = [threading.Thread(target=strike) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # Eight concurrent calls, one completion: exactly one strike, no quarantine
    # yet (the budget is 2), and nobody saw an exhaustion that did not happen.
    assert state.tool_argument_rejections["recall_results"] == (1, 1)
    assert state.quarantined_tools == set()
    assert exhausted == [False] * 8
