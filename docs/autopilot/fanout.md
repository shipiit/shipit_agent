---
title: Fan-out — parallel batches
description: Dispatch N child Autopilots in parallel against a batch of items. Each child gets a budget-scaled slice of the parent budget. Aggregate results, live per-child events, ordered output.
---

# Fan-out — parallel batches

`Autopilot.fanout()` dispatches **one child Autopilot per item** in
parallel. It's the single biggest unlock for long-running agent
workloads — "audit every PR merged today", "research every top-50
account", "migrate every SQL call in `src/`".

> **TL;DR** — `autopilot.fanout(items=[...], objective_template="Do {item}")`
> runs N children concurrently. Each child gets `parent_budget * child_budget_frac`
> (default 20%). Returns a `FanoutResult` with every child's outcome.

---

## When to reach for fan-out

| Use fan-out when… | Use plain `run()` when… |
| --- | --- |
| You have a list of items, one goal-shape per item. | You have one goal that needs many inner steps. |
| Each item is independent (no shared context). | Items depend on each other. |
| You want wall-clock parallelism. | You want deterministic, sequential output. |

---

## Quick start

```python
from shipit_agent import Goal
from shipit_agent.autopilot import Autopilot, BudgetPolicy

autopilot = Autopilot(
    llm=llm,
    goal=Goal(objective="fanout-parent", success_criteria=["done"]),
    budget=BudgetPolicy(max_seconds=600, max_iterations=6, max_tool_calls=30, max_dollars=3.0),
)

result = autopilot.fanout(
    items=["PR-101", "PR-102", "PR-103", "PR-104"],
    objective_template="Summarize {item} — what changed, what's risky.",
    criteria_template=["Mentions the main change", "Lists one risk"],
    max_parallel=4,
    child_budget_frac=0.25,
)

print(f"{result.status} · wall {result.wall_seconds:.1f}s")
for c in result.children:
    print(c["run_id"], c["status"], c["iterations"])
```

---

## Budget scaling — the safety model

A fan-out can burn budget fast. To keep aggregate spend bounded,
**every child inherits a scaled slice** of the parent budget:

```
child_budget = parent_budget * child_budget_frac
```

For the default `child_budget_frac=0.2`, a 10-item fan-out with the
parent capped at 30 min lets each child run up to 6 min. With
`max_parallel=10`, the wall-clock ceiling is ~6 min too.

Tighter global cap? Lower the fraction:

```python
autopilot.fanout(
    items=big_list,
    objective_template="...",
    max_parallel=20,
    child_budget_frac=0.05,            # each child gets 5% of parent
)
```

---

## Streaming variant — `fanout_stream()`

For a live dashboard over a 50-item run, the streaming version yields
one event per child as it completes:

```python
for ev in autopilot.fanout_stream(
    items=[f"case-{i}" for i in range(50)],
    objective_template="review {item}",
    max_parallel=10,
    child_budget_frac=0.1,
):
    if ev["kind"] == "autopilot.fanout_child":
        print(f"done: {ev['item_index']} → {ev['status']}")
    elif ev["kind"] == "autopilot.fanout_result":
        print(f"total: {ev['status']} across {len(ev['children'])} children")
```

### Event kinds

| Event | Payload |
| --- | --- |
| `autopilot.fanout_started` | `parent_run_id`, `items` (first 50), `total`, `child_budget`, `max_parallel` |
| `autopilot.fanout_child` | `item_index`, `run_id`, `status`, `iterations`, `halt_reason` |
| `autopilot.fanout_result` | the full `FanoutResult` payload |

---

## Custom aggregation

By default, the `aggregated_output` is a markdown digest of every
child. Pass your own `aggregator` to reshape:

```python
def top_wins(children):
    completed = [c for c in children if c.status == "completed"]
    return "\n---\n".join(c.output for c in completed[:5])

result = autopilot.fanout(
    items=accounts,
    objective_template="Research {item} and pitch one use case",
    aggregator=top_wins,
)
print(result.aggregated_output)
```

Aggregator receives `list[AutopilotResult]` (not dicts) and returns
`str`.

---

## The `FanoutResult` shape

```python
FanoutResult(
    parent_run_id="fanout-1713710400",
    objective_template="Review {item}",
    status="completed",                    # rollup: completed | partial | failed
    children=[                             # one dict per child, sorted by run_id
        {"run_id": "...", "status": "completed", "iterations": 3, "output": "..."},
        ...
    ],
    aggregated_output="...",               # markdown digest by default
    wall_seconds=42.7,
    failed=[],                             # run_ids that ended in 'failed'
)
```

Status rollup rules:
- **`completed`** — every child completed.
- **`partial`** — at least one completed, at least one didn't.
- **`failed`** — every child failed (rare; usually means the LLM is down).

---

## Combining with critic + artifacts

Every Autopilot feature composes. A common pattern is a "nightly batch
with deliverables":

```python
parent = Autopilot(
    llm=llm,
    goal=Goal(objective="nightly", success_criteria=["per-item digest"]),
    budget=BudgetPolicy(max_seconds=3600, max_tool_calls=200, max_dollars=10.0),
    critic=True,                           # each child gets a critic
    artifacts=True,                        # each iteration's code/md captured
)

result = parent.fanout(
    items=yesterday_merged_prs,
    objective_template="Write a ## heading + one-paragraph summary of {item}.",
    criteria_template=["Starts with ## heading", "One paragraph"],
    max_parallel=8,
    child_budget_frac=0.12,
)
```

Each child has its own critic verdict in `child.critic_verdict` and
its own artifact list. `result.aggregated_output` is a single
deliverable you can email / paste into Slack.

---

## API reference

```text
def Autopilot.fanout(
    self,
    items: list[Any],
    *,
    objective_template: str,
    criteria_template: list[str] | None = None,
    max_parallel: int = 5,
    child_budget_frac: float = 0.2,        # clamped to [0.05, 1.0]
    aggregator: Callable[[list[AutopilotResult]], str] | None = None,
    parent_run_id: str | None = None,
) -> FanoutResult: ...


def Autopilot.fanout_stream(...) -> Iterator[dict]: ...
```

Each child is a fresh Autopilot — mutations to the parent during
fan-out are **not** propagated. Tools, mcps, hooks, and agent kwargs
are copied by reference at dispatch time.

---

## Notebook

- `notebooks/43_fanout_critic_artifacts.ipynb` — focused walkthrough.
- `notebooks/44_complete_tour.ipynb` — fan-out in context with every
  other feature.
