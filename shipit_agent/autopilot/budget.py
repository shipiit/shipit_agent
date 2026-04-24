"""Budget gates that halt an Autopilot run before it overruns.

The policy is deliberately multi-axis: one run can blow through tokens
long before it runs out of wall-clock, or vice versa. Every axis trips
independently so the halt reason always pinpoints which limit was hit.

For 24-hour runs the axes that matter most are ``max_seconds`` and
``max_dollars``; ``max_iterations`` is the safety net that protects
against a degenerate loop that makes no progress.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(slots=True)
class BudgetPolicy:
    """Caps for a long-running Autopilot execution.

    Any field set to ``None`` or ``0`` disables that axis. Defaults are
    conservative: a 30-minute / 100-tool-call cap forces callers to opt
    into a 24-hour run by explicitly raising the ceilings.
    """

    max_seconds: float | None = 1_800.0
    max_tool_calls: int | None = 100
    max_tokens: int | None = 2_000_000
    max_dollars: float | None = 5.0
    max_iterations: int | None = 200

    def exceeded(self, usage: "BudgetUsage") -> tuple[bool, str]:
        """Return ``(True, reason)`` if any cap has been breached."""
        if self.max_seconds and usage.seconds > self.max_seconds:
            return (
                True,
                f"wall-clock limit reached: {usage.seconds:.0f}s > {self.max_seconds:.0f}s",
            )
        if self.max_tool_calls and usage.tool_calls > self.max_tool_calls:
            return (
                True,
                f"tool-call limit reached: {usage.tool_calls} > {self.max_tool_calls}",
            )
        if self.max_tokens and usage.tokens > self.max_tokens:
            return True, f"token limit reached: {usage.tokens} > {self.max_tokens}"
        if self.max_dollars and usage.dollars > self.max_dollars:
            return (
                True,
                f"dollar limit reached: ${usage.dollars:.2f} > ${self.max_dollars:.2f}",
            )
        if self.max_iterations and usage.iterations > self.max_iterations:
            return (
                True,
                f"iteration limit reached: {usage.iterations} > {self.max_iterations}",
            )
        return False, ""

    def would_exceed_after(
        self,
        usage: "BudgetUsage",
        *,
        extra_seconds: float = 0.0,
        extra_tokens: int = 0,
        extra_dollars: float = 0.0,
        extra_tool_calls: int = 0,
    ) -> tuple[bool, str]:
        """Check whether adding projected overhead to ``usage`` *would*
        trip a cap. Used for pre-iteration gating — skip the next step
        when we know it'd blow the budget before it starts.
        """
        projected = BudgetUsage(
            seconds=usage.seconds + extra_seconds,
            tool_calls=usage.tool_calls + extra_tool_calls,
            tokens=usage.tokens + extra_tokens,
            dollars=usage.dollars + extra_dollars,
            iterations=usage.iterations,
        )
        return self.exceeded(projected)

    def remaining(self, usage: "BudgetUsage") -> dict[str, float | int | None]:
        """Return the remaining headroom on each axis, or ``None`` when
        the axis is disabled. Useful for progress events and ETAs.
        """

        def _sub(cap: float | int | None, used: float | int) -> float | int | None:
            if not cap:
                return None
            return max(0, cap - used)

        return {
            "seconds": _sub(self.max_seconds, usage.seconds),
            "tool_calls": _sub(self.max_tool_calls, usage.tool_calls),
            "tokens": _sub(self.max_tokens, usage.tokens),
            "dollars": _sub(self.max_dollars, usage.dollars),
            "iterations": _sub(self.max_iterations, usage.iterations),
        }


@dataclass(slots=True)
class BudgetUsage:
    """Running totals the Autopilot updates after each iteration."""

    seconds: float = 0.0
    tool_calls: int = 0
    tokens: int = 0
    dollars: float = 0.0
    iterations: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
