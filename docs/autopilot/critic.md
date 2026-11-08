---
title: Critic — reflection loop
description: A per-iteration reviewer that scores output against criteria, feeds suggestions back into the next iteration, and short-circuits the run the moment every criterion is confidently met.
---

# Critic — reflection loop

The `Critic` is a **second-opinion reviewer** wired into Autopilot's
iteration loop. After each iteration it scores the output against the
goal's success criteria and returns a `CriticVerdict`. When the verdict
confidently says "every criterion is met", Autopilot halts without
burning another iteration.

> **TL;DR** — pass `critic=True` to Autopilot for a self-check, or
> `critic=Critic(llm=reviewer_llm)` for a dedicated stronger reviewer.
> Criteria-satisfaction rate goes up, wasted iterations go down.

---

## When to use it

| Use a critic when… | Skip the critic when… |
| --- | --- |
| The goal has concrete, checkable criteria. | The goal is open-ended brainstorming. |
| Hallucinated "done" is a real risk. | You want the cheapest possible run. |
| A 2× per-iteration cost is acceptable for quality. | Latency matters more than rigor. |

---

## The default critic — self-check

`critic=True` builds a critic that reuses your run's own LLM:

```python
from shipit_agent import Goal
from shipit_agent.autopilot import Autopilot, BudgetPolicy

autopilot = Autopilot(
    llm=llm,
    goal=Goal(
        objective="Explain the Python GIL and include a runnable snippet.",
        success_criteria=[
            "Two paragraphs of prose",
            "A runnable Python snippet showing GIL-related behavior",
        ],
    ),
    budget=BudgetPolicy(max_iterations=6),
    critic=True,                            # ← enables reflection
)
result = autopilot.run(run_id="gil-explainer")
print(result.critic_verdict)
```

Self-check is good at catching "I claimed to have an example but
didn't show one" — the critic sees the output and grounds criteria on
concrete evidence.

---

## A dedicated reviewer

For security reviews, compliance runs, or any high-stakes goal,
instantiate `Critic` with a stronger model so the reviewer isn't
marking its own homework:

```python
from shipit_agent.autopilot import Critic

strict_critic = Critic(
    llm=reviewer_llm,                       # e.g. a bigger Bedrock Llama or Claude
    confidence_threshold=0.85,              # raise the gate — 0.75 is default
)
autopilot = Autopilot(
    llm=llm,
    goal=Goal(objective="Audit authentication flow", success_criteria=[...]),
    budget=BudgetPolicy(max_iterations=8),
    critic=strict_critic,
)
```

The reviewer runs once per iteration — double the per-iteration LLM
cost. Pair with `max_iterations` carefully.

---

## The `CriticVerdict` shape

Every critic pass returns a verdict the final `AutopilotResult`
surfaces as `result.critic_verdict`:

```python
{
    "criteria_met": [True, False, True],       # one bool per criterion, in order
    "confidence": 0.82,                         # 0..1 — the critic's own confidence
    "suggestions": [                            # concrete next-actions (max 5 by default)
        "Include a working snippet for criterion 2",
    ],
    "reasoning": "First paragraph is solid; second repeats the first.",
}
```

Key rule: **a critic-said-yes only short-circuits the run when
`confidence >= confidence_threshold`**. A low-confidence "yes" is
still logged — and its suggestions feed into the next iteration — but
Autopilot won't trust it to terminate.

---

## How suggestions feed back into the next iteration

When the critic returns `suggestions`, Autopilot injects them into the
inner agent's prompt for the next iteration:

```
[critic feedback from prior iteration — address these before concluding]
- Include a working snippet for criterion 2
- Tighten the second paragraph; it currently repeats the first
```

Net effect: the inner agent sees its own critic's feedback mid-run,
not just at the end. Empirically cuts iterations-to-completion ~20–40%
on goals with explicit criteria.

---

## Stream events

When you use `autopilot.stream()`, a critic adds two event kinds:

| Event | Shape |
| --- | --- |
| `autopilot.critic` | `{"kind","criteria_met","confidence","suggestions","reasoning"}` — emitted after every iteration the critic runs |
| `autopilot.criteria_satisfied` | carries `by_critic: True` when the critic (not the inner agent) triggered termination |

---

## API reference

```python
class Critic:
    def __init__(
        self,
        *,
        llm: Any | None = None,
        system_prompt: str | None = None,
        confidence_threshold: float = 0.75,
        max_suggestions: int = 5,
    ) -> None: ...

    def review(
        self, *, objective: str, criteria: list[str], output: str,
        fallback_llm: Any | None = None,
    ) -> CriticVerdict: ...

    def should_terminate(self, verdict: CriticVerdict) -> bool: ...
```

- **`fallback_llm`** — Autopilot passes its own LLM here when `Critic`
  was constructed without one, so the default critic is free for the
  caller.
- **`should_terminate`** — the gate used by Autopilot; returns `True`
  only when every flag is `True` AND `confidence >= threshold`.

---

## Robustness

The JSON parser tolerates:

- Fenced `` ```json `` wrappers (many models wrap despite instructions).
- Extra prose before/after the JSON object.
- Missing `criteria_met` entries — padded to `len(criteria)` with `False`.
- Overflow entries — trimmed to `len(criteria)`.
- Garbage — returns a zero-confidence verdict with `reasoning="critic returned non-JSON; skipped."` rather than raising.

A critic that raises never kills the run — Autopilot logs it and keeps
iterating.

---

## Notebook

- `notebooks/43_fanout_critic_artifacts.ipynb` — a focused deep-dive.
- `notebooks/44_complete_tour.ipynb` — the critic in context with every
  other feature.
