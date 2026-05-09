"""Dataclasses + enums for the verifier network."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class VerifierVerdict(str, Enum):
    """Verdict returned by the pre-tool verifier for a proposed tool call."""

    ALLOW = "allow"
    """The tool call may proceed unchanged."""

    VETO = "veto"
    """Block the tool call. The agent will see a synthetic error result and re-plan."""

    REWRITE = "rewrite"
    """Allow the call but with modified arguments (returned in ``new_args``)."""


@dataclass(slots=True)
class PreToolDecision:
    """Verifier's decision about a single proposed tool call."""

    verdict: VerifierVerdict
    """ALLOW / VETO / REWRITE."""

    reason: str = ""
    """Human-readable explanation. Surfaced to the agent on veto/rewrite so it understands why."""

    new_args: dict[str, Any] | None = None
    """When verdict is REWRITE, the modified arguments to pass to the tool."""

    confidence: float = 1.0
    """0..1, used for telemetry. Verdicts below ``min_confidence`` are downgraded to ALLOW."""


@dataclass(slots=True)
class ProgressCheck:
    """Verifier's rating of one agent iteration."""

    score: float
    """0.0 (totally stalled) to 1.0 (clear progress)."""

    summary: str = ""
    """Short rationale, surfaced when the agent gets nudged for being stuck."""

    suggested_action: str | None = None
    """Optional hint the agent receives if its score drops too low too often."""


@dataclass(slots=True)
class VerifierConfig:
    """Options for ``VerifierNetwork``. Passed when constructing one of the verifier classes."""

    # Pre-tool veto
    veto_enabled: bool = True
    """If False, all pre-tool checks return ALLOW without calling the LLM."""

    veto_min_confidence: float = 0.6
    """Verdicts below this confidence are downgraded to ALLOW (avoid over-vetoing)."""

    # Progress check
    progress_enabled: bool = True
    """If False, progress checks are no-ops."""

    progress_threshold: float = 0.4
    """Below this score, the iteration is considered "no progress"."""

    progress_window: int = 3
    """Number of consecutive sub-threshold iterations before injecting a "you're stalling" nudge."""

    # Hard caps so the verifier itself can't run away
    max_pretool_calls_per_run: int = 50
    max_progress_calls_per_run: int = 30


@dataclass(slots=True)
class VerifierStats:
    """Telemetry — how often the verifier was consulted and what it said."""

    pretool_calls: int = 0
    pretool_allow: int = 0
    pretool_veto: int = 0
    pretool_rewrite: int = 0
    progress_calls: int = 0
    progress_below_threshold: int = 0
    nudges_injected: int = 0
    last_progress_scores: list[float] = field(default_factory=list)
