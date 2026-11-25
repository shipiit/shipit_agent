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


# ── a server error with no status: the SDK's mid-stream APIError ─────────────
# Bedrock's OpenAI-compatible (Mantle) endpoint can fail inside a stream that
# opened with 200. The OpenAI SDK raises a bare `APIError` for that — no status,
# only the server's own words — and a Gemma run on DRK CACHE ended on
# "The server had an error while processing your request. Sorry about that!".

def _api_error(message: str, body: object) -> Exception:
    import openai

    return openai.APIError(message, httpx.Request("POST", "https://bedrock-mantle.test/openai/v1/chat/completions"),
                           body=body)


SERVER_SAYS = "The server had an error while processing your request. Sorry about that!"


@pytest.mark.parametrize("error", [
    _api_error(SERVER_SAYS, {"type": "server_error", "code": None}),
    _api_error(SERVER_SAYS, None),
    _api_error("upstream failure", {"type": "server_error"}),
    _api_error("Overloaded", {"type": "overloaded_error"}),
    _api_error("Internal server error", {"type": "api_error"}),
], ids=["body-and-text", "text-only", "body-only", "overloaded", "api-error"])
def test_a_server_error_without_a_status_is_transient(error: Exception) -> None:
    assert is_transient_provider_error(error)


@pytest.mark.parametrize("error", [
    _api_error("Unsupported parameter: 'foo'", {"type": "invalid_request_error"}),
    _api_error("Incorrect API key provided", {"type": "authentication_error"}),
    _api_error("something new", None),
], ids=["bad-request", "auth", "unknown"])
def test_a_refused_or_unknown_api_error_is_not(error: Exception) -> None:
    assert not is_transient_provider_error(error)


@pytest.mark.parametrize("error", [ValueError(SERVER_SAYS), KeyError("Internal server error")],
                         ids=["ValueError", "KeyError"])
def test_server_words_in_a_bug_are_not_a_server_error(error: Exception) -> None:
    assert not is_transient_provider_error(error)


class ServerErrorOnce:
    model = "gemma"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, **_):
        self.calls += 1
        if self.calls == 1:
            raise _api_error(SERVER_SAYS, {"type": "server_error"})
        return LLMResponse(content="recovered")


def test_a_run_survives_a_server_error_without_a_status() -> None:
    llm = ServerErrorOnce()
    result = Agent(llm=llm, auto_use_skills=False,
                   retry_policy=RetryPolicy(llm_retry_base_delay=0, llm_retry_max_delay=0)).run("hi")
    assert result.output == "recovered" and llm.calls == 2
