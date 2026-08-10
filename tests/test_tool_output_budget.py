"""A tool result is paid for on every turn that follows it.

A message list is cumulative, so an unbounded tool output is not a one-off
cost: it is re-sent with every subsequent request. Observed on a real run —
one MCP tool called four times with empty arguments returned the same
138,000 characters each time, and a five-iteration turn spent 507,000 input
tokens.

Two bounds, both here: the model-visible copy is capped, and an identical
repeat is not sent twice. The canonical result stays complete either way.
"""

from __future__ import annotations

from shipit_agent import Agent
from shipit_agent.llms.base import LLMResponse
from shipit_agent.models import ToolCall
from shipit_agent.tools.base import ToolOutput

BIG = "x" * 100_000


class ScriptedLLM:
    model = "m"

    def __init__(self, turns: int) -> None:
        self.turns = turns
        self.calls = 0
        self.context_chars: list[int] = []

    def complete(self, *, messages, tools=None, system_prompt=None,
                 metadata=None, text_delta_callback=None):
        self.calls += 1
        self.context_chars.append(
            sum(len(m.content or "") for m in messages)
        )
        if self.calls <= self.turns:
            return LLMResponse(
                tool_calls=[ToolCall(name="dump", arguments={})],
                usage={"total_tokens": 10},
            )
        return LLMResponse(content="done", usage={"total_tokens": 10})


def dump_tool(payloads=None):
    """A tool returning ``BIG`` each call, or a scripted sequence."""
    class T:
        def __init__(self) -> None:
            self.name = "dump"
            self.description = "dump"
            self.prompt_instructions = ""
            self._n = 0

        def schema(self):
            return {"function": {"name": "dump", "parameters": {"properties": {}}}}

        def run(self, context, **kwargs):
            if payloads is None:
                return ToolOutput(text=BIG)
            text = payloads[min(self._n, len(payloads) - 1)]
            self._n += 1
            return ToolOutput(text=text)

    return T()


def run(*, turns=4, tools=None, cap=None):
    llm = ScriptedLLM(turns)
    kwargs = {} if cap is None else {"max_tool_output_chars": cap}
    agent = Agent(llm=llm, tools=[tools or dump_tool()],
                  auto_use_skills=False, max_iterations=turns + 2, **kwargs)
    return agent.run("go"), llm


class TestTheCap:
    def test_it_is_on_by_default(self) -> None:
        assert Agent(llm=None).max_tool_output_chars == 16_000

    def test_the_model_never_sees_the_whole_body(self) -> None:
        _result, llm = run(turns=1)
        assert max(llm.context_chars) < len(BIG)

    def test_the_caller_still_gets_all_of_it(self) -> None:
        """Bounding the model's copy must not lose the data."""
        result, _llm = run(turns=1)
        assert any(len(r.output) == len(BIG) for r in result.tool_results)

    def test_zero_means_no_cap(self) -> None:
        _result, llm = run(turns=1, cap=0)
        assert max(llm.context_chars) > len(BIG)


class TestARepeatedCall:
    def test_the_same_answer_is_not_sent_twice(self) -> None:
        _result, llm = run(turns=4)
        # Four identical 100k results, capped at 16k each, would still be
        # 64k of tool output. Collapsing the repeats keeps it near one.
        assert max(llm.context_chars) < 24_000

    def test_the_context_stops_growing(self) -> None:
        """The signature of the bug: every turn bigger than the last."""
        _result, llm = run(turns=4)
        growth = llm.context_chars[-1] - llm.context_chars[1]
        assert growth < 2_000, f"context grew {growth} chars across repeats"

    def test_the_pointer_says_where_the_output_went(self) -> None:
        result, _llm = run(turns=4)
        tool_messages = [
            m for m in result.messages if getattr(m, "role", "") == "tool"
        ]
        assert any("already called" in (m.content or "") for m in tool_messages)

    def test_a_changed_answer_is_sent_in_full(self) -> None:
        """Identity is verified, not assumed — the tool still runs."""
        first, second = "a" * 5_000, "b" * 5_000
        _result, llm = run(turns=2, tools=dump_tool([first, second]))
        assert max(llm.context_chars) > 9_000

    def test_a_small_repeat_is_left_alone(self) -> None:
        """Below the threshold, explaining the omission costs more."""
        _result, llm = run(turns=2, tools=dump_tool(["tiny"]))
        joined = llm.context_chars
        assert joined  # ran at all
        assert all(n < 5_000 for n in joined)
