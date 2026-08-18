"""Keep one flaky MCP server from dragging down every turn.

An MCP connector is a live dependency — a subprocess or a remote HTTP service —
and any of them can go down, get slow, or start rate-limiting. Without a guard,
a dead server is re-dialled on every step of every turn and each attempt waits
out the full transport timeout before failing, so one broken connector taxes the
whole agent. The transports already surface a failure as a readable tool result;
what is missing is *not trying again so soon*.

This module adds two pieces, composed as a transport wrapper:

* **Circuit breaker** — after a few consecutive failures a server is marked
  *open* and calls to it fail fast (no network wait) until a cooldown elapses.
  The cooldown grows exponentially while the server stays broken and resets the
  moment one call succeeds. A rate-limit (HTTP 429 / JSON-RPC ``-32029``) is
  special-cased to a long, fixed cooldown — hammering a server that just told us
  to slow down is how a soft limit becomes a ban.
* **Bounded retry** — a single transient failure (a subprocess that died, a
  dropped connection) is retried once after a short jittered delay, because the
  persistent transports reconnect on the next call. Rate-limit errors are never
  retried.

``ResilientMCPTransport`` wraps anything with ``.request(method, params)`` /
``.close()`` — the transport Protocol — so it composes with every transport
without changing them. The breaker is per server (per wrapper instance), so one
connector tripping never affects another.

Uses wall-clock (``time.monotonic``) and jitter (``random``): ordinary library
code, not a replay-sensitive workflow script.
"""
from __future__ import annotations

import random
import threading
import time
from typing import Any

from .mcp import MCPError

__all__ = ["CircuitBreaker", "ResilientMCPTransport", "is_rate_limited"]

#: Substrings that mark a rate-limit response across transports. HTTP 429, the
#: JSON-RPC reserved code some servers use, and the common prose forms.
_RATE_LIMIT_MARKERS = (
    "429",
    "-32029",
    "rate limit",
    "rate-limit",
    "too many requests",
    "quota exceeded",
)


def is_rate_limited(exc: BaseException) -> bool:
    """Best-effort: does this error mean 'you are being rate limited'?"""
    text = str(exc).lower()
    return any(marker in text for marker in _RATE_LIMIT_MARKERS)


class CircuitBreaker:
    """Per-server open/closed gate with exponential cooldown.

    Thread-safe: a connector may be called from more than one worker thread.
    """

    def __init__(
        self,
        *,
        fail_threshold: int = 3,
        base_cooldown: float = 2.0,
        max_cooldown: float = 60.0,
        rate_limit_cooldown: float = 300.0,
    ) -> None:
        self.fail_threshold = max(1, fail_threshold)
        self.base_cooldown = base_cooldown
        self.max_cooldown = max_cooldown
        self.rate_limit_cooldown = rate_limit_cooldown
        self._lock = threading.Lock()
        self._consecutive = 0
        self._open_until = 0.0
        self._next_cooldown = base_cooldown

    def allow(self) -> bool:
        """True when a call may proceed (breaker closed or cooldown elapsed)."""
        with self._lock:
            return time.monotonic() >= self._open_until

    def cooldown_remaining(self) -> float:
        with self._lock:
            return max(0.0, self._open_until - time.monotonic())

    def record_success(self) -> None:
        """One good call closes the breaker and resets the backoff."""
        with self._lock:
            self._consecutive = 0
            self._open_until = 0.0
            self._next_cooldown = self.base_cooldown

    def record_failure(self, *, rate_limited: bool = False) -> None:
        with self._lock:
            if rate_limited:
                # A server that said "slow down" gets a long, fixed rest — and
                # trips the breaker immediately rather than after N tries.
                self._open_until = time.monotonic() + self.rate_limit_cooldown
                self._consecutive = self.fail_threshold
                return
            self._consecutive += 1
            if self._consecutive >= self.fail_threshold:
                self._open_until = time.monotonic() + self._next_cooldown
                self._next_cooldown = min(
                    self._next_cooldown * 2, self.max_cooldown
                )


class ResilientMCPTransport:
    """Wrap a transport with a circuit breaker + one bounded retry.

    Transparent: same ``request`` / ``close`` surface, so callers and tools are
    unchanged. When the breaker is open the call fails fast with an
    :class:`~shipit_agent.mcp.MCPError` the tool layer already renders — the
    model is told the server is briefly unavailable instead of the run stalling
    on a timeout.
    """

    def __init__(
        self,
        inner: Any,
        *,
        breaker: CircuitBreaker | None = None,
        max_retries: int = 1,
        base_delay: float = 0.4,
        max_delay: float = 4.0,
        name: str = "",
    ) -> None:
        self._inner = inner
        self.breaker = breaker or CircuitBreaker()
        self.max_retries = max(0, max_retries)
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.name = name or getattr(inner, "name", "") or "mcp"

    def request(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if not self.breaker.allow():
            wait = self.breaker.cooldown_remaining()
            raise MCPError(
                f"MCP server {self.name!r} is temporarily unavailable "
                f"(retry in ~{wait:.0f}s)"
            )
        attempt = 0
        while True:
            try:
                result = self._inner.request(method, params)
                self.breaker.record_success()
                return result
            except (MCPError, OSError, TimeoutError) as exc:
                rate_limited = is_rate_limited(exc)
                # Never retry a rate-limit; back off long and re-raise.
                if rate_limited or attempt >= self.max_retries:
                    self.breaker.record_failure(rate_limited=rate_limited)
                    raise
                attempt += 1
                # Jittered exponential backoff between the bounded retries.
                delay = min(self.base_delay * (2 ** (attempt - 1)), self.max_delay)
                time.sleep(delay + random.uniform(0, self.base_delay))

    def close(self) -> None:
        closer = getattr(self._inner, "close", None)
        if callable(closer):
            closer()

    def __getattr__(self, item: str) -> Any:
        # Transparent wrapper: anything not defined here (a transport's
        # ``endpoint``, ``command``, ``bearer_token``…) reads through to the
        # wrapped transport, so callers and tests that inspect the transport see
        # it unchanged. Only reached for attributes missing on the wrapper, so
        # ``request``/``close``/``breaker`` keep their own behaviour.
        if item == "_inner":
            raise AttributeError(item)  # not yet initialised — avoid recursion
        return getattr(self._inner, item)
