"""Deferred tool calls: pause a run for a decision that comes later.

A ``PreToolUse`` hook (or a before-tool hook) that answers ``defer`` stops
the run after that step, as in the Claude Agent SDK. The call is saved with
the session as ``deferred_tool_use``; the next run on the session asks
about it again before calling the model, then runs it (or records the
refusal) where it stood in the conversation, and carries on.

Mixed into :class:`~shipit_agent.core.async_runtime.AsyncAgentRuntime`;
the methods run on the runtime instance.
"""

from __future__ import annotations

from typing import Any

from shipit_agent.core.loop.turn import Turn
from shipit_agent.core.models import Message, ToolCall
from shipit_agent.core.state import RuntimeState
from shipit_agent.tools.base import ToolContext

#: Session metadata key, the SDK's name for it.
DEFERRED_KEY = "deferred_tool_use"
_PLACEHOLDER_KIND = "deferred_tool_use"


class PausedCallMixin:
    """Deferred tool calls: pause a run for a decision that comes later."""

    def _pause_tool_call(
        self, state: RuntimeState, *, tool_call: Any, call_id: str, reason: str, iteration: int
    ) -> tuple[None, Message]:
        """Record a deferred call; its placeholder keeps the call answered in the transcript."""
        if self._deferred_tool_use is None:
            self._deferred_tool_use = {"id": call_id, "name": tool_call.name,
                                       "input": dict(tool_call.arguments), "reason": reason}
        self.emit(state, "tool_deferred", f"Tool call deferred: {tool_call.name}", tool=tool_call.name,
                  call_id=call_id, reason=reason, arguments=dict(tool_call.arguments), iteration=iteration)
        return None, Message(
            role="tool", name=tool_call.name,
            content=f"Tool '{tool_call.name}' is waiting for a decision ({reason}); the run pauses here.",
            metadata={"tool_call_id": call_id, "kind": _PLACEHOLDER_KIND},
        )

    def _pause_message(self) -> str:
        record = self._deferred_tool_use or {}
        return f"Paused: {record.get('name', 'a tool call')} is waiting for a decision."

    async def _resume_deferred_call(self, turn: Turn) -> bool:
        """Settle the session's deferred call, if any; ``False`` if it is deferred again."""
        session = turn.existing_session
        record = dict((session.metadata if session else {}).get(DEFERRED_KEY) or {})
        if not record:
            return True
        state = turn.state
        call = ToolCall(name=str(record["name"]), arguments=dict(record.get("input") or {}), id=str(record["id"]))
        context = ToolContext(prompt=turn.user_prompt, system_prompt=turn.base_prompt, metadata=dict(self.metadata),
                              state=turn.shared_state, session_id=self.session_id)
        result, message = await self._execute_single_tool(
            state=state, registry=turn.registry, tool_runner=turn.tool_runner, tool_call=call,
            tool_call_record={"id": call.id}, context=context, iteration=0,
        )
        if self._deferred_tool_use is not None:
            return False
        if result is not None:
            state.tool_results.append(result)
        _replace_placeholder(state.messages, call.id, message)
        return True


def _replace_placeholder(messages: list[Message], call_id: str, message: Message) -> None:
    for index, existing in enumerate(messages):
        if existing.role == "tool" and existing.metadata.get("tool_call_id") == call_id \
                and existing.metadata.get("kind") == _PLACEHOLDER_KIND:
            messages[index] = message
            return
    messages.append(message)
