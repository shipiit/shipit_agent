"""Clarifying questions the Claude Agent SDK way.

The model asks with ``questions`` (1-4, each with a ``header``, 2-4
``options`` of ``label`` and ``description``, and ``multiSelect``). The
app's ``can_use_tool`` is called with the tool name ``"AskUserQuestion"``
and answers by returning ``PermissionResultAllow(updated_input={"questions":
..., "answers": {question: label}})``, or ``"response"`` for a free reply.
"""

from __future__ import annotations

from typing import Any, Callable

from shipit_agent.tools.base import ToolContext, ToolOutput

from .permissions import PermissionResultDeny, ToolPermissionContext
from .tools import run_maybe_async

__all__ = ["AskUserQuestionTool"]

_NO_ONE = ("No one can answer questions in this run. Make the most reasonable "
           "assumption, say what you assumed, and continue.")


class AskUserQuestionTool:
    """``ask_user`` with the SDK's question format, answered through ``can_use_tool``."""

    name = "ask_user"
    description = "Ask the user clarifying multiple-choice questions when the task has several valid approaches."
    prompt_instructions = (
        "Ask only when the answer changes what you do and you cannot find it out yourself. "
        "Offer 2-4 concrete options per question; at most 4 questions at once."
    )
    read_only = True

    def __init__(self, can_use_tool: Callable[..., Any] | None) -> None:
        self.can_use_tool = can_use_tool

    def schema(self) -> dict[str, Any]:
        option = {"type": "object", "properties": {"label": {"type": "string"}, "description": {"type": "string"}},
                  "required": ["label", "description"]}
        question = {"type": "object", "properties": {
            "question": {"type": "string", "description": "The full question"},
            "header": {"type": "string", "description": "A short label, at most 12 characters"},
            "options": {"type": "array", "items": option, "minItems": 2, "maxItems": 4},
            "multiSelect": {"type": "boolean", "description": "Whether several options may be chosen"},
        }, "required": ["question", "header", "options", "multiSelect"]}
        return {"type": "function", "function": {
            "name": self.name, "description": self.description,
            "parameters": {"type": "object", "properties": {
                "questions": {"type": "array", "items": question, "minItems": 1, "maxItems": 4}},
                "required": ["questions"]},
        }}

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        questions = kwargs.get("questions")
        if not isinstance(questions, list) or not questions:
            return ToolOutput.error("Pass `questions`: a list of 1-4 questions, each with options.")
        if self.can_use_tool is None:
            return ToolOutput(text=_NO_ONE, metadata={"answered": False})
        answer = run_maybe_async(self.can_use_tool, "AskUserQuestion", {"questions": questions},
                                 ToolPermissionContext())
        if isinstance(answer, PermissionResultDeny) or _field(answer, "behavior") == "deny":
            reason = _field(answer, "message") or "the user declined to answer"
            return ToolOutput(text=f"{reason}. {_NO_ONE}", metadata={"answered": False})
        updated = _field(answer, "updated_input") or {}
        return ToolOutput(text=_answer_text(questions, updated), metadata={"answered": True, **updated})


def _field(answer: Any, key: str) -> Any:
    if isinstance(answer, dict):
        return answer.get(key)
    return getattr(answer, key, None)


def _answer_text(questions: list[Any], updated: dict[str, Any]) -> str:
    if updated.get("response"):
        return f"The user responded: {updated['response']}"
    answers = updated.get("answers") or {}
    lines = []
    for item in questions:
        text = str(item.get("question", "")) if isinstance(item, dict) else str(item)
        value = answers.get(text)
        if isinstance(value, list):
            value = ", ".join(map(str, value))
        lines.append(f"- {text} → {value if value not in (None, '') else '(no answer)'}")
    return "The user answered:\n" + "\n".join(lines)
