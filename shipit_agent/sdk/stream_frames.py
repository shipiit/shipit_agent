"""Framing a model response as the API's stream events, for ``include_partial_messages``.

Each response is ``message_start``, then its blocks in order (thinking, text,
tool calls) as ``content_block_start`` / ``content_block_delta`` /
``content_block_stop``, then ``message_delta`` and ``message_stop``: the
sequence the Claude Agent SDK's ``StreamEvent`` carries. Text streams as the
model writes it. Thinking and tool-call input arrive whole, in one delta each,
once the response is complete and before any tool runs.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

__all__ = ["ResponseFrames"]

_USAGE_KEYS = {"input_tokens": ("input_tokens", "prompt_tokens"), "output_tokens": ("output_tokens", "completion_tokens")}


def _usage(raw: dict[str, Any]) -> dict[str, int]:
    return {name: int(next((raw[key] for key in keys if raw.get(key) is not None), 0)) for name, keys in _USAGE_KEYS.items()}


class ResponseFrames:
    """The stream events of one response at a time; ``finish`` ends it and starts afresh."""

    def __init__(self, model: str) -> None:
        self.model = model
        #: The id of the response that just finished, for its ``AssistantMessage``.
        self.last_message_id = ""
        self._message_id = ""
        self._reset()

    def _reset(self) -> None:
        self._started = False
        self._index = 0
        self._open: str | None = None
        self._streamed_text = False
        self._streamed_calls: set[str] = set()

    def cut(self) -> list[dict[str, Any]]:
        """Close a response that ended mid-stream: its open block, then ``message_stop``."""
        if not self._started:
            return []
        events = [*self._close(), {"type": "message_stop"}]
        self._reset()
        return events

    def text(self, chunk: str) -> list[dict[str, Any]]:
        """A chunk of answer text, as the model writes it."""
        self._streamed_text = True
        return [*self._block("text", {"type": "text", "text": ""}), self._delta({"type": "text_delta", "text": chunk})]

    def tool_input(self, call_id: str, name: str, fragment: str) -> list[dict[str, Any]]:
        """A piece of a tool call's arguments, as the model writes it."""
        self._streamed_calls.add(call_id)
        block = {"type": "tool_use", "id": call_id, "name": name, "input": {}}
        opened = self._block(f"tool_use:{call_id}", block)
        return [*opened, self._delta({"type": "input_json_delta", "partial_json": fragment})]

    def finish(self, payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """The events before and after the response's ``AssistantMessage``."""
        before: list[dict[str, Any]] = []
        reasoning = str(payload.get("reasoning") or "")
        content = str(payload.get("content") or "")
        # A thinking block comes first, so it is only framed when no text has gone out yet.
        if reasoning and not self._started:
            before += self._block("thinking", {"type": "thinking", "thinking": ""})
            before.append(self._delta({"type": "thinking_delta", "thinking": reasoning}))
        if content and not self._streamed_text:
            before += self.text(content)
        calls = payload.get("tool_calls") or []
        for call in calls:
            if str(call["id"]) in self._streamed_calls:
                continue
            block = {"type": "tool_use", "id": str(call["id"]), "name": str(call["name"]), "input": {}}
            before += self._block(f"tool_use:{call['id']}", block)
            before.append(self._delta({"type": "input_json_delta", "partial_json": json.dumps(call["arguments"], default=str)}))
        before = [*self._start(), *before]
        stop_reason = payload.get("stop_reason") or ("tool_use" if calls else "end_turn")
        after = [
            *self._close(),
            {"type": "message_delta", "delta": {"stop_reason": stop_reason}, "usage": _usage(dict(payload.get("usage") or {}))},
            {"type": "message_stop"},
        ]
        self.last_message_id = self._message_id
        self._reset()
        return before, after

    def _start(self) -> list[dict[str, Any]]:
        if self._started:
            return []
        self._started = True
        self._message_id = f"msg_{uuid.uuid4().hex}"
        message = {"id": self._message_id, "type": "message", "role": "assistant", "model": self.model}
        return [{"type": "message_start", "message": message}]

    def _block(self, key: str, content_block: dict[str, Any]) -> list[dict[str, Any]]:
        if self._open == key:
            return []
        events = [*self._start(), *self._close()]
        self._open = key
        events.append({"type": "content_block_start", "index": self._index, "content_block": content_block})
        return events

    def _close(self) -> list[dict[str, Any]]:
        if self._open is None:
            return []
        self._open = None
        self._index += 1
        return [{"type": "content_block_stop", "index": self._index - 1}]

    def _delta(self, delta: dict[str, Any]) -> dict[str, Any]:
        return {"type": "content_block_delta", "index": self._index, "delta": delta}
