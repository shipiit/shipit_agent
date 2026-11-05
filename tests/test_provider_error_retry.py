"""Provider errors: retry rate limits, overloads and server errors; never bad requests.

A 429 or 529 from a provider is the most common way a long run dies. They are
retried with backoff (honouring ``Retry-After``); a malformed request is not,
because sending it again cannot succeed.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from shipit_agent.core.policies import RetryPolicy
from shipit_agent.core.runtime import AgentRuntime
from shipit_agent.llms.base import LLMResponse
from shipit_agent.llms.throttle import ThrottleKind, classify, retry_after_seconds


class _Response:
    def __init__(self, status_code: int, headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self.headers = headers or {}


class APIStatusError(Exception):
    """Shaped like the Anthropic and OpenAI SDK errors: a status and a response."""

    def __init__(self, status_code: int, headers: dict[str, str] | None = None) -> None:
        super().__init__(f"Error code: {status_code}")
        self.status_code = status_code
        self.response = _Response(status_code, headers)


class APIConnectionError(Exception):
    """Shaped like ``anthropic.APIConnectionError``: no status, not a ConnectionError."""


class _FailingLLM:
    def __init__(self, *errors: Exception) -> None:
        self.errors = list(errors)
        self.calls = 0

    def complete(self, **_: Any) -> LLMResponse:
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return LLMResponse(content="recovered")


def _run(llm: _FailingLLM, **policy: Any) -> tuple[Any, LLMResponse]:
    options = {"max_llm_retries": 3, "llm_retry_base_delay": 0} | policy
    runtime = AgentRuntime(
        llm=llm,
        prompt="You help.",
        max_iterations=2,
        retry_policy=RetryPolicy(**options),
    )
    return runtime.run("go")


@pytest.mark.parametrize("status", [408, 409, 429, 500, 502, 503, 529])
def test_retryable_statuses_are_retried(status: int) -> None:
    llm = _FailingLLM(APIStatusError(status))
    state, response = _run(llm)
    assert response.content == "recovered"
    assert llm.calls == 2
    retries = [e for e in state.events if e.type == "llm_retry"]
    assert len(retries) == 1 and retries[0].payload["attempt"] == 1


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_request_errors_are_raised_without_a_retry(status: int) -> None:
    llm = _FailingLLM(APIStatusError(status))
    with pytest.raises(APIStatusError):
        _run(llm)
    assert llm.calls == 1


def test_an_sdk_connection_error_is_retried() -> None:
    llm = _FailingLLM(APIConnectionError("Connection error."))
    _, response = _run(llm)
    assert response.content == "recovered"


def test_a_programming_error_is_not_retried() -> None:
    llm = _FailingLLM(KeyError("missing"))
    with pytest.raises(KeyError):
        _run(llm)
    assert llm.calls == 1


def test_the_last_error_is_raised_when_retries_run_out() -> None:
    llm = _FailingLLM(*(APIStatusError(529) for _ in range(5)))
    with pytest.raises(APIStatusError):
        _run(llm, max_llm_retries=2)
    assert llm.calls == 3


def test_retry_after_is_honoured(monkeypatch) -> None:
    sleeps: list[float] = []
    real_sleep = asyncio.sleep

    async def record(seconds: float) -> None:
        sleeps.append(seconds)
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", record)
    llm = _FailingLLM(APIStatusError(429, {"retry-after": "7"}))
    _run(llm, llm_retry_base_delay=0.1, llm_retry_jitter=False)
    assert 7.0 in sleeps


class TestClassification:
    def test_overloaded_is_capacity(self) -> None:
        assert classify(APIStatusError(529)) is ThrottleKind.CAPACITY

    @pytest.mark.parametrize("status", [408, 409])
    def test_timeouts_and_conflicts_are_transient(self, status: int) -> None:
        assert classify(APIStatusError(status)) is ThrottleKind.TRANSIENT


class TestRetryAfter:
    def test_seconds(self) -> None:
        assert retry_after_seconds(APIStatusError(429, {"retry-after": "2.5"})) == 2.5

    def test_milliseconds_win_when_present(self) -> None:
        error = APIStatusError(429, {"retry-after-ms": "1500", "retry-after": "9"})
        assert retry_after_seconds(error) == 1.5

    @pytest.mark.parametrize(
        "headers",
        [{}, {"retry-after": "soon"}, {"retry-after": "-3"}, {"retry-after": ""}],
    )
    def test_absent_or_unusable(self, headers: dict[str, str]) -> None:
        assert retry_after_seconds(APIStatusError(429, headers)) is None

    def test_an_error_without_a_response(self) -> None:
        assert retry_after_seconds(RuntimeError("429")) is None
