r"""Guardrails — content-level protection around every agent run.

Complements the permission engine (which gates *which tools* run) with
checks on *what flows through*: prompts in, answers out, tool arguments in
between::

    from shipit_agent import Agent, Guardrails

    agent = Agent.with_builtins(
        llm=llm,
        guardrails=Guardrails(
            block_prompt_injection=True,     # "ignore previous instructions", …
            block_secret_leaks=True,         # API keys/JWTs/private keys redacted
            redact_pii=True,                 # emails, phones, SSNs, cards
            input_blocklist=["internal-codename"],
            tool_rules={"bash": [r"rm\s+-rf\s+/", r"curl[^|]*\|\s*sh"]},
        ),
    )

Every trigger emits a ``guardrail_triggered`` event, blocked prompts never
reach the LLM, and redactions replace matches with ``[REDACTED:<kind>]``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from .permissions import PermissionDecision, PermissionResult

# ── detection patterns ────────────────────────────────────────────────

_INJECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"ignore\s+(?:all|any|previous|prior|the above)\s+.{0,30}instructions",
        r"disregard\s+(?:your|the)\s+(?:system\s+)?(?:prompt|instructions|rules)",
        r"reveal\s+(?:your|the)\s+system\s+prompt",
        r"you\s+are\s+now\s+(?:DAN|jailbroken|unrestricted)",
        r"pretend\s+(?:you\s+have|there\s+are)\s+no\s+(?:rules|restrictions|guidelines)",
        r"override\s+(?:your|all)\s+safety",
    )
]

_SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("api-key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("aws-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("private-key", re.compile(r"-----BEGIN[A-Z ]*PRIVATE KEY-----")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
]

_PII_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("credit-card", re.compile(r"\b(?:\d[ -]?){15}\d\b")),
    ("phone", re.compile(r"(?<![\d.])\+?\d{1,3}[ .-]?\(?\d{2,4}\)?[ .-]?\d{3,4}[ .-]?\d{3,4}(?![\d.])")),
]


@dataclass(slots=True)
class GuardDecision:
    """Outcome of a guardrail check."""

    action: str = "allow"  # "allow" | "block" | "redact"
    reason: str = ""
    text: str = ""  # the (possibly redacted) text when action != "block"

    @property
    def blocked(self) -> bool:
        return self.action == "block"


@dataclass(slots=True)
class Guardrails:
    """Composable content guardrails for prompts, outputs, and tool args.

    - ``block_prompt_injection`` — refuse prompts matching common
      injection/jailbreak phrasings (checked on INPUT).
    - ``block_secret_leaks`` — redact API keys, tokens, JWTs, and private
      keys from OUTPUT (never blocks; redacts).
    - ``redact_pii`` — redact emails/phones/SSNs/cards from OUTPUT.
    - ``input_blocklist`` / ``output_blocklist`` — case-insensitive
      substrings that block the prompt / redact the answer.
    - ``tool_rules`` — ``{tool_name: [regex, ...]}``; a tool call whose
      serialized arguments match any regex is DENIED (merges with the
      permission engine; guardrail denials win).
    - ``custom_input`` / ``custom_output`` — callables
      ``(text) -> GuardDecision | None`` for bespoke checks.
    """

    block_prompt_injection: bool = True
    block_secret_leaks: bool = True
    redact_pii: bool = False
    input_blocklist: list[str] = field(default_factory=list)
    output_blocklist: list[str] = field(default_factory=list)
    tool_rules: dict[str, list[str]] = field(default_factory=dict)
    custom_input: Callable[[str], GuardDecision | None] | None = None
    custom_output: Callable[[str], GuardDecision | None] | None = None

    # ── input ─────────────────────────────────────────────────────────
    def check_input(self, text: str) -> GuardDecision:
        if self.block_prompt_injection:
            for pattern in _INJECTION_PATTERNS:
                if pattern.search(text):
                    return GuardDecision(
                        action="block",
                        reason=f"prompt-injection pattern: {pattern.pattern[:40]}",
                    )
        lowered = text.lower()
        for term in self.input_blocklist:
            if term.lower() in lowered:
                return GuardDecision(
                    action="block", reason=f"blocklisted input term: {term!r}"
                )
        if self.custom_input is not None:
            custom = self.custom_input(text)
            if custom is not None:
                return custom
        return GuardDecision(action="allow", text=text)

    # ── output ────────────────────────────────────────────────────────
    def check_output(self, text: str) -> GuardDecision:
        redacted = text
        kinds: list[str] = []
        if self.block_secret_leaks:
            for kind, pattern in _SECRET_PATTERNS:
                redacted, n = pattern.subn(f"[REDACTED:{kind}]", redacted)
                if n:
                    kinds.append(kind)
        if self.redact_pii:
            for kind, pattern in _PII_PATTERNS:
                redacted, n = pattern.subn(f"[REDACTED:{kind}]", redacted)
                if n:
                    kinds.append(kind)
        lowered = redacted.lower()
        for term in self.output_blocklist:
            if term.lower() in lowered:
                pattern = re.compile(re.escape(term), re.IGNORECASE)
                redacted = pattern.sub("[REDACTED:blocklist]", redacted)
                kinds.append("blocklist")
        if self.custom_output is not None:
            custom = self.custom_output(redacted)
            if custom is not None:
                return custom
        if kinds:
            return GuardDecision(
                action="redact",
                reason="redacted: " + ", ".join(sorted(set(kinds))),
                text=redacted,
            )
        return GuardDecision(action="allow", text=text)

    # ── tools ─────────────────────────────────────────────────────────
    def check_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> PermissionResult | None:
        rules = self.tool_rules.get(name) or self.tool_rules.get("*")
        if not rules:
            return None
        serialized = repr(arguments)
        for rule in rules:
            if re.search(rule, serialized, re.IGNORECASE):
                return PermissionResult(
                    decision=PermissionDecision.DENY,
                    reason=f"guardrail: arguments match {rule!r}",
                )
        return None
