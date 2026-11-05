"""Recording a tool call's result: checks, what the model sees, and the events.

Mixed into :class:`~shipit_agent.core.async_runtime.AsyncAgentRuntime`;
the methods run on the runtime instance.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from shipit_agent.core.decisions.artifact_paths import _declared_paths
from shipit_agent.core.loop.tool_attempts import LiveToolOutput
from shipit_agent.core.models import Message, ToolResult
from shipit_agent.core.state import RuntimeState
from shipit_agent.core.tool_runner import safe_tool_event_metadata
from shipit_agent.tools import ToolOutputChunk


class ToolOutcomeMixin:
    """Recording a tool call's result: checks, what the model sees, and the events."""

    async def _record_tool_outcome(
        self,
        *,
        state: RuntimeState,
        tool_call: Any,
        tool_result: ToolResult,
        iteration: int,
        call_id: str,
        group_id: str | None,
        live: LiveToolOutput,
        signature: tuple[str, str] | None,
        started_at: float,
        model_output_limit: int | None,
    ) -> tuple[ToolResult, Message]:
        """Check *tool_result*, turn it into the tool message, and report it.

        After-tool hooks run first, then guardrails, which neutralise indirect
        prompt injection and redact secrets before the model reads anything.
        """
        if self.hooks:
            tool_result = self.hooks.run_after_tool(tool_call.name, tool_result)
            if tool_result.is_error:
                note = self.hooks.run_post_tool_failure(
                    tool_call.name, dict(tool_call.arguments), str(tool_result.output)
                )
                if note:
                    tool_result.output = f"{tool_result.output}\n\n{note}"

        tool_result.output, redacted_secret = self.sanitize_tool_output(
            state, tool_call.name, tool_result.output
        )
        if self.guardrails is not None and tool_result.output:
            # Output was buffered while the tool ran; release it now it is checked.
            live.publish(ToolOutputChunk(tool_result.output, {"buffered": True}))
            await asyncio.sleep(0)

        self.note_lockdown(
            state,
            tool=tool_call.name,
            arguments=dict(tool_call.arguments),
            output_metadata=dict(tool_result.metadata),
            redacted_secret=redacted_secret,
            iteration=iteration,
        )

        model_output = self.model_visible_tool_output(
            tool_result,
            arguments=tool_call.arguments,
            seen=state.seen_tool_outputs,
            limit_override=model_output_limit,
        )
        tool_result.tool_call_id = call_id
        message = Message(
            role="tool",
            name=tool_call.name,
            content=model_output,
            tool_call_id=call_id,
            metadata=dict(tool_result.metadata),
        )
        self.remember_tool_call(state, signature, failed=tool_result.is_error)
        if state.verify_gate is not None:
            metadata = dict(tool_result.metadata or {})
            arguments = getattr(tool_call, "arguments", None) or {}
            state.verify_gate.note_tool(
                read_only=signature is not None,
                paths=[str(path) for path in _declared_paths(metadata)],
                command=str(metadata.get("command") or arguments.get("command") or ""),
                exit_code=metadata.get("exit_code"),
                output=(
                    tool_result.output if isinstance(tool_result.output, str) else ""
                ),
                ok=metadata.get("ok"),
            )

        self.emit(
            state,
            "tool_failed" if tool_result.is_error else "tool_completed",
            f"Tool {'failed' if tool_result.is_error else 'completed'}: {tool_call.name}",
            # Renderers pair an outcome to its call by (tool, call_id).
            tool=tool_call.name,
            call_id=call_id,
            group_id=group_id,
            output=tool_result.output,
            output_chars=len(tool_result.output),
            model_output_chars=len(model_output),
            model_output_reduced=model_output != tool_result.output,
            metadata=safe_tool_event_metadata(tool_result.metadata),
            error=(
                str(tool_result.metadata.get("error") or "")
                if tool_result.is_error
                else ""
            ),
            iteration=iteration,
            duration_ms=round((time.perf_counter() - started_at) * 1000, 1),
        )
        self.note_connection_request(state, tool_call.name, tool_result.metadata)
        self.note_artifacts(state, tool_call.name, tool_result)
        if tool_result.metadata.get("interactive"):
            self.emit(
                state,
                "interactive_request",
                f"Interactive request from {tool_call.name}",
                kind=tool_result.metadata.get("kind"),
                payload=dict(tool_result.metadata),
            )
        return tool_result, message
