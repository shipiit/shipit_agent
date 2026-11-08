---
title: CostRouter — tiered LLM routing
description: Classify each turn as easy / medium / hard and route to the cheapest adequate model. Drop-in LLM adapter — every Autopilot feature works unchanged. Typical savings on 24h runs — 50–70%.
---

# CostRouter

`CostRouter` is a **drop-in LLM adapter** that classifies each prompt by
difficulty and routes it to the cheapest tier that can handle it.

> **TL;DR** — `CostRouter(easy=Tier(llm=haiku), medium=Tier(llm=sonnet),
> hard=Tier(llm=opus))` then hand the router to `Autopilot(llm=router, ...)`.
> The inner runtime never knows the call was routed. Typical savings on
> overnight runs: **50–70%**.

---

## Why it exists

On a 24-hour Autopilot run, most turns are things like "read this file",
"summarise one paragraph", or "yes or no?". Those turns don't need a
frontier model — running them on Opus (or Llama 70B) is pure waste.

The router fixes that. The classifier is a **cheap regex-style
heuristic** (no extra LLM call) — ship it with your agent and the first
long-running workload immediately benefits.

---

## Quick start

```python
from shipit_agent.routing import CostRouter, Tier
from shipit_agent.autopilot import Autopilot, BudgetPolicy
from shipit_agent.deep import Goal
from examples.run_multi_tool_agent import build_llm_from_env

haiku  = build_llm_from_env("bedrock")   # cheap — Llama 4 Scout / Claude Haiku
sonnet = build_llm_from_env("bedrock")   # swap to Sonnet 4.5 in real use
opus   = build_llm_from_env("bedrock")   # swap to Opus or Llama 405B

router = CostRouter(
    easy=Tier(llm=haiku,  price_per_1k=0.25, name="haiku"),
    medium=Tier(llm=sonnet, price_per_1k=3.0,  name="sonnet"),
    hard=Tier(llm=opus,   price_per_1k=15.0, name="opus"),
)

# The router IS an LLM — pass it to any Agent or Autopilot.
autopilot = Autopilot(
    llm=router,
    goal=Goal(objective="...", success_criteria=[...]),
    budget=BudgetPolicy(max_seconds=3600),
)
result = autopilot.run(run_id="nightly")

print(router.report.to_dict())
# {"tier_counts": {"easy": 34, "medium": 11, "hard": 2},
#  "estimated_dollars_spent": 1.82, "estimated_dollars_if_hardest": 4.85,
#  "savings": 3.03, "savings_pct": 62.5}
```

---

## The `Tier` and `SpendReport`

```python
@dataclass(slots=True)
class Tier:
    llm: Any                    # any shipit_agent LLM adapter
    price_per_1k: float = 0.0   # coarse $/1k-token for the savings report
    name: str = ""              # display-only: "haiku", "sonnet", "opus"
```

```python
router.report.tier_counts                 # {"easy": 34, "medium": 11, "hard": 2}
router.report.estimated_dollars_spent     # 1.82
router.report.estimated_dollars_if_hardest # 4.85
router.report.savings                     # 3.03
router.report.savings_pct                 # 62.5
```

`price_per_1k` is **only** used for the report — routing decisions never
block on price.

---

## Classification — the defaults

| Tier | When it fires |
| --- | --- |
| **HARD** | Prompt mentions high-effort verbs (`refactor`, `architect`, `investigate`, `security audit`, `optimize`, `threat model`) OR is > 500 chars |
| **MEDIUM** | Mentions an action verb (`write`, `implement`, `fix`, `add`, `create`) OR contains a code fence OR is > 120 chars |
| **EASY** | Everything else |

Hard keywords beat medium keywords beat length. Full list — see
`DEFAULT_DIFFICULTY_SIGNALS` in `shipit_agent.routing.cost_router`.

---

## Custom classifier

Pass your own `difficulty_fn` — useful if you want a tiny Haiku-class
LLM to score the prompt, or if you already have a difficulty oracle:

```python
def my_classifier(prompt: str) -> DifficultyTier:
    # call your own judge model, your own heuristic, whatever
    return DifficultyTier.MEDIUM if "debug" in prompt else DifficultyTier.EASY

router = CostRouter(
    easy=Tier(...), medium=Tier(...), hard=Tier(...),
    difficulty_fn=my_classifier,
)
```

If your custom classifier raises, the router falls back to `MEDIUM` —
**runs never die on classification**.

---

## Force a tier (override)

```python
router = CostRouter(..., force_tier=DifficultyTier.HARD)
# every call now goes to the hard tier — useful for audits / demos
```

---

## Graceful behavior

- **Missing usage metadata** on an LLM response → the call still succeeds; savings report just skips that entry.
- **Classifier raises** → fallback to `MEDIUM`.
- **Streaming** — `router.stream(...)` forwards the inner LLM's events unchanged.

---

## When NOT to use it

- Every call is short and cheap — no routing needed.
- You already hand-route based on task type upstream.
- You need exact per-call cost accounting — this is heuristic, not invoice-level.

---

## Notebook

- `notebooks/45_cost_router_async_ask_vision_sandbox.ipynb` — live demo with Bedrock Llama, combined with async ask_user + sandbox + vision.
