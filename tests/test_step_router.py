"""StepRouter — which model runs each step, and how a fast step escalates."""

from __future__ import annotations

import asyncio

import pytest

from shipit_agent.llms.base import LLMResponse
from shipit_agent.models import Message, ToolCall
from shipit_agent.routing import StepRouter, classify_step
from shipit_agent.routing.step_router import TURN_START

TOOLS = [{"type": "function", "function": {"name": "search"}}]
USAGE = {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110}


def turn(text: str = "find a flight") -> Message:
    return Message(role="user", content=text, metadata={TURN_START: True})


def asked(name: str = "search") -> Message:
    return Message(role="assistant", tool_calls=[ToolCall(name=name, id="c1")])


def answered(error: str | None = None) -> Message:
    meta = {"error": error} if error else {}
    return Message(role="tool", content="result", tool_call_id="c1", metadata=meta)


def reminder() -> Message:
    return Message(role="user", content="Use your tools; do not restate the plan.")


def tool_call() -> LLMResponse:
    return LLMResponse(tool_calls=[ToolCall(name="search", id="c2")], usage=dict(USAGE))


def text(content: str, usage: dict | None = None) -> LLMResponse:
    return LLMResponse(content=content, usage=dict(USAGE) if usage is None else usage)


class Streaming:
    """Streams queued responses in chunks and stops when the callback says so."""

    def __init__(self, model: str, *responses: LLMResponse) -> None:
        self.model = model
        self.queue = list(responses)
        self.calls: list[dict] = []
        self.aborted = False

    def complete(self, *, messages, tools=None, system_prompt=None, metadata=None,
                 text_delta_callback=None, require_tool_call=False) -> LLMResponse:
        self.calls.append({"tools": tools, "require_tool_call": require_tool_call})
        response = self.queue.pop(0)
        if text_delta_callback is None or not response.content:
            return response
        sent = ""
        for i in range(0, len(response.content), 40):
            sent += response.content[i : i + 40]
            if text_delta_callback(response.content[i : i + 40]) is False:
                self.aborted = True
                # Streamed APIs often report usage only in the final chunk.
                return LLMResponse(content=sent)
        return response


class Plain:
    """An adapter with no streaming support at all."""

    def __init__(self, model: str, *responses: LLMResponse) -> None:
        self.model, self.queue, self.calls = model, list(responses), 0

    def complete(self, *, messages, tools=None, system_prompt=None, metadata=None):
        self.calls += 1
        return self.queue.pop(0)


def route(router: StepRouter, messages, *, tools=TOOLS, metadata=None, run_async=False):
    seen: list[str] = []
    kwargs = {"messages": messages, "tools": tools, "metadata": metadata,
              "text_delta_callback": lambda chunk: seen.append(chunk)}
    if run_async:
        response = asyncio.run(router.acomplete(**kwargs))
    else:
        response = router.complete(**kwargs)
    return response, "".join(seen)


class TestClassifyStep:
    def test_first_step_of_a_turn_plans(self):
        assert classify_step([turn()], tools=TOOLS, metadata=None) == "plan"

    def test_successful_tool_results_are_digested(self):
        assert classify_step([turn(), asked(), answered()], tools=TOOLS, metadata=None) == "digest"

    def test_a_failed_tool_call_is_recovered(self):
        steps = [turn(), asked(), answered(error="tool_failed")]
        assert classify_step(steps, tools=TOOLS, metadata=None) == "recover"

    def test_an_injected_user_message_does_not_start_a_turn(self):
        steps = [turn(), asked(), answered(), reminder()]
        assert classify_step(steps, tools=TOOLS, metadata=None) == "digest"

    def test_only_the_latest_turn_counts(self):
        steps = [turn("first"), asked(), answered(error="x"),
                 Message(role="assistant", content="done"), turn("second")]
        assert classify_step(steps, tools=TOOLS, metadata=None) == "plan"

    def test_no_tools_means_the_reply_is_the_answer(self):
        assert classify_step([turn(), asked(), answered()], tools=None, metadata=None) == "answer"
        assert classify_step([turn(), asked(), answered()], tools=[], metadata=None) == "answer"

    def test_a_compacted_turn_start_still_routes_mid_turn_steps(self):
        summary = Message(role="user", content="Summary of the turn so far.",
                          metadata={"compacted": True})
        assert classify_step([summary], tools=TOOLS, metadata=None) == "plan"
        assert classify_step([summary, asked(), answered()], tools=TOOLS, metadata=None) == "digest"

    def test_without_a_turn_marker_it_stays_on_the_strong_model(self):
        steps = [Message(role="user", content="hi"), asked(), answered()]
        assert classify_step(steps, tools=TOOLS, metadata=None) == "plan"

    @pytest.mark.parametrize("purpose", ["context_compaction", "agent_decision_summary"])
    def test_summaries_are_fast_work(self, purpose):
        assert classify_step([turn()], tools=None, metadata={"purpose": purpose}) == "summary"

    def test_other_side_calls_stay_strong(self):
        meta = {"purpose": "guardrail_judge"}
        assert classify_step([turn()], tools=None, metadata=meta) == "side"

    def test_plain_dict_messages_are_understood(self):
        steps = [{"role": "user", "content": "go", "metadata": {TURN_START: True}},
                 {"role": "assistant", "content": ""}, {"role": "tool", "content": "ok"}]
        assert classify_step(steps, tools=TOOLS, metadata=None) == "digest"


@pytest.mark.parametrize("run_async", [False, True])
class TestRouting:
    def test_planning_runs_on_strong_and_streams_live(self, run_async):
        fast, strong = Streaming("fast"), Streaming("strong", text("Here is the plan."))
        response, seen = route(StepRouter(fast=fast, strong=strong), [turn()], run_async=run_async)
        assert (fast.calls, len(strong.calls)) == ([], 1)
        assert seen == "Here is the plan."
        assert response.metadata["route"] == {"step": "plan", "model": "strong"}

    def test_a_fast_tool_step_stands_and_its_narration_is_released(self, run_async):
        narration = tool_call()
        narration.content = "Checking the next page."
        fast, strong = Streaming("fast", narration), Streaming("strong")
        router = StepRouter(fast=fast, strong=strong)
        response, seen = route(router, [turn(), asked(), answered()], run_async=run_async)
        assert response.tool_calls and strong.calls == []
        assert seen == "Checking the next page."
        assert response.metadata["route"]["step"] == "digest"
        assert router.report.to_dict()["steps"] == {"digest": 1}

    def test_a_long_fast_answer_is_cut_and_rerun_on_strong(self, run_async):
        fast = Streaming("fast", text("A small model's final answer. " * 100))
        strong = Streaming("strong", text("The strong model's answer."))
        router = StepRouter(fast=fast, strong=strong, escalate_after_chars=200)
        response, seen = route(router, [turn(), asked(), answered()], run_async=run_async)
        assert fast.aborted
        assert seen == "The strong model's answer."  # never the fast text, never twice
        assert response.metadata["route"] == {"step": "escalated", "model": "strong"}
        assert router.report.to_dict()["escalations"] == 1

    def test_a_short_fast_answer_is_also_escalated(self, run_async):
        fast, strong = Streaming("fast", text("Done.")), Streaming("strong", text("All set."))
        response, seen = route(StepRouter(fast=fast, strong=strong),
                               [turn(), asked(), answered()], run_async=run_async)
        assert not fast.aborted and seen == "All set."
        assert response.metadata["discarded_usage"]["prompt_tokens"] == 100

    def test_aborted_usage_is_estimated_not_recorded_as_zero(self, run_async):
        fast = Streaming("fast", text("word " * 500, usage={}))
        strong = Streaming("strong", text("ok"))
        router = StepRouter(fast=fast, strong=strong, escalate_after_chars=100)
        response, _ = route(router, [turn(), asked(), answered()], run_async=run_async)
        discarded = response.metadata["discarded_usage"]
        assert discarded["estimated"] is True
        assert discarded["prompt_tokens"] > 0 and discarded["completion_tokens"] > 0

    def test_a_non_streaming_fast_model_still_escalates(self, run_async):
        fast, strong = Plain("fast", text("Done.")), Plain("strong", text("All set."))
        response, _ = route(StepRouter(fast=fast, strong=strong),
                            [turn(), asked(), answered()], run_async=run_async)
        assert (fast.calls, strong.calls) == (1, 1)
        assert response.content == "All set."

    def test_summaries_go_fast_and_never_escalate(self, run_async):
        fast, strong = Streaming("fast", text("Summary.")), Streaming("strong")
        response, _ = route(StepRouter(fast=fast, strong=strong), [turn()], tools=None,
                            metadata={"purpose": "context_compaction"}, run_async=run_async)
        assert response.content == "Summary." and strong.calls == []

    def test_a_failed_tool_is_recovered_on_strong(self, run_async):
        fast, strong = Streaming("fast"), Streaming("strong", tool_call())
        route(StepRouter(fast=fast, strong=strong),
              [turn(), asked(), answered(error="timeout")], run_async=run_async)
        assert fast.calls == [] and len(strong.calls) == 1


def test_forwarded_kwargs_match_each_adapter():
    strong = Plain("strong", text("ok"))
    router = StepRouter(fast=Plain("fast"), strong=strong)
    # Plain names neither the callback nor require_tool_call: neither is sent.
    router.complete(messages=[turn()], tools=TOOLS, require_tool_call=True,
                    text_delta_callback=lambda _c: None, timeout=5)
    assert strong.calls == 1


def test_async_prefers_the_adapters_native_acomplete():
    class Native(Streaming):
        async def acomplete(self, **kwargs):
            self.native = True
            return self.complete(**kwargs)

    strong = Native("strong", text("ok"))
    asyncio.run(StepRouter(fast=Streaming("fast"), strong=strong).acomplete(messages=[turn()], tools=TOOLS))
    assert strong.native is True


def test_model_is_the_one_with_the_tighter_window():
    router = StepRouter(fast=Plain("gpt-4o-mini"), strong=Plain("claude-opus-4"))
    assert router.model in {"gpt-4o-mini", "claude-opus-4"}
    from shipit_agent.compaction import get_model_limits

    windows = {m: get_model_limits(m).context_window for m in ("gpt-4o-mini", "claude-opus-4")}
    assert get_model_limits(router.model).context_window == min(windows.values())


@pytest.mark.parametrize("limit", [0, -5, True, 1.5])
def test_invalid_escalation_threshold(limit):
    with pytest.raises(ValueError, match="escalate_after_chars"):
        StepRouter(fast=Plain("a"), strong=Plain("b"), escalate_after_chars=limit)
