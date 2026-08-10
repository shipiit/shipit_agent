"""A reminder is only worth having if it is last, short, and not repeated.

Models attend most strongly to the tokens closest to generation, so an
instruction that must hold every step goes after the conversation rather than
at the top of the system prompt. That only works if the runtime keeps three
properties, each pinned below: it reaches the model, it is genuinely last,
and it is rebuilt rather than stacked.
"""

from __future__ import annotations

from typing import Any

from shipit_agent import Agent, FunctionTool
from shipit_agent.llms.base import LLMResponse
from shipit_agent.models import ToolCall
from shipit_agent.prompts.reminders import (
    DEPTH_REMINDER,
    GROUNDING_REMINDER,
    LAST_STEP_REMINDER,
    build_reminder,
)


class TestWhatItSays:
    def test_before_any_tool_it_warns_against_inventing(self) -> None:
        """The observed failure: asked for the latest cases, the agent called
        nothing and returned a full table of invented case IDs, describing
        them as retrieved."""
        assert build_reminder(ran_tools=False, out_of_steps=False) == GROUNDING_REMINDER

    def test_after_tools_it_asks_for_depth(self) -> None:
        text = build_reminder(ran_tools=True, out_of_steps=False)
        assert text == DEPTH_REMINDER

    def test_on_the_last_step_it_asks_for_an_answer(self) -> None:
        text = build_reminder(ran_tools=True, out_of_steps=True)
        assert text == LAST_STEP_REMINDER

    def test_the_last_step_beats_depth(self) -> None:
        """Telling a model to open more files it cannot open wastes the step."""
        assert DEPTH_REMINDER not in build_reminder(
            ran_tools=True, out_of_steps=True
        )

    def test_custom_guidance_is_always_included(self) -> None:
        text = build_reminder(ran_tools=False, out_of_steps=False, custom="Cite ids.")
        assert text.endswith("Cite ids.")

    def test_custom_guidance_joins_a_built_in(self) -> None:
        text = build_reminder(ran_tools=True, out_of_steps=False, custom="Cite ids.")
        assert DEPTH_REMINDER in text and text.endswith("Cite ids.")

    def test_blank_custom_guidance_adds_nothing(self) -> None:
        assert build_reminder(
            ran_tools=False, out_of_steps=False, custom="   "
        ) == GROUNDING_REMINDER

    def test_exactly_one_built_in_applies_at_a_time(self) -> None:
        """Three risks, three phases of a turn — never two at once, or the
        reminder becomes the boilerplate it exists to avoid being."""
        for ran, out in ((False, False), (True, False), (True, True)):
            text = build_reminder(ran_tools=ran, out_of_steps=out)
            present = [
                r for r in (GROUNDING_REMINDER, DEPTH_REMINDER, LAST_STEP_REMINDER)
                if r in text
            ]
            assert len(present) == 1, (ran, out, present)

    def test_grounding_gives_way_once_a_tool_has_run(self) -> None:
        """After retrieval the risk is no longer invention."""
        assert GROUNDING_REMINDER not in build_reminder(
            ran_tools=True, out_of_steps=False
        )


class _Recorder:
    """Captures the exact message list each completion received."""

    def __init__(self, script: list[LLMResponse]) -> None:
        self.script = script
        self.calls = 0
        self.seen: list[list[Any]] = []

    def complete(self, *, messages, tools=None, **_kw) -> LLMResponse:
        self.seen.append(list(messages))
        self.calls += 1
        return self.script[min(self.calls - 1, len(self.script) - 1)]

    def texts(self, index: int) -> list[str]:
        return [
            (m.get("content") if isinstance(m, dict) else m.content) or ""
            for m in self.seen[index]
        ]


def _echo(query: str) -> str:
    """Search the echo feed."""
    return f"15 results for {query}"


def _agent(llm, **kw) -> Agent:
    return Agent(
        llm=llm,
        tools=[FunctionTool.from_callable(_echo, name="search_echo")],
        auto_use_skills=False,
        **kw,
    )


class TestItReachesTheModel:
    def test_it_is_absent_before_any_tool_has_run(self) -> None:
        llm = _Recorder([LLMResponse(content="done")])
        _agent(llm).run("hi")
        assert not any(DEPTH_REMINDER in t for t in llm.texts(0))

    def test_it_appears_once_a_tool_has_run(self) -> None:
        llm = _Recorder([
            LLMResponse(tool_calls=[ToolCall(name="search_echo",
                                             arguments={"query": "qilin"})]),
            LLMResponse(content="done"),
        ])
        _agent(llm).run("tell me about qilin in detail")
        assert any(DEPTH_REMINDER in t for t in llm.texts(1))

    def test_it_is_the_very_last_message(self) -> None:
        """Its whole value is proximity to generation."""
        llm = _Recorder([
            LLMResponse(tool_calls=[ToolCall(name="search_echo",
                                             arguments={"query": "q"})]),
            LLMResponse(content="done"),
        ])
        _agent(llm).run("detail please")
        assert DEPTH_REMINDER in llm.texts(1)[-1]

    def test_custom_guidance_reaches_the_model(self) -> None:
        llm = _Recorder([LLMResponse(content="done")])
        _agent(llm, reminder="Always cite the echo id.").run("hi")
        assert "Always cite the echo id." in llm.texts(0)[-1]


class TestItDoesNotAccumulate:
    def _run(self) -> _Recorder:
        llm = _Recorder([
            LLMResponse(tool_calls=[ToolCall(name="search_echo",
                                             arguments={"query": "a"})]),
            LLMResponse(tool_calls=[ToolCall(name="search_echo",
                                             arguments={"query": "b"})]),
            LLMResponse(content="done"),
        ])
        _agent(llm, max_iterations=5).run("detail")
        return llm

    def test_only_ever_one_copy_is_in_context(self) -> None:
        """Appended to a per-call copy, never to the conversation itself."""
        llm = self._run()
        for index in range(llm.calls):
            assert sum(DEPTH_REMINDER in t for t in llm.texts(index)) <= 1

    def test_it_never_enters_the_saved_conversation(self) -> None:
        llm = _Recorder([
            LLMResponse(tool_calls=[ToolCall(name="search_echo",
                                             arguments={"query": "a"})]),
            LLMResponse(content="done"),
        ])
        result = _agent(llm).run("detail")
        assert not any(
            DEPTH_REMINDER in (m.content or "") for m in result.messages
        )
