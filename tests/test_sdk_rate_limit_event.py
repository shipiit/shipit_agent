"""``RateLimitEvent``: the run hit a rate limit and waited it out."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from shipit_agent.core.policies import RetryPolicy
from shipit_agent.llms.base import LLMResponse
from shipit_agent.sdk import AgentOptions, RateLimitEvent, ResultMessage, SystemMessage, query


class _Status(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status


class _FailsOnce:
    model = "claude-sonnet-5-5"

    def __init__(self, error: Exception) -> None:
        self.error, self.calls = error, 0

    def complete(self, **_: Any) -> LLMResponse:
        self.calls += 1
        if self.calls == 1:
            raise self.error
        return LLMResponse(content="done")


def _run(error: Exception, delay: float = 0.0) -> list[Any]:
    policy = RetryPolicy(llm_retry_base_delay=delay, llm_retry_max_delay=delay, max_llm_retries=1,
                         retry_on_exceptions=(Exception,))
    options = AgentOptions(llm=_FailsOnce(error), tools=[], agent_options={"retry_policy": policy})

    async def go() -> list[Any]:
        return [message async for message in query(prompt="go", options=options)]

    return asyncio.run(go())


def test_a_429_becomes_a_rejected_rate_limit_event_before_the_retry() -> None:
    messages = _run(_Status(429, "Too many requests"), delay=0.01)
    events = [m for m in messages if isinstance(m, RateLimitEvent)]
    assert len(events) == 1
    info = events[0].rate_limit_info
    assert info["status"] == "rejected" and info["rate_limit_type"] is None and info["utilization"] is None
    assert isinstance(info["resets_at"], int) and info["resets_at"] > 0
    assert info["raw"]["reason"] == "token_quota"
    assert events[0].uuid and events[0].session_id == messages[-1].session_id
    # The retry is still reported as one, and the run still succeeds.
    assert any(isinstance(m, SystemMessage) and m.subtype == "api_retry" for m in messages)
    assert isinstance(messages[-1], ResultMessage) and messages[-1].subtype == "success"


def test_without_a_wait_there_is_no_reset_time() -> None:
    info = next(m for m in _run(_Status(429, "Too many requests")) if isinstance(m, RateLimitEvent)).rate_limit_info
    assert info["resets_at"] is None


@pytest.mark.parametrize(
    "error",
    [_Status(529, "Overloaded"), _Status(503, "Service unavailable"), _Status(500, "Internal error"), ConnectionError("reset")],
)
def test_overload_server_and_network_errors_are_not_rate_limits(error: Exception) -> None:
    messages = _run(error)
    assert not any(isinstance(m, RateLimitEvent) for m in messages)
    assert any(isinstance(m, SystemMessage) and m.subtype == "api_retry" for m in messages)
