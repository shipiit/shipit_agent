"""The patterns guardrails look for: prompt injection, secrets and personal data."""

from __future__ import annotations

import re

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
