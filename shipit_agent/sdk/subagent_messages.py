"""A sub-agent's work as SDK messages, attributed to the tool call that started it.

The parent's stream carries each child event as ``sub_agent_event`` with the
child's own event inside. Its tool calls become ``AssistantMessage``s and its
tool results ``UserMessage``s, both with ``parent_tool_use_id`` set; a
``task_progress`` ``SystemMessage`` follows each result. A child's text and
thinking are left out unless asked for, and a child never streams partial
events or ends the run: only the parent does.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from .types import (
    AssistantMessage,
    ContentBlock,
    Message,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

__all__ = ["SubagentMessages"]

_RESULT_KINDS = frozenset({"tool_completed", "tool_failed", "tool_denied", "tool_arguments_rejected"})


@dataclass(slots=True)
class _Progress:
    description: str
    started: float
    tokens: int = 0
    tool_uses: int = 0
    last_tool: str | None = None
    calls: dict[str, str] = field(default_factory=dict)


def _tokens(usage: dict[str, Any]) -> int:
    total = usage.get("total_tokens")
    if isinstance(total, int):
        return total
    return int(usage.get("prompt_tokens") or 0) + int(usage.get("completion_tokens") or 0)


class SubagentMessages:
    """Turns forwarded child events into messages; one per parent run."""

    def __init__(self, *, forward_text: bool, session_id: str = "") -> None:
        self.forward_text = forward_text
        self.session_id = session_id
        self._tasks: dict[str, _Progress] = {}

    def feed(self, payload: dict[str, Any], timestamp: float) -> list[Message]:
        parent = payload.get("parent_tool_use_id")
        inner = payload.get("inner")
        kind = payload.get("inner_type")
        if not parent or not isinstance(inner, dict):
            return []
        task = self._tasks.setdefault(str(parent), _Progress(str(payload.get("task") or ""), timestamp))
        if kind == "assistant_message":
            return self._assistant(str(parent), inner, task)
        if kind in _RESULT_KINDS:
            return self._result(str(parent), kind, inner, task, timestamp)
        if kind in ("run_completed", "run_failed"):
            # The child is done: one last report with its final totals.
            return [self._progress(str(parent), task, timestamp)]
        return []

    def _assistant(self, parent: str, inner: dict[str, Any], task: _Progress) -> list[Message]:
        task.tokens += _tokens(dict(inner.get("usage") or {}))
        blocks: list[ContentBlock] = []
        if self.forward_text and inner.get("reasoning"):
            blocks.append(ThinkingBlock(str(inner["reasoning"])))
        if self.forward_text and inner.get("content"):
            blocks.append(TextBlock(str(inner["content"])))
        for call in inner.get("tool_calls") or []:
            task.calls[str(call.get("id") or "")] = str(call.get("name") or "")
            blocks.append(ToolUseBlock(str(call.get("id") or ""), str(call.get("name") or ""), dict(call.get("arguments") or {})))
        if not blocks:
            return []
        message = AssistantMessage(
            content=blocks,
            model=str(inner.get("model") or ""),
            parent_tool_use_id=parent,
            usage=dict(inner.get("usage") or {}),
            stop_reason=inner.get("stop_reason"),
            session_id=self.session_id,
            uuid=str(uuid.uuid4()),
            message_id=f"msg_{uuid.uuid4().hex}",
        )
        return [message]

    def _result(self, parent: str, kind: str, inner: dict[str, Any], task: _Progress, timestamp: float) -> list[Message]:
        call_id = str(inner.get("call_id") or inner.get("tool_call_id") or "")
        if kind in ("tool_denied", "tool_arguments_rejected"):
            block = ToolResultBlock(call_id, str(inner.get("reason") or "not permitted"), True)
        else:
            text = inner.get("output")
            if text is None:
                text = inner.get("error") or ""
            block = ToolResultBlock(call_id, str(text), kind == "tool_failed" or bool(inner.get("error")))
        task.tool_uses += 1
        task.last_tool = str(inner.get("tool") or inner.get("name") or task.calls.get(call_id) or "") or None
        result = UserMessage(content=[block], uuid=str(uuid.uuid4()), parent_tool_use_id=parent)
        return [result, self._progress(parent, task, timestamp)]

    def _progress(self, parent: str, task: _Progress, timestamp: float) -> SystemMessage:
        usage = {"total_tokens": task.tokens, "tool_uses": task.tool_uses,
                 "duration_ms": max(0, int((timestamp - task.started) * 1000))}
        return SystemMessage("task_progress", {
            "task_id": parent, "tool_use_id": parent, "description": task.description,
            "usage": usage, "last_tool_name": task.last_tool,
            "uuid": str(uuid.uuid4()), "session_id": self.session_id,
        })
