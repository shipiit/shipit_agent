"""Turning a run's events into SDK-shaped messages, as they arrive."""

from __future__ import annotations

import uuid
from typing import Any

from shipit_agent.core.models import AgentEvent
from shipit_agent.core.result_subtype import result_subtype

from .types import (
    AssistantMessage,
    ContentBlock,
    Message,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

__all__ = ["MessageStream", "error_result"]

#: Events that become a ``SystemMessage``, and the subtype each becomes.
_SYSTEM_SUBTYPES = {
    "context_compacted": "compact_boundary",
    "llm_retry": "api_retry",
    "model_fallback": "model_fallback",
    "task_started": "task_started",
    "task_notification": "task_notification",
}
#: Bookkeeping keys every event carries, left out of ``SystemMessage.data``.
_STAMP_KEYS = frozenset({"run_id", "sequence", "session_id"})


class MessageStream:
    """Feed it a run's events in order; it returns the messages each one makes."""

    def __init__(self, *, init: dict[str, Any], partial: bool = False) -> None:
        self.init = dict(init)
        self.partial = partial
        self.session_id = str(init.get("session_id") or "")
        self._started_at: float | None = None

    def feed(self, event: AgentEvent) -> list[Message]:
        if self._started_at is None:
            self._started_at = event.timestamp
        payload = event.payload
        self.session_id = str(payload.get("session_id") or self.session_id)
        kind = event.type
        if kind == "run_started":
            return [SystemMessage("init", {**self.init, "session_id": self.session_id})]
        if kind == "assistant_message":
            return [self._assistant(payload)]
        if kind in ("tool_completed", "tool_failed", "tool_denied", "tool_arguments_rejected"):
            return [self._tool_result(kind, payload)]
        if kind == "text_delta" and self.partial:
            return [self._delta(payload)]
        if kind in _SYSTEM_SUBTYPES:
            data = {k: v for k, v in payload.items() if k not in _STAMP_KEYS}
            return [SystemMessage(_SYSTEM_SUBTYPES[kind], data)]
        if kind == "run_completed":
            return [self._result(event)]
        if kind == "run_failed":
            started = self._started_at if self._started_at is not None else event.timestamp
            failure = ResultMessage(
                subtype="error_during_execution",
                duration_ms=int((event.timestamp - started) * 1000),
                duration_api_ms=0,
                is_error=True,
                num_turns=0,
                session_id=self.session_id,
                errors=[f"{payload.get('error_type', 'Error')}: {payload.get('error', '')}"],
            )
            return [failure]
        return []

    def _assistant(self, payload: dict[str, Any]) -> AssistantMessage:
        blocks: list[ContentBlock] = []
        if payload.get("reasoning"):
            blocks.append(ThinkingBlock(str(payload["reasoning"])))
        if payload.get("content"):
            blocks.append(TextBlock(str(payload["content"])))
        for call in payload.get("tool_calls") or []:
            blocks.append(ToolUseBlock(str(call["id"]), str(call["name"]), dict(call["arguments"])))
        return AssistantMessage(
            content=blocks,
            model=str(payload.get("model") or ""),
            usage=dict(payload.get("usage") or {}),
            stop_reason=payload.get("stop_reason"),
            session_id=self.session_id,
            uuid=str(uuid.uuid4()),
        )

    def _tool_result(self, kind: str, payload: dict[str, Any]) -> UserMessage:
        call_id = str(payload.get("call_id") or payload.get("tool_call_id") or "")
        if kind in ("tool_denied", "tool_arguments_rejected"):
            block = ToolResultBlock(call_id, str(payload.get("reason") or "not permitted"), True)
        else:
            failed = kind == "tool_failed" or bool(payload.get("error"))
            text = payload.get("output")
            if text is None:
                text = payload.get("error") or ""
            block = ToolResultBlock(call_id, str(text), failed)
        return UserMessage(content=[block], uuid=str(uuid.uuid4()))

    def _delta(self, payload: dict[str, Any]) -> StreamEvent:
        delta = {"type": "text_delta", "text": str(payload.get("chunk") or "")}
        return StreamEvent(
            uuid=str(uuid.uuid4()),
            session_id=self.session_id,
            event={"type": "content_block_delta", "delta": delta},
        )

    def _result(self, event: AgentEvent) -> ResultMessage:
        summary = event.payload.get("summary") or {}
        subtype = result_subtype(summary)
        started = self._started_at if self._started_at is not None else event.timestamp
        return ResultMessage(
            subtype=subtype,
            duration_ms=int((event.timestamp - started) * 1000),
            duration_api_ms=int(summary.get("duration_api_ms", 0) or 0),
            is_error=subtype != "success",
            num_turns=int(summary.get("iterations", 0) or 0),
            session_id=self.session_id,
            total_cost_usd=summary.get("estimated_cost_usd"),
            usage=dict(summary.get("usage") or {}),
            result=str(event.payload.get("output") or ""),
            stop_reason=summary.get("finish_reason"),
            permission_denials=[dict(d) for d in summary.get("permission_denials", [])],
        )


def error_result(error: BaseException, *, session_id: str, duration_ms: int = 0) -> ResultMessage:
    """The ``ResultMessage`` for a run that raised instead of finishing."""
    return ResultMessage(
        subtype="error_during_execution",
        duration_ms=duration_ms,
        duration_api_ms=0,
        is_error=True,
        num_turns=0,
        session_id=session_id,
        errors=[f"{type(error).__name__}: {error}"],
    )
