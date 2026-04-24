"""CostRouter — route each turn to the cheapest model that can handle it.

Typical 24-hour Autopilot runs spend 50–70% of their budget on turns
that would have been fine with the smallest model in the lineup. The
CostRouter fixes that: before each turn, classify the prompt as easy /
medium / hard, then pick the tier whose model is sized for that level.

Classification is heuristic by default (cheap, deterministic, no extra
LLM call). Callers who need richer scoring can pass a custom
`difficulty_fn` — e.g. a tiny Haiku-class call that returns a 0-1
score. Autopilot treats the router as a drop-in LLM; every adapter in
`shipit_agent.llms` satisfies the same interface so `.complete()` and
`.stream()` just work.

Kept deliberately boring: no model downloads, no embedding models, no
network. Heuristics are measured in lines of code, not papers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Iterable

from shipit_agent.models import Message


class DifficultyTier(str, Enum):
    """Three-tier classification the router picks between."""
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


@dataclass(slots=True)
class Tier:
    """Per-tier configuration: the LLM to use and its price.

    ``price_per_1k`` is a rough $/1k-token figure used only for the
    :class:`SpendReport` — routing decisions never block on it.
    """

    llm: Any
    price_per_1k: float = 0.0
    name: str = ""            # display-only, e.g. "haiku" / "sonnet" / "opus"


@dataclass(slots=True)
class SpendReport:
    """Aggregated cost/savings across a session of `router.route()` calls."""
    tier_counts: dict[str, int] = field(default_factory=dict)
    estimated_dollars_spent: float = 0.0
    estimated_dollars_if_hardest: float = 0.0

    @property
    def savings(self) -> float:
        return max(0.0, self.estimated_dollars_if_hardest - self.estimated_dollars_spent)

    @property
    def savings_pct(self) -> float:
        if self.estimated_dollars_if_hardest <= 0:
            return 0.0
        return 100.0 * self.savings / self.estimated_dollars_if_hardest

    def to_dict(self) -> dict[str, Any]:
        return {
            "tier_counts": dict(self.tier_counts),
            "estimated_dollars_spent": round(self.estimated_dollars_spent, 4),
            "estimated_dollars_if_hardest": round(self.estimated_dollars_if_hardest, 4),
            "savings": round(self.savings, 4),
            "savings_pct": round(self.savings_pct, 1),
        }


# ── Heuristics — tuned from real agent traces, not from papers. ──


@dataclass(slots=True)
class DifficultySignals:
    """Config for the default difficulty classifier."""
    hard_substrings: tuple[str, ...] = (
        "refactor", "architect", "design", "plan", "review", "audit", "investig",
        "debug", "root cause", "optimise", "optimize", "migrate", "security",
        "threat model", "consolidate", "reconcile", "summarise this codebase",
    )
    medium_substrings: tuple[str, ...] = (
        "write", "implement", "add", "fix", "build", "create", "generate",
        "draft", "compose", "edit", "update", "search", "find",
    )
    long_prompt_chars: int = 500        # prompts longer than this → bump to hard
    medium_prompt_chars: int = 120      # prompts longer than this → bump to medium
    code_block_triggers_medium: bool = True


DEFAULT_DIFFICULTY_SIGNALS = DifficultySignals()


def classify_difficulty(
    prompt: str,
    *,
    signals: DifficultySignals = DEFAULT_DIFFICULTY_SIGNALS,
) -> DifficultyTier:
    """Cheap heuristic classifier.

    Order matters: hard keywords beat medium keywords beat easy. Length
    and code-fence presence nudge the tier upward.
    """
    text = prompt.lower()

    for kw in signals.hard_substrings:
        if kw in text:
            return DifficultyTier.HARD

    length = len(prompt)
    has_code = "```" in prompt

    if length >= signals.long_prompt_chars:
        return DifficultyTier.HARD
    if has_code and signals.code_block_triggers_medium:
        return DifficultyTier.MEDIUM
    for kw in signals.medium_substrings:
        if kw in text:
            return DifficultyTier.MEDIUM
    if length >= signals.medium_prompt_chars:
        return DifficultyTier.MEDIUM
    return DifficultyTier.EASY


# ── The router ──────────────────────────────────────────────────


class CostRouter:
    """Tiered LLM router + drop-in LLM adapter.

    ``CostRouter`` exposes the same ``complete(...)`` / ``stream(...)``
    surface every shipit_agent LLM adapter does. Pass it to ``Agent``
    or ``Autopilot`` exactly like any other LLM — the runtime never
    knows the turn was routed.
    """

    def __init__(
        self,
        *,
        easy: Tier,
        medium: Tier,
        hard: Tier,
        difficulty_fn: Callable[[str], DifficultyTier] | None = None,
        signals: DifficultySignals = DEFAULT_DIFFICULTY_SIGNALS,
        force_tier: DifficultyTier | None = None,
    ) -> None:
        self.tiers: dict[DifficultyTier, Tier] = {
            DifficultyTier.EASY: easy,
            DifficultyTier.MEDIUM: medium,
            DifficultyTier.HARD: hard,
        }
        self.difficulty_fn = difficulty_fn or (lambda p: classify_difficulty(p, signals=signals))
        self.force_tier = force_tier
        self.report = SpendReport()

    # ── routing decision ────────────────────────────────────────

    def classify(self, prompt: str) -> DifficultyTier:
        if self.force_tier is not None:
            return self.force_tier
        try:
            return self.difficulty_fn(prompt)
        except Exception:      # noqa: BLE001 — never let classification raise
            return DifficultyTier.MEDIUM

    def route(self, prompt: str) -> tuple[Any, DifficultyTier]:
        """Return the LLM to use for this prompt and the chosen tier."""
        tier = self.classify(prompt)
        return self.tiers[tier].llm, tier

    # ── LLM adapter shape — make the router itself a drop-in LLM ──

    def complete(self, messages: Iterable[Message], **kwargs: Any) -> Any:
        """Forward to the tier-appropriate LLM. Looks at the last user
        message (or the concatenated prompt) to classify."""
        msgs = list(messages)
        prompt = self._prompt_from_messages(msgs)
        llm, tier = self.route(prompt)
        response = llm.complete(msgs, **kwargs)
        self._record(tier, response)
        return response

    def stream(self, messages: Iterable[Message], **kwargs: Any):
        msgs = list(messages)
        prompt = self._prompt_from_messages(msgs)
        llm, tier = self.route(prompt)
        stream_ = llm.stream(msgs, **kwargs)
        for event in stream_:
            yield event
        # No token count here — the underlying LLM owns accounting during stream.
        self._record(tier, None)

    # ── accounting ──────────────────────────────────────────────

    def _record(self, tier: DifficultyTier, response: Any) -> None:
        self.report.tier_counts[tier.value] = self.report.tier_counts.get(tier.value, 0) + 1
        usage = getattr(response, "usage", None) if response is not None else None
        if not isinstance(usage, dict):
            return
        total = int(usage.get("total_tokens", 0) or 0)
        if total <= 0:
            total = int(usage.get("prompt_tokens", 0) or 0) + int(usage.get("completion_tokens", 0) or 0)
        if total <= 0:
            return

        self.report.estimated_dollars_spent += (total / 1000.0) * self.tiers[tier].price_per_1k
        self.report.estimated_dollars_if_hardest += (
            (total / 1000.0) * self.tiers[DifficultyTier.HARD].price_per_1k
        )

    @staticmethod
    def _prompt_from_messages(messages: list[Message]) -> str:
        # Prefer the last user message; fall back to the concat of all
        # user messages. Tolerate dicts too (tests pass them sometimes).
        def _role(m: Any) -> str: return getattr(m, "role", None) or m.get("role", "")
        def _content(m: Any) -> str: return getattr(m, "content", None) or m.get("content", "")

        users = [_content(m) for m in messages if _role(m) == "user"]
        if users:
            return str(users[-1])
        return "\n".join(str(_content(m)) for m in messages)
