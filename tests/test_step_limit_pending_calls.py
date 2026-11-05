"""Reaching the step limit with tool calls still pending is the step limit.

A response that carried text *and* tool calls at the last step used to be
taken as the final answer: its calls never ran, the run reported success,
and the "answer" was the model's preamble ("Checking.").
"""

from __future__ import annotations

from typing import Any

from shipit_agent import Agent, FunctionTool
from shipit_agent.core.models import ToolCall
from shipit_agent.llms.base import LLMResponse


def _echo(text: str = "") -> str:
    """Echo the text."""
    return f"echo:{text}"


class _KeepsCalling:
    """Says something and calls a tool every step, even when no tools are
    offered (weak models do; so do calls healed from text). The wrap-up
    step, sent with no tools and after the limit, gets a summary."""

    def __init__(self) -> None:
        self.step = 0

    def complete(self, *, tools: Any = None, **_: Any) -> LLMResponse:
        self.step += 1
        if self.step > 2:
            return LLMResponse(content="Summary: echoed once, not finished.")
        return LLMResponse(
            content="Checking.",
            tool_calls=[ToolCall(name="echo", arguments={"text": str(self.step)})],
        )


def _run() -> Any:
    tools = [FunctionTool.from_callable(_echo, name="echo")]
    return Agent(llm=_KeepsCalling(), tools=tools, max_turns=2).run("go")


def test_pending_calls_at_the_limit_end_the_run_as_the_step_limit() -> None:
    result = _run()
    assert result.subtype == "error_max_turns"


def test_the_wrap_up_summary_is_the_answer_not_the_preamble() -> None:
    assert _run().output == "Summary: echoed once, not finished."
