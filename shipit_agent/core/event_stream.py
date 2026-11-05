"""Streaming a turn: run it in the background and yield its events as they happen, cancelling when the caller stops listening.

Mixed into :class:`~shipit_agent.core.async_runtime.AsyncAgentRuntime`;
the methods run on the runtime instance.
"""

from __future__ import annotations

import asyncio
from collections import deque
from typing import Any, AsyncIterator

from shipit_agent.core.models import AgentEvent


class EventStreamMixin:
    """Streaming a turn: run it in the background and yield its events as they happen, cancelling when the caller stops listening."""

    async def stream(
        self,
        user_prompt: str,
        *,
        user_content: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """Run the agent and yield a bounded stream with disconnect cancellation."""
        event_buffer: deque[AgentEvent] = deque()
        wake = asyncio.Event()
        worker_done = False
        provisional_types = {"text_delta", "tool_input_delta", "tool_output_delta"}

        def _subscriber(event: AgentEvent) -> None:
            # Preserve canonical lifecycle events. Under a slow consumer only
            # replace an older delta; run_completed carries the complete text.
            if len(event_buffer) >= self.stream_queue_maxsize:
                drop_index = next(
                    (
                        index
                        for index, queued in enumerate(event_buffer)
                        if queued.type in provisional_types
                    ),
                    None,
                )
                if drop_index is None:
                    self.cancel()
                    return
                del event_buffer[drop_index]
            event_buffer.append(event)
            wake.set()

        self._event_subscriber = _subscriber

        async def _worker() -> None:
            nonlocal worker_done
            try:
                await self._run_turn(user_prompt, user_content=user_content)
            finally:
                worker_done = True
                wake.set()

        task = asyncio.create_task(_worker())
        try:
            while not worker_done or event_buffer:
                if not event_buffer:
                    wake.clear()
                    if worker_done:
                        break
                    await wake.wait()
                    continue
                yield event_buffer.popleft()
        finally:
            self._event_subscriber = None
            if not task.done() and self.cancel_on_stream_close:
                self.cancel()
                task.cancel()
            if task.done() or not self.cancel_on_stream_close:
                await asyncio.gather(task, return_exceptions=True)
            else:
                try:
                    await asyncio.wait_for(
                        asyncio.gather(task, return_exceptions=True),
                        timeout=self.stream_join_timeout,
                    )
                except TimeoutError:
                    task.cancel()
