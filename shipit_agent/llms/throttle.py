"""Telling apart the failures that need different responses.

A retry loop that treats every non-2xx the same is worse than no retry loop.
On the ``bedrock-mantle`` endpoint the two throttling responses mean opposite
things:

* **429** — a token-per-minute quota was exceeded. Retrying quickly makes it
  worse; the fix is a lower submission rate or a quota increase.
* **503** — regional capacity is under pressure. Occasional ones should be
  retried with backoff and jitter; sustained ones mean the request rate is
  above available capacity and needs to be reduced and ramped back up.

And two more the loop must not lump in:

* **401/403** — a derived bearer token expired or was revoked mid-run. Exactly
  one refresh-and-retry is correct; retrying without refreshing is pointless,
  and giving up loses a run to a token that is trivially renewable.
* **400** — the request is malformed. Retrying an unchanged malformed request
  is guaranteed to fail again, and hides the real cause behind N attempts.

Classification works on status codes when present and falls back to matching
the message, because SDKs differ about where they put the status. The kinds are
deliberately coarse: each one exists because it demands a *different action*.
"""

from __future__ import annotations

import logging
import random
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "ThrottleKind",
    "BackoffPolicy",
    "RetrySchedule",
    "classify",
    "DEFAULT_SCHEDULE",
]


class ThrottleKind(Enum):
    """Why a call failed, in terms of what to do about it."""

    TOKEN_QUOTA = "token_quota"       # 429 — slow down
    CAPACITY = "capacity"             # 503 — back off, maybe ramp
    AUTH = "auth"                     # 401/403 — refresh once
    BAD_REQUEST = "bad_request"       # 400 — never retry
    TRANSIENT = "transient"           # other 5xx / network — retry
    UNKNOWN = "unknown"               # not classifiable — retry conservatively

    @property
    def retryable(self) -> bool:
        return self is not ThrottleKind.BAD_REQUEST

    @property
    def needs_credential_refresh(self) -> bool:
        return self is ThrottleKind.AUTH

    @property
    def advice(self) -> str:
        return _ADVICE[self]


_ADVICE = {
    ThrottleKind.TOKEN_QUOTA: (
        "A token-per-minute quota was exceeded. Reduce the submission rate; "
        "request a quota increase if this is sustained."
    ),
    ThrottleKind.CAPACITY: (
        "Regional capacity is under pressure. Occasional responses are "
        "transient; if sustained, reduce the rate and ramp back up in steps, "
        "or route latency-sensitive traffic to the priority service tier."
    ),
    ThrottleKind.AUTH: (
        "The credential was rejected. A derived short-term key may have "
        "expired; refreshing once and retrying usually resolves it."
    ),
    ThrottleKind.BAD_REQUEST: (
        "The request was rejected as malformed. Retrying will not help — check "
        "parameters and tool schemas for this model family."
    ),
    ThrottleKind.TRANSIENT: "A transient server or network error.",
    ThrottleKind.UNKNOWN: "Unclassified failure.",
}

_STATUS_KINDS = {
    400: ThrottleKind.BAD_REQUEST,
    401: ThrottleKind.AUTH,
    403: ThrottleKind.AUTH,
    422: ThrottleKind.BAD_REQUEST,
    429: ThrottleKind.TOKEN_QUOTA,
    503: ThrottleKind.CAPACITY,
}

_MESSAGE_PATTERNS: tuple[tuple[re.Pattern[str], ThrottleKind], ...] = (
    (re.compile(r"\b429\b|too many requests|rate.?limit|throttl", re.I), ThrottleKind.TOKEN_QUOTA),
    (re.compile(r"\b503\b|service unavailable|capacity", re.I), ThrottleKind.CAPACITY),
    (re.compile(r"\b40[13]\b|unauthorized|forbidden|expired token|invalid.{0,10}token", re.I), ThrottleKind.AUTH),
    (re.compile(r"\b400\b|\b422\b|validation|malformed|invalid.{0,20}(schema|parameter)", re.I), ThrottleKind.BAD_REQUEST),
    (re.compile(r"\b5\d\d\b|timeout|timed out|connection reset|broken pipe", re.I), ThrottleKind.TRANSIENT),
)


def _status_of(error: Any) -> int | None:
    for attribute in ("status_code", "status", "http_status", "code"):
        value = getattr(error, attribute, None)
        if isinstance(value, int) and 100 <= value < 600:
            return value
    response = getattr(error, "response", None)
    if response is not None:
        value = getattr(response, "status_code", None)
        if isinstance(value, int):
            return value
    return None


def classify(error: Any) -> ThrottleKind:
    """Categorise *error* by what response it calls for.

    Prefers an explicit status code; falls back to the message. Unclassifiable
    errors return ``UNKNOWN``, which is retryable but conservative — the safe
    direction, since a retried permanent error costs a little latency while an
    un-retried transient one costs the run.
    """
    status = _status_of(error)
    if status is not None:
        if status in _STATUS_KINDS:
            return _STATUS_KINDS[status]
        if 500 <= status < 600:
            return ThrottleKind.TRANSIENT
        if 400 <= status < 500:
            return ThrottleKind.BAD_REQUEST
    text = str(error)
    for pattern, kind in _MESSAGE_PATTERNS:
        if pattern.search(text):
            return kind
    return ThrottleKind.UNKNOWN


@dataclass(frozen=True, slots=True)
class BackoffPolicy:
    """How hard to retry one kind of failure."""

    max_attempts: int = 3
    base_delay: float = 1.0
    multiplier: float = 2.0
    max_delay: float = 60.0
    jitter: bool = True
    refresh_credentials_first: bool = False

    def delay_for(self, attempt: int, *, rng: random.Random | None = None) -> float:
        """Delay before *attempt* (1-based). Full jitter when enabled.

        Full jitter — a uniform draw from ``[0, computed]`` — rather than
        computed±ε, because synchronised clients retrying at the same computed
        instant is how a capacity dip becomes a thundering herd.
        """
        if attempt < 1:
            return 0.0
        raw = min(self.base_delay * (self.multiplier ** (attempt - 1)), self.max_delay)
        if not self.jitter:
            return raw
        return (rng or random).uniform(0.0, raw)


@dataclass(frozen=True, slots=True)
class RetrySchedule:
    """A backoff policy per throttle kind."""

    policies: dict[ThrottleKind, BackoffPolicy]

    def policy_for(self, kind: ThrottleKind) -> BackoffPolicy:
        return self.policies.get(kind, self.policies[ThrottleKind.UNKNOWN])

    def should_retry(self, kind: ThrottleKind, attempt: int) -> bool:
        return kind.retryable and attempt < self.policy_for(kind).max_attempts

    def describe(self, kind: ThrottleKind) -> str:
        """One line fit for a run summary — the cause, not just the failure."""
        return f"{kind.value}: {kind.advice}"


#: Shipped defaults. A token quota starts at a long delay because retrying it
#: quickly is actively harmful; capacity starts short because most 503s are a
#: momentary dip; auth refreshes once and does not loop.
DEFAULT_SCHEDULE = RetrySchedule(
    {
        ThrottleKind.TOKEN_QUOTA: BackoffPolicy(
            max_attempts=4, base_delay=20.0, multiplier=2.0, max_delay=120.0
        ),
        ThrottleKind.CAPACITY: BackoffPolicy(
            max_attempts=6, base_delay=1.0, multiplier=2.0, max_delay=45.0
        ),
        ThrottleKind.AUTH: BackoffPolicy(
            max_attempts=2, base_delay=0.0, jitter=False,
            refresh_credentials_first=True,
        ),
        ThrottleKind.BAD_REQUEST: BackoffPolicy(max_attempts=1, jitter=False),
        ThrottleKind.TRANSIENT: BackoffPolicy(max_attempts=4, base_delay=1.0),
        ThrottleKind.UNKNOWN: BackoffPolicy(max_attempts=2, base_delay=2.0),
    }
)
