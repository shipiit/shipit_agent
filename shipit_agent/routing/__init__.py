"""Cost-aware routing — tiered LLM selection based on turn difficulty.

Public surface:
  - CostRouter                 — the routing decision engine
  - DifficultyTier             — Enum-style constants (EASY / MEDIUM / HARD)
  - Tier                       — per-tier configuration (llm + approx $/1k tokens)
  - SpendReport                — tallied cost savings after a run
  - DEFAULT_DIFFICULTY_SIGNALS — lightweight heuristics (no LLM call needed)

Typical use::

    from shipit_agent.routing import CostRouter, Tier

    router = CostRouter(
        easy=Tier(llm=llm_haiku,  price_per_1k=0.25),
        medium=Tier(llm=llm_sonnet, price_per_1k=3.0),
        hard=Tier(llm=llm_opus,   price_per_1k=15.0),
    )
    chosen, tier = router.route("What day is it?")
    # chosen == llm_haiku
"""

from .cost_router import (
    CostRouter,
    DEFAULT_DIFFICULTY_SIGNALS,
    DifficultyTier,
    SpendReport,
    Tier,
    classify_difficulty,
)

__all__ = [
    "CostRouter",
    "DEFAULT_DIFFICULTY_SIGNALS",
    "DifficultyTier",
    "SpendReport",
    "Tier",
    "classify_difficulty",
]
