"""Running a tool call that passed its gates: live output and retries.

Mixed into :class:`~shipit_agent.core.async_runtime.AsyncAgentRuntime`;
the methods run on the runtime instance.
"""

from __future__ import annotations

import asyncio
from typing import Any

from shipit_agent.core.models import ToolResult
from shipit_agent.core.state import RuntimeState
from shipit_agent.core.tool_runner import ToolRunner, safe_tool_event_metadata
from shipit_agent.tools import ToolContext, ToolOutputChunk


class LiveToolOutput:
    """Forward one tool call's output chunks to the event stream as they arrive.

    Tools may run on a worker thread, so each chunk is handed back to the
    event loop and emitted there. Chunks are numbered per call, and carry the
    attempt that produced them, so a renderer can drop a failed attempt's
    output when a retry starts.
    """

    def __init__(
        self,
        runtime: Any,
        state: RuntimeState,
        *,
        tool_call: Any,
        call_id: str,
        group_id: str | None,
        iteration: int,
    ) -> None:
        self._runtime = runtime
        self._state = state
        self._tool_call = tool_call
        self._call_id = call_id
        self._group_id = group_id
        self._iteration = iteration
        self._loop = asyncio.get_running_loop()
        self._sequence = 0
        #: Zero-based attempt number; the retry loop advances it.
        self.attempt = 0

    def publish(self, chunk: ToolOutputChunk) -> None:
        """Emit *chunk* as a ``tool_output_delta`` event. Safe from any thread."""
        self._sequence += 1
        sequence = self._sequence
        attempt_number = self.attempt + 1

        def _emit_chunk() -> None:
            self._runtime.emit(
                self._state,
                "tool_output_delta",
                f"Tool output: {self._tool_call.name}",
                tool=self._tool_call.name,
                call_id=self._call_id,
                group_id=self._group_id,
                chunk=chunk.text,
                chunk_metadata=safe_tool_event_metadata(chunk.metadata),
                sequence=sequence,
                attempt=attempt_number,
                iteration=self._iteration,
            )

        self._loop.call_soon_threadsafe(_emit_chunk)


class ToolAttemptsMixin:
    """Running a tool call that passed its gates: live output and retries."""

    async def _attempt_tool_call(
        self,
        *,
        state: RuntimeState,
        tool_runner: ToolRunner,
        tool_call: Any,
        context: ToolContext,
        iteration: int,
        call_id: str,
        group_id: str | None,
        live: LiveToolOutput,
    ) -> ToolResult:
        """Run *tool_call*, retrying the failures the retry policy names.

        Never raises for a tool's own failure: the result comes back marked
        as an error, so the model can read what went wrong and adapt. With
        guardrails on, output is buffered until it has been checked, so
        nothing unchecked reaches the stream.
        """
        stream_live = self.guardrails is None
        while True:
            self.emit(
                state,
                "tool_output_started",
                f"Tool output started: {tool_call.name}",
                tool=tool_call.name,
                call_id=call_id,
                group_id=group_id,
                attempt=live.attempt + 1,
                buffered=not stream_live,
                iteration=iteration,
            )
            try:
                return await self._run_tool_async(
                    tool_runner,
                    tool_call,
                    context,
                    live.publish if stream_live else None,
                )
            except self.retry_policy.retry_on_exceptions as exc:
                if live.attempt >= self.retry_policy.max_tool_retries:
                    error_output = f"Error running tool '{tool_call.name}': {exc}"
                    error_metadata = {"error": str(exc)}
                    break
                live.attempt += 1
                self.emit(
                    state,
                    "tool_retry",
                    f"Retrying tool: {tool_call.name}",
                    attempt=live.attempt,
                    error=str(exc),
                    iteration=iteration,
                )
            # A tool is a fault boundary: whatever it raises becomes a result
            # the model can read, never a crashed run.
            except Exception as exc:
                error_output = f"Error running tool '{tool_call.name}': {exc}"
                error_metadata = {"error": str(exc), "error_type": type(exc).__name__}
                break

        if stream_live:
            live.publish(ToolOutputChunk(error_output, dict(error_metadata)))
            await asyncio.sleep(0)
        return ToolResult(
            name=tool_call.name,
            output=error_output,
            is_error=True,
            metadata=error_metadata,
        )
