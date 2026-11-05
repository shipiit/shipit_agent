"""Accounting for every completion, including the ones nobody watches.

An agent makes far more model calls than the one the user is waiting on: a
summariser when history overflows, a sub-agent per delegated task, a cheap model
to assess or narrate, a consolidator for memory, a verifier at the end. Those
calls happen outside the main streaming loop, so a tracker wired only to that
loop reports a fraction of the real cost — and reports it lowest exactly on the
runs that cost most, because delegation is what multiplies calls.

Two things follow from tagging every call with a *purpose*:

**Accounting closes.** Every completion reaches one sink, and the run total is
the sum of its parts rather than the part that happened to be observable.

**Tiering becomes possible.** Service tiers are opted into per invocation and
can be mixed within one application, so the same run can put the turn the user
is watching on the priority tier and push its background fan-out to flex. That
is a cost reduction and a latency improvement at once, with no behaviour change
— but only if each call site says what it is for.

Cache tokens need one more piece of care: providers disagree about whether
cached tokens are *inside* ``input_tokens`` or *added to* it. Getting that wrong
double-counts or under-counts on every cached turn, and implicit caching means
most turns are cached turns. The split is therefore explicit, driven by the
model's capabilities rather than assumed.
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Mapping

logger = logging.getLogger(__name__)

__all__ = [
    "Purpose",
    "ServiceTier",
    "TierPolicy",
    "UsageEvent",
    "UsageLedger",
    "split_usage",
    "DEFAULT_TIER_POLICY",
]


class Purpose(str, Enum):
    """Why a completion happened. Every call site names one."""

    MAIN = "main"                          # the turn the user is waiting on
    SUBAGENT = "subagent"                  # delegated child run
    SUMMARIZER = "summarizer"              # compaction handoff
    MEMORY = "memory"                      # memory extraction / consolidation
    ASSESSOR = "assessor"                  # delegation / routing decisions
    PROGRESS = "progress"                  # narration, activity labels
    VERIFIER = "verifier"                  # end-of-run checking
    TITLE = "title"                        # conversation titling
    OTHER = "other"


class ServiceTier(str, Enum):
    PRIORITY = "priority"   # lower latency, premium price
    STANDARD = "standard"   # default
    FLEX = "flex"           # discounted, higher latency


@dataclass(frozen=True, slots=True)
class TierPolicy:
    """Which service tier each purpose runs on."""

    default: ServiceTier = ServiceTier.STANDARD
    by_purpose: Mapping[Purpose, ServiceTier] = field(default_factory=dict)

    def tier_for(self, purpose: Purpose) -> ServiceTier:
        return self.by_purpose.get(purpose, self.default)

    def as_request_param(self, purpose: Purpose, *, supported: bool) -> dict[str, str]:
        """``{"service_tier": ...}`` when the model supports it, else ``{}``.

        Returns a dict so a call site can splat it unconditionally: a model
        family that does not understand the parameter must never receive it.
        """
        if not supported:
            return {}
        return {"service_tier": self.tier_for(purpose).value}


#: The user waits on the foreground turn; everything else is background work
#: whose latency nobody observes. Verification stays on standard because it
#: gates the answer.
DEFAULT_TIER_POLICY = TierPolicy(
    default=ServiceTier.STANDARD,
    by_purpose={
        Purpose.MAIN: ServiceTier.PRIORITY,
        Purpose.SUBAGENT: ServiceTier.FLEX,
        Purpose.SUMMARIZER: ServiceTier.FLEX,
        Purpose.MEMORY: ServiceTier.FLEX,
        Purpose.ASSESSOR: ServiceTier.FLEX,
        Purpose.PROGRESS: ServiceTier.FLEX,
        Purpose.TITLE: ServiceTier.FLEX,
        Purpose.VERIFIER: ServiceTier.STANDARD,
    },
)


@dataclass(frozen=True, slots=True)
class UsageEvent:
    """One model call's token usage, normalised into billing units."""

    purpose: Purpose
    model: str
    input_tokens: int = 0          # excludes cached portions
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    tier: ServiceTier = ServiceTier.STANDARD
    agent: str = ""

    @property
    def total_input(self) -> int:
        return self.input_tokens + self.cache_read_tokens + self.cache_write_tokens

    @property
    def total_tokens(self) -> int:
        return self.total_input + self.output_tokens


def split_usage(
    usage: Mapping[str, Any],
    *,
    cache_included_in_input: bool,
) -> tuple[int, int, int, int]:
    """Normalise a provider usage payload to ``(input, output, read, write)``.

    ``input`` always excludes cached tokens, so the four numbers sum to the true
    total exactly once regardless of which convention the provider used. Missing
    or non-numeric fields count as zero rather than raising — usage accounting
    must never be able to fail a run.
    """

    def number(*keys: str) -> int:
        for key in keys:
            value = usage.get(key)
            if isinstance(value, (int, float)):
                return max(0, int(value))
        return 0

    raw_input = number("input_tokens", "prompt_tokens")
    output = number("output_tokens", "completion_tokens")
    cache_read = number("cache_read_input_tokens", "cache_read", "cached_tokens")
    cache_write = number("cache_creation_input_tokens", "cache_write")

    if cache_included_in_input:
        return max(0, raw_input - cache_read - cache_write), output, cache_read, cache_write
    return raw_input, output, cache_read, cache_write


class UsageLedger:
    """Collects every :class:`UsageEvent` in a run and totals it by purpose.

    Thread-safe, because sub-agents and parallel tool threads record
    concurrently. Pricing is injected — a hand-maintained table belongs in one
    place, and the ledger's job is completeness, not rates.
    """

    __slots__ = ("_events", "_lock", "_price")

    def __init__(
        self,
        price_fn: Callable[[UsageEvent], float] | None = None,
    ) -> None:
        self._events: list[UsageEvent] = []
        self._lock = threading.Lock()
        self._price = price_fn

    def record(self, event: UsageEvent) -> None:
        with self._lock:
            self._events.append(event)

    def sink(self, purpose: Purpose, model: str, *, agent: str = "") -> Callable[..., None]:
        """A bound recorder for one call site.

        Threading a zero-argument-ish callable through is what makes tagging
        every nested completion cheap enough that it actually happens.
        """

        def _record(
            usage: Mapping[str, Any],
            *,
            cache_included_in_input: bool = True,
            tier: ServiceTier = ServiceTier.STANDARD,
        ) -> None:
            in_tokens, out_tokens, read, write = split_usage(
                usage or {}, cache_included_in_input=cache_included_in_input
            )
            self.record(
                UsageEvent(
                    purpose=purpose,
                    model=model,
                    input_tokens=in_tokens,
                    output_tokens=out_tokens,
                    cache_read_tokens=read,
                    cache_write_tokens=write,
                    tier=tier,
                    agent=agent,
                )
            )

        return _record

    # -- reporting ---------------------------------------------------------

    @property
    def events(self) -> list[UsageEvent]:
        with self._lock:
            return list(self._events)

    def totals(self) -> dict[str, int]:
        events = self.events
        return {
            "calls": len(events),
            "input_tokens": sum(e.input_tokens for e in events),
            "output_tokens": sum(e.output_tokens for e in events),
            "cache_read_tokens": sum(e.cache_read_tokens for e in events),
            "cache_write_tokens": sum(e.cache_write_tokens for e in events),
            "total_tokens": sum(e.total_tokens for e in events),
        }

    def by_purpose(self) -> dict[str, dict[str, int]]:
        grouped: dict[str, dict[str, int]] = defaultdict(
            lambda: {"calls": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        )
        for event in self.events:
            row = grouped[event.purpose.value]
            row["calls"] += 1
            row["input_tokens"] += event.input_tokens
            row["output_tokens"] += event.output_tokens
            row["total_tokens"] += event.total_tokens
        return dict(grouped)

    def cost_usd(self) -> float | None:
        """Total cost, or ``None`` when any call could not be priced.

        Partial coverage is reported as unknown rather than as a number, because
        a sum missing one call reads as authoritative and under-reports.
        """
        if self._price is None:
            return None
        total = 0.0
        for event in self.events:
            try:
                value = self._price(event)
            except Exception:  # noqa: BLE001
                logger.debug("Could not price %s/%s", event.purpose, event.model)
                return None
            if value is None:
                return None
            total += float(value)
        return round(total, 6)

    def summary(self) -> dict[str, Any]:
        """The block that belongs in a run summary."""
        summary: dict[str, Any] = {
            "usage": self.totals(),
            "by_purpose": self.by_purpose(),
        }
        cost = self.cost_usd()
        if cost is not None:
            summary["cost_usd"] = cost
        return summary
