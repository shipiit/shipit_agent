"""LLM retry backoff, jitter, and per-request timeout passthrough."""

from __future__ import annotations

import asyncio
import time

from shipit_agent.async_runtime import AsyncAgentRuntime
from shipit_agent.llms.base import LLMResponse
from shipit_agent.policies import RetryPolicy
from shipit_agent.runtime import AgentRuntime


class FlakyLLM:
    def __init__(self, failures: int):
        self.failures = failures
        self.calls = 0

    def complete(self, *, messages, tools=None, system_prompt=None, metadata=None):
        self.calls += 1
        if self.calls <= self.failures:
            raise ConnectionError("boom")
        return LLMResponse(content="recovered")


class TimeoutRecordingLLM:
    def __init__(self):
        self.timeouts: list = []

    def complete(
        self,
        *,
        messages,
        tools=None,
        system_prompt=None,
        metadata=None,
        timeout=None,
    ):
        self.timeouts.append(timeout)
        return LLMResponse(content="ok")


class NoTimeoutParamLLM:
    """An older adapter shape — must never be sent a timeout kwarg."""

    def complete(self, *, messages, tools=None, system_prompt=None, metadata=None):
        return LLMResponse(content="ok")


def test_retry_policy_backoff_is_exponential_and_capped():
    policy = RetryPolicy(
        llm_retry_base_delay=1.0, llm_retry_max_delay=3.0, llm_retry_jitter=False
    )
    assert policy.llm_retry_delay(1) == 1.0
    assert policy.llm_retry_delay(2) == 2.0
    assert policy.llm_retry_delay(3) == 3.0  # capped
    assert RetryPolicy(llm_retry_base_delay=0).llm_retry_delay(1) == 0.0


def test_sync_retry_sleeps_with_backoff(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))

    llm = FlakyLLM(failures=2)
    runtime = AgentRuntime(
        llm=llm,
        prompt="You are helpful.",
        max_iterations=2,
        retry_policy=RetryPolicy(
            max_llm_retries=2,
            llm_retry_base_delay=0.05,
            llm_retry_jitter=False,
        ),
    )
    state, response = runtime.run("hello")
    assert response.content == "recovered"
    assert llm.calls == 3
    assert sleeps == [0.05, 0.10]
    retries = [e for e in state.events if e.type == "llm_retry"]
    assert [e.payload["delay"] for e in retries] == [0.05, 0.10]


def test_sync_retry_exhaustion_raises(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)
    llm = FlakyLLM(failures=10)
    runtime = AgentRuntime(
        llm=llm,
        prompt="You are helpful.",
        max_iterations=2,
        retry_policy=RetryPolicy(max_llm_retries=1, llm_retry_base_delay=0),
    )
    try:
        runtime.run("hello")
        raise AssertionError("expected ConnectionError")
    except ConnectionError:
        pass
    assert llm.calls == 2  # initial + one retry


def test_async_retry_sleeps_with_backoff(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    llm = FlakyLLM(failures=1)
    runtime = AsyncAgentRuntime(
        llm=llm,
        prompt="You are helpful.",
        max_iterations=2,
        retry_policy=RetryPolicy(
            max_llm_retries=2,
            llm_retry_base_delay=0.05,
            llm_retry_jitter=False,
        ),
    )
    state, response = asyncio.run(runtime.run("hello"))
    assert response.content == "recovered"
    assert sleeps == [0.05]


def test_request_timeout_forwarded_when_adapter_accepts_it():
    llm = TimeoutRecordingLLM()
    runtime = AgentRuntime(
        llm=llm,
        prompt="You are helpful.",
        max_iterations=1,
        retry_policy=RetryPolicy(request_timeout=42.5),
    )
    runtime.run("hello")
    assert llm.timeouts == [42.5]


def test_request_timeout_skipped_for_older_adapters():
    llm = NoTimeoutParamLLM()
    runtime = AgentRuntime(
        llm=llm,
        prompt="You are helpful.",
        max_iterations=1,
        retry_policy=RetryPolicy(request_timeout=42.5),
    )
    state, response = runtime.run("hello")  # must not raise TypeError
    assert response.content == "ok"


def test_async_request_timeout_forwarded():
    llm = TimeoutRecordingLLM()
    runtime = AsyncAgentRuntime(
        llm=llm,
        prompt="You are helpful.",
        max_iterations=1,
        retry_policy=RetryPolicy(request_timeout=7.0),
    )
    asyncio.run(runtime.run("hello"))
    assert llm.timeouts == [7.0]
