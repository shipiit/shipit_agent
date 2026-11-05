"""Executing one tool call: the registry, argument, duplicate and permission gates.

A call that passes runs in :mod:`.tool_attempts` and is recorded in
:mod:`.tool_outcome`.

Mixed into :class:`~shipit_agent.core.async_runtime.AsyncAgentRuntime`;
the methods run on the runtime instance.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable

from shipit_agent.core.loop.tool_attempts import LiveToolOutput
from shipit_agent.core.models import Message, ToolResult
from shipit_agent.core.registry import ToolRegistry
from shipit_agent.core.state import (
    RuntimeState,
)
from shipit_agent.core.tool_runner import ToolRunner
from shipit_agent.tools import ToolContext, ToolOutputChunk


class ToolExecutionMixin:
    """Executing one tool call: the registry, argument, duplicate and permission gates."""

    async def _run_tool_async(
        self,
        tool_runner: ToolRunner,
        tool_call: Any,
        context: ToolContext,
        output_callback: Callable[[ToolOutputChunk], None] | None = None,
    ) -> ToolResult:
        """Run native async tools directly and sync tools in a context-aware thread."""
        result = await tool_runner.run_tool_call_async(
            tool_call, context, output_callback
        )
        # Thread-safe output callbacks are queued onto this event loop. Let
        # them drain before the canonical tool_completed event is emitted.
        await asyncio.sleep(0)
        return result

    def _defer_tool_call(
        self,
        *,
        state: RuntimeState,
        tool: Any,
        tool_call: Any,
        tool_call_record: dict[str, Any],
        context: ToolContext,
        iteration: int,
    ) -> tuple[ToolResult | None, Message] | None:
        """Queue *tool_call* for approval when the approval queue wants it.

        Returns ``None`` when the call should run now, or the result and tool
        message to record when it was queued (or auto-applied).
        """
        from shipit_agent.approvals.gate import defer_tool_call

        deferred_call = tool_call
        runner = ToolRunner(self.registry())

        def _apply() -> ToolResult:
            return runner.run_tool_call(deferred_call, context)

        outcome = defer_tool_call(
            approvals=self.approvals,
            tool=tool,
            tool_call=tool_call,
            call_id=tool_call_record["id"],
            apply_fn=_apply,
        )
        if not outcome.handled:
            return None

        action = outcome.action
        if outcome.result is not None:
            outcome.message.content = self.model_visible_tool_output(outcome.result)
        self.emit(
            state,
            "tool_completed" if outcome.applied else "action_queued",
            f"{'Applied' if outcome.applied else 'Queued for approval'}: {tool_call.name}",
            tool=tool_call.name,
            call_id=tool_call_record["id"],
            action_id=action.id,
            title=action.title,
            tag=action.tag,
            auto_approved=action.auto_approved,
            iteration=iteration,
        )
        return outcome.result, outcome.message

    async def _execute_single_tool(
        self,
        *,
        state: RuntimeState,
        registry: ToolRegistry,
        tool_runner: ToolRunner,
        tool_call: Any,
        tool_call_record: dict[str, Any],
        context: ToolContext,
        iteration: int,
        model_output_limit: int | None = None,
        group_id: str | None = None,
    ) -> tuple[ToolResult | None, Message]:
        # Defined up front so the recording line below can never NameError on an
        # early-return path that skipped the duplicate gate.
        signature: tuple[str, str] | None = None
        tool = registry.get(tool_call.name)
        if tool is None:
            error_output = (
                f"Error: tool '{tool_call.name}' is not registered. "
                f"Choose a different tool from the available list."
            )
            self.emit(
                state,
                "tool_failed",
                f"Tool failed: {tool_call.name}",
                error="tool_not_registered",
                iteration=iteration,
            )
            msg = Message(
                role="tool",
                name=tool_call.name,
                content=error_output,
                metadata={
                    "tool_call_id": tool_call_record["id"],
                    "error": "tool_not_registered",
                },
            )
            return None, msg

        refusal = self.refuse_withheld_call(
            state, context.state, tool_call, tool_call_record, iteration=iteration
        )
        if refusal is not None:
            return None, refusal

        # ── Argument gate ────────────────────────────────────────────────
        # Repair recoverable argument names; refuse a call missing required
        # arguments, naming the one the next step must supply.
        argument_error = self.check_arguments(tool, tool_call)
        if argument_error:
            self.emit(
                state,
                "tool_arguments_rejected",
                f"Tool call missing arguments: {tool_call.name}",
                tool=tool_call.name,
                arguments=dict(tool_call.arguments or {}),
                iteration=iteration,
            )
            return None, Message(
                role="tool",
                name=tool_call.name,
                content=argument_error,
                metadata={
                    "tool_call_id": tool_call_record["id"],
                    "error": "missing_required_arguments",
                },
            )

        # ── Duplicate-call gate: skip an exact repeat of a READ-ONLY call
        # already run this turn. Mutating tools are never suppressed here.
        signature = self.readonly_call_signature(tool, tool_call)
        if signature is not None and signature in state.executed_readonly_calls:
            self.emit(
                state,
                "tool_skipped_duplicate",
                f"Skipped repeat call: {tool_call.name}",
                tool=tool_call.name,
                iteration=iteration,
            )
            note = (
                f"[Already ran: {tool_call.name} was called with these exact "
                f"arguments earlier in this turn. Its result is already above "
                f"in this conversation — reuse it. This call was NOT run again. "
                f"Do not repeat it; answer from the result you have, or call "
                f"{tool_call.name} with different arguments.]"
            )
            return None, Message(
                role="tool",
                name=tool_call.name,
                content=note,
                metadata={
                    "tool_call_id": tool_call_record["id"],
                    "duplicate_suppressed": True,
                },
            )

        # ── Permission gate: blocking hooks + rule-based permission engine ──
        decision = self.authorize(tool_call.name, tool_call.arguments, tool)
        if (
            decision is not None
            and decision.needs_approval
            and getattr(self, "approvals", None) is not None
        ):
            queued = self._defer_tool_call(
                state=state,
                tool=tool,
                tool_call=tool_call,
                tool_call_record=tool_call_record,
                context=context,
                iteration=iteration,
            )
            if queued is not None:
                return queued

        if decision is not None and not decision.allowed:
            reason = decision.reason or "not permitted"
            error_kind = (
                "permission_denied" if decision.denied else "permission_required"
            )
            self.emit(
                state,
                "tool_denied",
                f"Tool blocked: {tool_call.name}",
                # Renderers pair outcomes to calls by (tool, call_id); the
                # gate can fire before `tool_called`.
                tool=tool_call.name,
                call_id=tool_call_record["id"],
                group_id=group_id,
                reason=reason,
                decision=decision.decision.value,
                iteration=iteration,
            )
            content = (
                # A denial is FINAL — say so, or the model retries the same call
                # and re-prompts the human on every loop (reference-K.2 style).
                f"Tool '{tool_call.name}' was DENIED by a human and was NOT run "
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
                    "tool_call_id": tool_call_record["id"],
                    "error": error_kind,
                    "decision": decision.decision.value,
                },
            )
            return None, msg
        if decision is not None and decision.updated_arguments is not None:
            tool_call = type(
                "RewrittenToolCall",
                (),
                {
                    "name": tool_call.name,
                    "arguments": dict(decision.updated_arguments),
                },
            )()

        self.emit(
            state,
            "tool_called",
            f"Tool called: {tool_call.name}",
            tool=tool_call.name,
            call_id=tool_call_record["id"],
            group_id=group_id,
            arguments=tool_call.arguments,
            iteration=iteration,
        )
        started_at = time.perf_counter()
        call_id = tool_call_record["id"]
        live = LiveToolOutput(
            self,
            state,
            tool_call=tool_call,
            call_id=call_id,
            group_id=group_id,
            iteration=iteration,
        )
        tool_result = await self._attempt_tool_call(
            state=state,
            tool_runner=tool_runner,
            tool_call=tool_call,
            context=context,
            iteration=iteration,
            call_id=call_id,
            group_id=group_id,
            live=live,
        )
        return await self._record_tool_outcome(
            state=state,
            tool_call=tool_call,
            tool_result=tool_result,
            iteration=iteration,
            call_id=call_id,
            group_id=group_id,
            live=live,
            signature=signature,
            started_at=started_at,
            model_output_limit=model_output_limit,
        )
