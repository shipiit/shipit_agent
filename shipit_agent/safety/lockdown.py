"""Lockdown — once the agent reads something sensitive, it may only read.

The hole this closes: nothing today stops an agent from reading your customer
list and then, in the same turn, posting it to Slack. Guardrails redact
*recognizable* secrets from tool output, which handles API keys and JWTs. They
do nothing about data that is sensitive without matching a pattern — a private
document, a salary table, an unreleased plan. That data reaches the model
intact, and every outbound tool is still available.

Cloudflare OS calls this ``prohibitAllSharing``: an observation may be marked
so sensitive that the gadget "goes into lockdown mode where it can no longer
perform any actions, only make observations. This prevents the gadget from
leaking data through other gatekeepers."

Same idea here. When a tool reports that it returned sensitive data, the run
latches into lockdown: **observations still run, every action is denied for
the rest of the run**. Reading is how the agent finishes the analysis; acting
is how the data gets out.

A tool declares it::

    return ToolOutput(text=rows, metadata={"sensitive": True})

Or a policy detects it::

    Agent(lockdown=LockdownPolicy(sensitive_paths=("*.env", "**/secrets/**")))

The default policy honours explicit declarations and detects nothing, so
nothing changes for an agent whose tools say nothing. Detection is opt-in
because a false positive costs the rest of the run.
"""

from __future__ import annotations

import fnmatch
import time
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "LockdownPolicy",
    "LockdownState",
    "LockdownTrigger",
    "coerce_lockdown",
]


@dataclass(frozen=True, slots=True)
class LockdownTrigger:
    """Why lockdown engaged — shown to the user and to the model."""

    reason: str
    tool: str
    source: str  # "declared" | "path" | "secret" | "manual"
    at: float = field(default_factory=time.time)

    def describe(self) -> str:
        return f"{self.reason} (via {self.tool})"


@dataclass
class LockdownPolicy:
    """When to latch, and what latching means.

    ``enabled=False`` disables the mechanism entirely, including explicit
    declarations — for a run where you have decided the risk is acceptable.
    """

    enabled: bool = True

    # Honour ``ToolOutput(metadata={"sensitive": True})``. The tool knows what
    # it returned; this is the signal with no false positives.
    honour_declarations: bool = True

    # Glob patterns over a call's path-ish arguments. Off by default: a false
    # positive costs every remaining action in the run.
    sensitive_paths: tuple[str, ...] = ()

    # Latch when guardrails redact a secret from a tool's output. Also off by
    # default — a redacted secret never reached the model, so the exfiltration
    # risk is lower than for data that arrived intact.
    on_secret_redaction: bool = False

    # Tools that stay available even in lockdown, beyond observations. The
    # human-facing ones belong here: reporting *that* the run locked down is
    # not the leak, and removing the ability to say so makes lockdown look
    # like a hang.
    always_allowed: tuple[str, ...] = ("ask_user", "human_review", "give_up", "todo")

    def path_hit(self, arguments: dict[str, Any]) -> str | None:
        """Does any path-ish argument match a sensitive pattern?"""
        if not self.sensitive_paths:
            return None
        for key in ("path", "file", "filename", "url", "pattern", "query"):
            value = arguments.get(key)
            if not isinstance(value, str) or not value:
                continue
            for pattern in self.sensitive_paths:
                if fnmatch.fnmatch(value, pattern):
                    return f"read a protected location ({value})"
        return None


@dataclass
class LockdownState:
    """Whether this run has latched, and why.

    One-way: there is no un-latch. A run that has seen sensitive data has seen
    it, and a mechanism that could be switched off mid-run would be a
    mechanism the model could be talked into switching off.
    """

    policy: LockdownPolicy = field(default_factory=LockdownPolicy)
    trigger: LockdownTrigger | None = None

    @property
    def engaged(self) -> bool:
        return self.trigger is not None

    # ── latching ─────────────────────────────────────────────────────────

    def engage(self, *, reason: str, tool: str, source: str) -> LockdownTrigger | None:
        """Latch. Returns the trigger, or ``None`` if already latched or off."""
        if not self.policy.enabled or self.engaged:
            return None
        self.trigger = LockdownTrigger(reason=reason, tool=tool, source=source)
        return self.trigger

    def observe(
        self,
        *,
        tool: str,
        arguments: dict[str, Any],
        output_metadata: dict[str, Any] | None = None,
        redacted_secret: bool = False,
    ) -> LockdownTrigger | None:
        """Evaluate one completed tool call. Returns a trigger if it latched."""
        if not self.policy.enabled or self.engaged:
            return None

        metadata = output_metadata or {}
        if self.policy.honour_declarations and metadata.get("sensitive"):
            reason = str(
                metadata.get("sensitive_reason")
                or "the tool reported that it returned sensitive data"
            )
            return self.engage(reason=reason, tool=tool, source="declared")

        hit = self.policy.path_hit(arguments)
        if hit:
            return self.engage(reason=hit, tool=tool, source="path")

        if redacted_secret and self.policy.on_secret_redaction:
            return self.engage(
                reason="a secret was redacted from this tool's output",
                tool=tool,
                source="secret",
            )
        return None

    # ── enforcing ────────────────────────────────────────────────────────

    def blocks(self, tool: str, *, read_only: bool) -> bool:
        """Is this call denied by lockdown?"""
        if not self.engaged:
            return False
        if read_only or tool in self.policy.always_allowed:
            return False
        return True

    def denial_reason(self, tool: str) -> str:
        """What the model is told — the *why*, so it can report rather than retry."""
        trigger = self.trigger
        detail = trigger.describe() if trigger else "sensitive data was read"
        return (
            f"Lockdown: this run read sensitive data — {detail}. "
            f"Only read-only tools may run for the rest of the run, so "
            f"'{tool}' is blocked. Do not retry it or look for another way to "
            f"send this data. Finish your analysis and report what you found."
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "engaged": self.engaged,
            "reason": self.trigger.reason if self.trigger else None,
            "tool": self.trigger.tool if self.trigger else None,
            "source": self.trigger.source if self.trigger else None,
            "at": self.trigger.at if self.trigger else None,
        }


def coerce_lockdown(spec: Any) -> LockdownState:
    """Normalize an ``lockdown=`` argument into a :class:`LockdownState`.

    Accepts a policy, ``True``/``False``, a dict of policy kwargs, or ``None``
    (the default policy: declarations honoured, nothing detected).
    """
    if spec is None or spec is True:
        return LockdownState()
    if spec is False:
        return LockdownState(policy=LockdownPolicy(enabled=False))
    if isinstance(spec, LockdownState):
        return spec
    if isinstance(spec, LockdownPolicy):
        return LockdownState(policy=spec)
    if isinstance(spec, dict):
        return LockdownState(policy=LockdownPolicy(**spec))
    raise TypeError(f"Unsupported lockdown spec: {type(spec)!r}")
