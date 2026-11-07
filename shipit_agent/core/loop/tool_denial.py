"""Refusing a tool call: the event, the record, and what the model is told.

Mixed into :class:`~shipit_agent.core.async_runtime.AsyncAgentRuntime`;
the methods run on the runtime instance.
"""

from __future__ import annotations

from typing import Any

from shipit_agent.core.models import Message
from shipit_agent.core.state import RuntimeState
from shipit_agent.safety.permissions import PermissionResult

#: Longest string kept whole in a denied call's recorded input.
_DENIAL_VALUE_CHARS = 500


class ToolDenialMixin:
    """Refusing a tool call: the event, the record, and what the model is told."""

    def _deny_tool_call(
        self,
        state: RuntimeState,
        *,
        tool_call: Any,
        call_id: str,
        group_id: str | None,
        decision: PermissionResult,
        iteration: int,
    ) -> tuple[None, Message]:
        """Report a refused (or unapproved) call and build the tool message for it."""
        reason = decision.reason or "not permitted"
        error_kind = "permission_denied" if decision.denied else "permission_required"
        self.emit(
            state,
            "tool_denied",
            f"Tool blocked: {tool_call.name}",
            # Renderers pair outcomes to calls by (tool, call_id); the
            # gate can fire before `tool_called`.
            tool=tool_call.name,
            call_id=call_id,
            group_id=group_id,
            reason=reason,
            decision=decision.decision.value,
            iteration=iteration,
        )
        self._permission_denials.append(
            {
                "tool_name": tool_call.name,
                "tool_use_id": call_id,
                "tool_input": _shortened(tool_call.arguments),
            }
        )
        content = (
            # A denial is FINAL — say so, or the model retries the same call
            # and re-prompts the human on every loop (reference-K.2 style).
            f"Tool '{tool_call.name}' was DENIED and was NOT run "
            f"— {reason}. This decision is final: do NOT retry it, rephrase "
            "it, or pursue the same goal another way. Silence is not consent. "
            "Stop and tell the user the action was declined."
            if decision.denied
            else f"Tool '{tool_call.name}' requires human approval — {reason}"
        )
        msg = Message(
            role="tool",
            name=tool_call.name,
            content=content,
            metadata={
                "tool_call_id": call_id,
                "error": error_kind,
                "decision": decision.decision.value,
            },
        )
        return None, msg


def _shortened(arguments: dict[str, Any]) -> dict[str, Any]:
    """*arguments* with long strings cut, so a denied write does not copy a
    whole file into the run summary and every event that carries it."""
    return {
        key: (
            f"{value[:_DENIAL_VALUE_CHARS]}… [{len(value)} chars]"
            if isinstance(value, str) and len(value) > _DENIAL_VALUE_CHARS
            else value
        )
        for key, value in arguments.items()
    }
