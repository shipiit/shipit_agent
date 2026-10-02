"""StepRouter inside a real Agent run: routing, accounting, calibration."""

from __future__ import annotations

import asyncio

import pytest

from shipit_agent import Agent, FunctionTool
from shipit_agent.llms.base import LLMResponse
from shipit_agent.models import ToolCall
from shipit_agent.routing import StepRouter

USAGE = {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110}


class Scripted:
    def __init__(self, model: str, *responses: LLMResponse) -> None:
        self.model, self.queue, self.calls = model, list(responses), 0

    def complete(self, *, messages, tools=None, **_kw) -> LLMResponse:
        self.calls += 1
        return self.queue.pop(0)


def calls(name: str) -> LLMResponse:
    return LLMResponse(tool_calls=[ToolCall(name=name, arguments={})], usage=dict(USAGE))


def says(content: str) -> LLMResponse:
    return LLMResponse(content=content, usage=dict(USAGE))


def make(router: StepRouter, **kwargs) -> Agent:
    tools = [FunctionTool.from_callable(lambda: "page one", name="lookup_a"),
             FunctionTool.from_callable(lambda: "page two", name="lookup_b")]
    return Agent(llm=router, tools=tools, auto_use_skills=False,
                 auto_project_memory=False, auto_project_skills=False, **kwargs)


def run(agent: Agent, prompt: str, async_run: bool):
    return asyncio.run(agent.arun(prompt)) if async_run else agent.run(prompt)


@pytest.mark.parametrize("async_run", [False, True])
def test_routine_steps_run_on_the_fast_model(async_run):
    # The runtime appends a reminder as a user message on every tool step; the
    # router must still recognise step two as routine, not a new turn.
    strong = Scripted("strong", calls("lookup_a"), says("Final: 42."))
    fast = Scripted("fast", calls("lookup_b"), says("A draft answer."))
    router = StepRouter(fast=fast, strong=strong)
    result = run(make(router), "Find the number", async_run)

    assert "Final: 42." in result.output
    assert "draft" not in result.output
    assert router.report.to_dict()["steps"] == {"plan": 1, "digest": 1, "escalated": 1}
    assert (fast.calls, strong.calls) == (2, 2)


@pytest.mark.parametrize("async_run", [False, True])
def test_the_discarded_fast_call_is_counted_in_usage(async_run):
    strong = Scripted("strong", calls("lookup_a"), says("Final."))
    fast = Scripted("fast", says("A draft answer."))
    result = run(make(StepRouter(fast=fast, strong=strong)), "go", async_run)
    diagnostics = result.metadata["run_summary"]["usage_diagnostics"]
    # plan + escalated answer + the fast draft that was thrown away.
    assert diagnostics["reported_tokens_by_purpose"]["main"] == 3 * 110
    assert diagnostics["discarded_tokens"] == 110


def test_calibration_learns_from_the_model_that_ran_the_step():
    strong = Scripted("strong", calls("lookup_a"), says("Final."))
    fast = Scripted("fast", calls("lookup_b"), says("draft"))
    agent = make(StepRouter(fast=fast, strong=strong))
    agent.run("go")
    learned = set(agent._session_runtime_state["token_calibrator"]._stats)
    assert "fast" in learned


def test_a_plain_agent_run_marks_the_real_prompt_as_the_turn_start():
    seen = []

    class Model:
        def complete(self, *, messages, **_kw):
            seen.extend(messages)
            return LLMResponse(content="ok")

    Agent(llm=Model(), auto_use_skills=False, auto_project_memory=False,
          auto_project_skills=False).run("hello there")
    starts = [m for m in seen if m.metadata.get("turn_start")]
    assert [m.content for m in starts] == ["hello there"]


class Streams(Scripted):
    """Streams its text through the runtime's delta callback, like a real adapter."""

    def complete(self, *, messages, tools=None, text_delta_callback=None, **_kw):
        response = super().complete(messages=messages, tools=tools)
        if text_delta_callback is not None and response.content:
            for i in range(0, len(response.content), 8):
                if text_delta_callback(response.content[i : i + 8]) is False:
                    return LLMResponse(content=response.content[: i + 8])
        return response


def test_each_model_is_priced_at_its_own_rate():
    from shipit_agent.costs.tracker import CostTracker

    strong = Scripted("gpt-4o", calls("lookup_a"), says("Final."))
    fast = Scripted("gpt-4o-mini", calls("lookup_b"), says("draft"))
    result = make(StepRouter(fast=fast, strong=strong)).run("go")
    summary = result.metadata["run_summary"]
    by_model = summary["usage_diagnostics"]["tokens_by_model"]
    assert set(by_model) == {"gpt-4o", "gpt-4o-mini"}
    # fast: one digest step + the discarded draft; strong: plan + final answer.
    assert by_model["gpt-4o-mini"]["input"] == 200 and by_model["gpt-4o"]["input"] == 200

    tracker = CostTracker()
    expected = sum(tracker.calculate_cost(m, b["input"], b["output"]) for m, b in by_model.items())
    all_strong = tracker.calculate_cost("gpt-4o", 400, 40)
    assert summary["estimated_cost_usd"] == round(expected, 6)
    assert summary["estimated_cost_usd"] < all_strong


def test_a_streamed_run_never_exposes_the_fast_draft():
    strong = Streams("strong", calls("lookup_a"), says("The strong answer."))
    fast = Streams("fast", says("FASTDRAFT " * 20))
    events = list(make(StepRouter(fast=fast, strong=strong)).stream("go"))
    assert "FASTDRAFT" not in repr([e.payload for e in events])
    final = next(e for e in events if e.type == "final_answer")
    assert final.payload["content"] == "The strong answer."


def test_routing_survives_a_compaction_of_the_turns_opening():
    from shipit_agent.compaction import CompactionCheckpoint
    from shipit_agent.models import Message
    from shipit_agent.routing import classify_step

    history = [Message(role="system", content="sys"),
               Message(role="user", content="find it", metadata={"turn_start": True}),
               Message(role="assistant", tool_calls=[ToolCall(name="lookup_a", id="c0")]),
               Message(role="tool", content="page zero", tool_call_id="c0"),
               Message(role="user", content="Re-issue the call.",
                       metadata={"internal": True, "kind": "required_tool_retry"}),
               Message(role="assistant", tool_calls=[ToolCall(name="lookup_a", id="c1")]),
               Message(role="tool", content="page one", tool_call_id="c1")]
    # Compaction cut at the injected retry nudge, folding the real prompt away.
    checkpoint = CompactionCheckpoint(compacted_to=4, summary="Summary.",
                                      tokens_before=100, tokens_after=20)
    replayed = checkpoint.replay(history)
    assert not any(m.metadata.get("turn_start") for m in replayed)
    tools = [{"type": "function", "function": {"name": "lookup_b"}}]
    assert classify_step(replayed, tools=tools, metadata=None) == "digest"
