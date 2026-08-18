"""MCP resilience: a dead server fails fast, a rate-limit backs off, one
transient blip retries."""
import pytest

from shipit_agent.mcp import MCPError
from shipit_agent.mcp_resilience import (
    CircuitBreaker,
    ResilientMCPTransport,
    is_rate_limited,
)


class FakeTransport:
    """Records calls; raises a scripted sequence of errors then succeeds."""

    def __init__(self, script=None):
        self.script = list(script or [])
        self.calls = 0
        self.closed = False

    def request(self, method, params=None):
        self.calls += 1
        if self.script:
            exc = self.script.pop(0)
            if exc is not None:
                raise exc
        return {"ok": True, "method": method}

    def close(self):
        self.closed = True


# ── circuit breaker ──────────────────────────────────────────────────────

def test_breaker_opens_after_threshold_failures():
    cb = CircuitBreaker(fail_threshold=3)
    assert cb.allow()
    for _ in range(2):
        cb.record_failure()
    assert cb.allow()  # not yet
    cb.record_failure()  # third
    assert not cb.allow()
    assert cb.cooldown_remaining() > 0


def test_success_closes_the_breaker():
    cb = CircuitBreaker(fail_threshold=2, base_cooldown=100)
    cb.record_failure()
    cb.record_failure()
    assert not cb.allow()
    cb.record_success()
    assert cb.allow()
    assert cb.cooldown_remaining() == 0


def test_rate_limit_trips_immediately_with_long_cooldown():
    cb = CircuitBreaker(fail_threshold=5, rate_limit_cooldown=300)
    cb.record_failure(rate_limited=True)  # single hit, not 5
    assert not cb.allow()
    assert cb.cooldown_remaining() > 100  # the long rest, not the base


def test_cooldown_grows_exponentially():
    cb = CircuitBreaker(fail_threshold=1, base_cooldown=2, max_cooldown=60)
    cb.record_failure()
    first = cb.cooldown_remaining()
    cb.record_failure()
    second = cb.cooldown_remaining()
    assert second > first  # 2s → 4s


# ── is_rate_limited ──────────────────────────────────────────────────────

@pytest.mark.parametrize("msg", [
    "HTTP 429 Too Many Requests",
    "error -32029",
    "Rate limit exceeded, slow down",
    "quota exceeded for today",
])
def test_detects_rate_limit(msg):
    assert is_rate_limited(MCPError(msg))


def test_ordinary_error_is_not_rate_limited():
    assert not is_rate_limited(MCPError("connection refused"))


# ── wrapper ──────────────────────────────────────────────────────────────

def test_passes_through_on_success():
    t = ResilientMCPTransport(FakeTransport(), name="s")
    assert t.request("tools/list")["ok"] is True


def test_fails_fast_when_breaker_open_without_calling_inner():
    inner = FakeTransport()
    cb = CircuitBreaker(fail_threshold=1)
    cb.record_failure()  # open it
    t = ResilientMCPTransport(inner, breaker=cb, name="s")
    with pytest.raises(MCPError, match="temporarily unavailable"):
        t.request("tools/list")
    assert inner.calls == 0  # never hit the network


def test_retries_one_transient_failure_then_succeeds():
    inner = FakeTransport(script=[MCPError("subprocess died"), None])
    t = ResilientMCPTransport(inner, max_retries=1, base_delay=0, name="s")
    assert t.request("tools/call")["ok"] is True
    assert inner.calls == 2  # failed once, retried, succeeded


def test_never_retries_a_rate_limit():
    inner = FakeTransport(script=[MCPError("429 too many requests"), None])
    cb = CircuitBreaker(fail_threshold=5)
    t = ResilientMCPTransport(inner, breaker=cb, max_retries=3, base_delay=0, name="s")
    with pytest.raises(MCPError, match="429"):
        t.request("tools/call")
    assert inner.calls == 1  # no retry
    assert not cb.allow()  # and it tripped the breaker at once


def test_close_delegates():
    inner = FakeTransport()
    ResilientMCPTransport(inner).close()
    assert inner.closed
