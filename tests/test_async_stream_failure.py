"""A run that fails ends the async stream with run_failed, as the sync stream does.

It used to stop silently after step_started: the worker's exception was
gathered with return_exceptions=True and dropped.
"""

from __future__ import annotations

import asyncio
from typing import Any

from shipit_agent import Agent
from shipit_agent.core.policies import RetryPolicy
from shipit_agent.llms.base import LLMResponse

NO_RETRIES = RetryPolicy(llm_retry_base_delay=0, max_llm_retries=0)


class _Down:
    model = "claude-sonnet-5-5"

    def complete(self, **_: Any) -> LLMResponse:
        raise PermissionError("bad key")


def _async_events() -> list[Any]:
    async def run() -> list[Any]:
        return [event async for event in Agent(llm=_Down(), retry_policy=NO_RETRIES).astream("hi")]

    return asyncio.run(run())


def test_the_async_stream_ends_with_run_failed() -> None:
    last = _async_events()[-1]
    assert last.type == "run_failed"
    assert last.payload["error_type"] == "PermissionError"
    assert last.payload["error"] == "bad key"


def test_the_sync_and_async_streams_report_a_failure_the_same_way() -> None:
    sync_last = list(Agent(llm=_Down(), retry_policy=NO_RETRIES).stream("hi"))[-1]
    async_last = _async_events()[-1]
    assert (sync_last.type, sync_last.payload["error_type"]) == (async_last.type, async_last.payload["error_type"])


def test_a_successful_async_stream_has_no_failure_event() -> None:
    class _Fine:
        model = "claude-sonnet-5-5"

        def complete(self, **_: Any) -> LLMResponse:
            return LLMResponse(content="ok")

    async def run() -> list[str]:
        return [event.type async for event in Agent(llm=_Fine()).astream("hi")]

    types = asyncio.run(run())
    assert types[-1] == "run_completed" and "run_failed" not in types
