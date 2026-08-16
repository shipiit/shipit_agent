"""Blind-call repair — a rejected call gets the tool's full signature back.

With deferred_tools on, a model never sees a tool's schema, so a weak model
guesses argument names (``items`` for ``provided_items``). The guess bounces at
the argument gate; without the signature, the retry is another guess. The gate
now returns the compact callable signature so the next call is correct.
"""

from __future__ import annotations

from typing import Any

from shipit_agent.agent import Agent
from shipit_agent.llms.base import LLMResponse, ToolCall
from shipit_agent.tools.base import ToolContext, ToolOutput


class ClassifyTool:
    name = "classify_specialty"
    read_only = True

    def __init__(self) -> None:
        self.runs = 0

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "classify the request",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "provided_items": {"type": "array"},
                        "evidence_keys": {"type": "object"},
                    },
                    "required": ["provided_items"],
                },
            },
        }

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        self.runs += 1
        return ToolOutput(text="classified", metadata={})


class _BlindThenCorrectLLM:
    """Calls with a wrong arg name first, then (given the signature) correctly."""

    def __init__(self) -> None:
        self.i = 0

    def complete(self, *, messages, tools=None, **_kw) -> LLMResponse:
        self.i += 1
        if self.i == 1:
            # Blind: guessed 'items' instead of 'provided_items'.
            return LLMResponse(
                tool_calls=[ToolCall(name="classify_specialty", arguments={"items": [1, 2]})]
            )
        if self.i == 2:
            # Correct, using the signature handed back.
            return LLMResponse(
                tool_calls=[
                    ToolCall(name="classify_specialty", arguments={"provided_items": [1, 2]})
                ]
            )
        return LLMResponse(content="done")


def _rejection(result):
    return next(
        m for m in result.messages
        if (getattr(m, "metadata", {}) or {}).get("error") == "missing_required_arguments"
    )


def test_blind_call_error_carries_the_signature():
    tool = ClassifyTool()
    result = Agent(llm=_BlindThenCorrectLLM(), tools=[tool], auto_use_skills=False).run("go")
    rejection = _rejection(result)
    # The full signature is in the error: name, required param, optional param.
    assert "Signature: classify_specialty(provided_items: array" in rejection.content
    assert "evidence_keys?: object" in rejection.content
    assert "'provided_items'" in rejection.content


def test_blind_call_then_recovers_and_runs():
    tool = ClassifyTool()
    result = Agent(llm=_BlindThenCorrectLLM(), tools=[tool], auto_use_skills=False).run("go")
    # First call bounced (not run); the corrected second call ran once.
    assert tool.runs == 1


def test_signature_hint_is_robust_to_a_broken_schema():
    from shipit_agent.runtime_core import RuntimeCore

    class Broken:
        name = "x"
        def schema(self):
            raise RuntimeError("no schema")

    assert RuntimeCore._signature_hint(Broken()) == ""      # absent, not a crash
