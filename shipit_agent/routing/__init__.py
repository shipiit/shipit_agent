"""Cost-aware routing — tiered LLM selection based on turn difficulty.

Public surface:
  - CostRouter                 — the routing decision engine
  - DifficultyTier             — Enum-style constants (EASY / MEDIUM / HARD)
  - Tier                       — per-tier configuration (llm + approx $/1k tokens)
  - SpendReport                — tallied cost savings after a run
  - DEFAULT_DIFFICULTY_SIGNALS — lightweight heuristics (no LLM call needed)
  - StepRouter                 — per-STEP routing inside a run: routine steps on a
                                 fast model, planning/recovery/answers on a strong one

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
    DEFAULT_DIFFICULTY_SIGNALS,
    CostRouter,
    DifficultyTier,
    SpendReport,
    Tier,
    classify_difficulty,
)
from .step_router import RouteReport, StepRouter, classify_step

__all__ = [
    "DEFAULT_DIFFICULTY_SIGNALS",
    "CostRouter",
    "DifficultyTier",
    "RouteReport",
    "SpendReport",
    "StepRouter",
    "Tier",
    "classify_difficulty",
    "classify_step",
]
