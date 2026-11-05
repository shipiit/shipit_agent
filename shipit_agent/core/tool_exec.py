"""Executing one tool call: argument checks, the duplicate and permission gates, approvals, retries, live output and the recorded result.

Mixed into :class:`~shipit_agent.core.async_runtime.AsyncAgentRuntime`;
the methods run on the runtime instance.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable

from shipit_agent.core.models import Message, ToolResult
from shipit_agent.core.registry import ToolRegistry
from shipit_agent.core.runtime_core import (
    _declared_paths,
)
from shipit_agent.core.state import (
    RuntimeState,
)
from shipit_agent.core.tool_runner import ToolRunner, safe_tool_event_metadata
from shipit_agent.tools import ToolContext, ToolOutputChunk


class ToolExecutionMixin:
    """Executing one tool call: argument checks, the duplicate and permission gates, approvals, retries, live output and the recorded result."""

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
        """Mirror of AgentRuntime._defer_tool_call — same shared decision."""
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

        # ── Argument gate ────────────────────────────────────────────────
        # Mirrors runtime.py: repair recoverable argument names, refuse a
        # call whose required arguments are all absent, and say which one is
        # missing so the next step can supply it.
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

        # ── Duplicate-call gate (see the sync runtime for the rationale) ────
        # Skip an exact repeat of a READ-ONLY call already run this turn — the
        # dithering fix. Mutating tools are never suppressed.
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
                # Mirrors runtime.py — renderers pair outcomes to calls by
                # (tool, call_id), and the gate can fire before `tool_called`.
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
        attempt = 0
        output_sequence = 0
        loop = asyncio.get_running_loop()

        def _publish_output(chunk: ToolOutputChunk) -> None:
            nonlocal output_sequence
            output_sequence += 1
            sequence = output_sequence
            attempt_number = attempt + 1

            def _emit_chunk() -> None:
                self.emit(
                    state,
                    "tool_output_delta",
                    f"Tool output: {tool_call.name}",
                    tool=tool_call.name,
                    call_id=tool_call_record["id"],
                    group_id=group_id,
                    chunk=chunk.text,
                    chunk_metadata=safe_tool_event_metadata(chunk.metadata),
                    sequence=sequence,
                    attempt=attempt_number,
                    iteration=iteration,
                )

            loop.call_soon_threadsafe(_emit_chunk)

        while True:
            self.emit(
                state,
                "tool_output_started",
                f"Tool output started: {tool_call.name}",
                tool=tool_call.name,
                call_id=tool_call_record["id"],
                group_id=group_id,
                attempt=attempt + 1,
                buffered=self.guardrails is not None,
                iteration=iteration,
            )
            try:
                tool_result = await self._run_tool_async(
                    tool_runner,
                    tool_call,
                    context,
                    None if self.guardrails is not None else _publish_output,
                )
                break
            except self.retry_policy.retry_on_exceptions as exc:
                if attempt >= self.retry_policy.max_tool_retries:
                    tool_result = ToolResult(
                        name=tool_call.name,
                        output=f"Error running tool '{tool_call.name}': {exc}",
                        is_error=True,
                        metadata={"error": str(exc)},
                    )
                    if self.guardrails is None:
                        _publish_output(
                            ToolOutputChunk(tool_result.output, {"error": str(exc)})
                        )
                        await asyncio.sleep(0)
                    break
                attempt += 1
                self.emit(
                    state,
                    "tool_retry",
                    f"Retrying tool: {tool_call.name}",
                    attempt=attempt,
                    error=str(exc),
                    iteration=iteration,
                )
            except Exception as exc:  # noqa: BLE001 - tools are a fault boundary
                error_output = f"Error running tool '{tool_call.name}': {exc}"
                tool_result = ToolResult(
                    name=tool_call.name,
                    output=error_output,
                    is_error=True,
                    metadata={
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                    },
                )
                if self.guardrails is None:
                    _publish_output(
                        ToolOutputChunk(
                            error_output,
                            {"error": str(exc), "error_type": type(exc).__name__},
                        )
                    )
                    await asyncio.sleep(0)
                break

        if self.hooks:
            tool_result = self.hooks.run_after_tool(tool_call.name, tool_result)

        # Guardrails: neutralize indirect injection and redact secrets BEFORE
        # the model reads the result.
        tool_result.output, redacted_secret = self.sanitize_tool_output(
            state, tool_call.name, tool_result.output
        )
        if self.guardrails is not None and tool_result.output:
            _publish_output(ToolOutputChunk(tool_result.output, {"buffered": True}))
            await asyncio.sleep(0)

        # Did this read latch the run into lockdown?
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
        tool_result.tool_call_id = tool_call_record["id"]
        msg = Message(
            role="tool",
            name=tool_call.name,
            content=model_output,
            tool_call_id=tool_call_record["id"],
            metadata={
                **dict(tool_result.metadata),
            },
        )
        self.remember_tool_call(state, signature, failed=tool_result.is_error)
        if state.verify_gate is not None:
            md = dict(tool_result.metadata or {})
            arguments = getattr(tool_call, "arguments", None) or {}
            state.verify_gate.note_tool(
                read_only=signature is not None,
                paths=[str(path) for path in _declared_paths(md)],
                command=str(md.get("command") or arguments.get("command") or ""),
                exit_code=md.get("exit_code"),
                output=(
                    tool_result.output if isinstance(tool_result.output, str) else ""
                ),
                ok=md.get("ok"),
            )
        terminal_event = "tool_failed" if tool_result.is_error else "tool_completed"
        self.emit(
            state,
            terminal_event,
            f"Tool {'failed' if tool_result.is_error else 'completed'}: {tool_call.name}",
            # Renderers pair an outcome to its call by (tool, call_id); without
            # them this loop's transcript could only guess.
            tool=tool_call.name,
            call_id=tool_call_record["id"],
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
        return tool_result, msg
