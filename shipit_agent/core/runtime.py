"""The synchronous face of the agent loop.

There is one loop, :class:`~shipit_agent.core.async_runtime.AsyncAgentRuntime`.
:class:`AgentRuntime` drives it for callers that are not async: :meth:`run`
waits for the result, and :meth:`stream` yields events from a worker thread as
they happen. Everything else (configuration, tools, cancellation, compaction)
is the async runtime's own, reached through this object.
"""

from __future__ import annotations

import asyncio
import contextvars
import queue
import threading
from typing import Any, Coroutine, Iterator, TypeVar

from shipit_agent.core.async_runtime import AsyncAgentRuntime
from shipit_agent.core.models import AgentEvent

# Re-exported: these helpers lived here before the loops were merged, and
# callers import them from this module.
from shipit_agent.core.narration import _join_clauses, _looks_like_prose
from shipit_agent.core.state import (
    RuntimeState,
    _isolated_tool_state,
    _merge_tool_state,
)
from shipit_agent.llms.base import LLMResponse

T = TypeVar("T")


class _StreamDone:
    """Marks the end of a stream's event queue."""

__all__ = [
    "AgentRuntime",
    "RuntimeState",
    "run_sync",
    "_isolated_tool_state",
    "_join_clauses",
    "_looks_like_prose",
    "_merge_tool_state",
]


def run_sync(coroutine: Coroutine[Any, Any, T]) -> T:
    """Run *coroutine* to completion from synchronous code.

    Uses a fresh event loop on this thread when none is running. Inside a
    running loop (a notebook, or sync code called from async code) the loop
    cannot be re-entered, so the coroutine runs on a worker thread with its own
    loop, carrying the caller's context variables across.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)

    outcome: dict[str, Any] = {}

    def _worker() -> None:
        try:
            outcome["value"] = asyncio.run(coroutine)
        except BaseException as error:
            outcome["error"] = error

    worker = threading.Thread(
        target=contextvars.copy_context().run, args=(_worker,), name="shipit-agent-run"
    )
    worker.start()
    worker.join()
    if "error" in outcome:
        raise outcome["error"]
    return outcome["value"]


class AgentRuntime(AsyncAgentRuntime):
    """Run the agent loop from synchronous code.

    The same runtime as :class:`~shipit_agent.core.async_runtime.AsyncAgentRuntime`,
    with the same arguments and settings, except that :meth:`run` and
    :meth:`stream` block instead of awaiting.
    """

    def run(
        self,
        user_prompt: str,
        *,
        user_content: list[dict[str, Any]] | None = None,
    ) -> tuple[RuntimeState, LLMResponse]:
        """Run one turn and return its final state and model response.

        ``user_content`` is the multimodal form of the same turn (text, image
        and document blocks); ``user_prompt`` stays the plain text used for
        guardrails, planning and events.
        """
        return run_sync(self._run_turn(user_prompt, user_content=user_content))

    def stream(
        self,
        user_prompt: str,
        *,
        user_content: list[dict[str, Any]] | None = None,
    ) -> Iterator[AgentEvent]:
        """Run one turn on a worker thread and yield its events as they happen.

        Leaving the loop early cancels the run when ``cancel_on_stream_close``
        is set. The queue is bounded by ``stream_queue_maxsize``.
        """
        loop = self
        events: queue.Queue[AgentEvent | _StreamDone] = queue.Queue(
            maxsize=loop.stream_queue_maxsize
        )
        completed = threading.Event()

        def _put(item: AgentEvent | _StreamDone) -> None:
            while True:
                try:
                    events.put(item, timeout=0.1)
                    return
                except queue.Full:
                    if loop.cancelled:
                        return

        def _subscriber(event: AgentEvent) -> None:
            if not loop.cancelled:
                _put(event)

        def _worker() -> None:
            try:
                asyncio.run(loop._run_turn(user_prompt, user_content=user_content))
            except BaseException as error:
                _put(
                    AgentEvent(
                        type="run_failed",
                        message="Agent run failed",
                        payload={
                            "error_type": type(error).__name__,
                            "error": str(error),
                            "retryable": isinstance(error, ConnectionError),
                        },
                    )
                )
            finally:
                completed.set()
                _put(_StreamDone())

        loop._event_subscriber = _subscriber
        # Caller-owned context variables (tenant, user, tracing) must reach the
        # worker, or run() and stream() would authorise the same call differently.
        worker = threading.Thread(
            target=contextvars.copy_context().run,
            args=(_worker,),
            name="shipit-agent-stream",
            daemon=True,
        )
        worker.start()
        try:
            while True:
                item = events.get()
                if isinstance(item, _StreamDone):
                    break
                yield item
        finally:
            if not completed.is_set() and loop.cancel_on_stream_close:
                loop.cancel()
            worker.join(timeout=loop.stream_join_timeout)
            loop._event_subscriber = None

