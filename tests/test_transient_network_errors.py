"""A dropped connection is retried, not the end of the run.

A benchmark run on Bedrock ended with `ReadError: [Errno 54] Connection
reset by peer`: httpx's network errors, and botocore's closed-connection
error, were not seen as transient, because only names ending in
ConnectionError or TimeoutError were. Errors that are bugs, or a bad URL,
must still not be retried.
"""

from __future__ import annotations

import httpx
import pytest

from shipit_agent import Agent
from shipit_agent.core.policies import RetryPolicy
from shipit_agent.llms import LLMResponse
from shipit_agent.llms.throttle import is_transient_provider_error


class ConnectionClosedError(Exception):
    """Stands in for botocore.exceptions.ConnectionClosedError (matched by name)."""


@pytest.mark.parametrize("error", [
    httpx.ReadError("Connection reset by peer"),
    httpx.WriteError("Broken pipe"),
    httpx.ConnectError("refused"),
    httpx.RemoteProtocolError("Server disconnected without sending a response."),
    httpx.ReadTimeout("timed out"),
    ConnectionClosedError("Connection was closed before we received a valid response"),
], ids=lambda e: type(e).__name__)
def test_network_failures_are_transient(error: Exception) -> None:
    assert is_transient_provider_error(error)


@pytest.mark.parametrize("error", [KeyError("choices"), ValueError("bad"), httpx.UnsupportedProtocol("ftp://x")],
                         ids=lambda e: type(e).__name__)
def test_bugs_and_bad_urls_are_not(error: Exception) -> None:
    assert not is_transient_provider_error(error)


class DropsOnce:
    model = "flaky"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, **_):
        self.calls += 1
        if self.calls == 1:
            raise httpx.ReadError("[Errno 54] Connection reset by peer")
        return LLMResponse(content="recovered")


def test_a_run_survives_a_dropped_connection() -> None:
    llm = DropsOnce()
    result = Agent(llm=llm, auto_use_skills=False,
                   retry_policy=RetryPolicy(llm_retry_base_delay=0, llm_retry_max_delay=0)).run("hi")
    assert result.output == "recovered" and llm.calls == 2
    assert any(e.type == "llm_retry" for e in result.events)
