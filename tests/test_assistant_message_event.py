"""One ``assistant_message`` event per model response, like the SDK's AssistantMessage.

It carries what the model said alongside its tool calls, which a
non-streaming adapter otherwise never surfaces.
"""

from __future__ import annotations

from typing import Any

from shipit_agent import Agent, FunctionTool
from shipit_agent.core.models import ToolCall
from shipit_agent.llms.base import LLMResponse
from shipit_agent.safety.guardrails import Guardrails

USAGE = {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}


class _TwoSteps:
    model = "claude-sonnet-5-5"

    def __init__(self) -> None:
        self.steps = [
            LLMResponse(
                content="Let me look.",
                tool_calls=[ToolCall(name="echo", arguments={"text": "x"}, id="c1")],
                reasoning_content="I should echo first.",
                usage=USAGE,
                metadata={"finish_reason": "tool_use"},
            ),
            LLMResponse(content="All done.", usage=USAGE, metadata={"finish_reason": "end_turn"}),
        ]

    def complete(self, **_: Any) -> LLMResponse:
        return self.steps.pop(0)


def _echo(text: str = "") -> str:
    """Echo the text."""
    return f"echo:{text}"


ECHO = FunctionTool.from_callable(_echo, name="echo")


def _messages(**options: Any) -> list[Any]:
    events = Agent(llm=_TwoSteps(), tools=[ECHO], **options).stream("go")
    return [e for e in events if e.type == "assistant_message"]


def test_each_model_response_is_one_assistant_message() -> None:
    first, second = _messages()
    assert first.payload["iteration"] == 1 and second.payload["iteration"] == 2


def test_the_message_carries_text_thinking_and_tool_calls() -> None:
    first, _ = _messages()
    payload = first.payload
    assert payload["content"] == "Let me look."
    assert payload["reasoning"] == "I should echo first."
    assert payload["tool_calls"] == [{"id": "c1", "name": "echo", "arguments": {"text": "x"}}]
    assert payload["model"] == "claude-sonnet-5-5"
    assert payload["usage"]["total_tokens"] == 7
    assert payload["stop_reason"] == "tool_use"


def test_an_answer_step_has_text_and_no_tool_calls() -> None:
    _, second = _messages()
    assert second.payload["content"] == "All done."
    assert second.payload["tool_calls"] == []
    assert second.payload["stop_reason"] == "end_turn"


def test_text_is_left_out_when_guardrails_may_rewrite_the_answer() -> None:
    guardrails = Guardrails(block_secret_leaks=True)
    assert guardrails.modifies_output()
    first, second = _messages(guardrails=guardrails)
    assert first.payload["content"] == "" and second.payload["content"] == ""
    assert first.payload["tool_calls"][0]["name"] == "echo"
