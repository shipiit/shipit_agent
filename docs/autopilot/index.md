---
title: Autopilot
description: The long-running, goal-driven, budget-gated runtime. Runs until every success criterion is met — or a budget trips. Streams every iteration live, checkpoints every step, resumes cleanly after a crash.
---

# Autopilot

`Autopilot` is the long-running runtime that turns any shipit_agent
`Agent` or `GoalAgent` into a **Claude-Desktop-style autonomous runner**:
goal-driven, budget-gated, checkpointed, and streaming every iteration
as it happens.

> **TL;DR** — `Autopilot(llm=llm, goal=Goal(...), budget=BudgetPolicy(...)).run(run_id="my-run")`
> keeps the inner agent looping until every success criterion is
> satisfied or a budget trip halts it cleanly. Add `critic=True`,
> `artifacts=True`, or `autopilot.fanout(...)` to go further.

---

## What Autopilot adds on top of `GoalAgent`

| Feature | GoalAgent | Autopilot |
| --- | --- | --- |
| Termination | Fixed `max_steps` (20 default) | **Criteria-satisfaction OR budget trip** |
| Budget | Step count only | **Wall-clock · tool calls · tokens · dollars · iters** |
| Crash safety | None | **Atomic JSON checkpoint every iteration** |
| Resume after crash | Not supported | **`autopilot.resume(run_id)`** — picks up where it left off |
| Telemetry | `events` list on result | **`autopilot.stream()` — live event iterator** |
| Reflection | Manual | **Optional built-in `Critic` loop** |
| Deliverables | Single output blob | **`ArtifactCollector` — code / markdown / files** |
| Parallel batches | Manual threading | **`autopilot.fanout(items, template)` — built-in** |
| 24-hour resilience | Not designed for it | **Cumulative budgets, SIGTERM handler, corrupt-checkpoint quarantine** |

---

## Bulletproof for 24-hour runs

Autopilot is designed for runs that outlive their host process. The
stack survives crashes, VM restarts, `systemd stop`, and disk
corruption:

- **Cumulative budgets across resume.** Every field of
  `BudgetUsage` — seconds, tool calls, tokens, dollars, iterations —
  persists in the checkpoint. A run that crashes at hour 12 and
  resumes for another 12 hours trips its 24-hour cap exactly at
  hour 24, not hour 36.
- **Dollar tracking from provider usage.** Token counts from the LLM
  response flow through the built-in pricing table (with Bedrock /
  LiteLLM prefix handling) so `max_dollars` actually fires instead of
  always reading `$0`.
- **Graceful SIGTERM / SIGHUP.** `systemd` and `launchd` send
  `SIGTERM` on service stop. Autopilot catches it alongside `SIGINT`,
  halts at the next iteration boundary, saves a final checkpoint,
  and sets `halt_reason="halted by SIGTERM"`.
- **Corrupt-checkpoint quarantine.** A JSON parse error during
  `load()` renames the bad file to
  `<run_id>.corrupted.<timestamp>.json` instead of silently dropping
  it, so operators can inspect what went wrong.
- **First-iteration heartbeat.** The run emits a heartbeat on
  iteration 1 even before the regular interval elapses, so a slow
  first step never looks like a hang.
- **`remaining` budget on every event.** Stream iteration + heartbeat
  events carry per-axis headroom so a UI can render ETA bars.
- **Thread-safe external stop.** `autopilot.request_stop(reason)`
  halts the loop cleanly from a daemon, a UI, or a signal handler.

Test coverage for these scenarios lives in `tests/test_autopilot_hardening.py`
and `tests/test_autopilot_long_task.py`, plus an opt-in soak gated on
`SHIPIT_AUTOPILOT_SOAK=<seconds>` that drives a real Bedrock LLM for
the requested duration.

---

## Quick start

```python
from shipit_agent import Goal
from shipit_agent.autopilot import Autopilot, BudgetPolicy
from examples.run_multi_tool_agent import build_llm_from_env

llm = build_llm_from_env("bedrock")     # defaults to Llama 4 Scout

autopilot = Autopilot(
    llm=llm,
    goal=Goal(
        objective="Summarize three Python dict gotchas with runnable snippets.",
        success_criteria=[
            "At least 3 gotchas explained in prose",
            "Each gotcha has a Python snippet that reproduces it",
            "A one-line avoidance tip is shown for each",
        ],
    ),
    budget=BudgetPolicy(
        max_seconds=600,                 # 10 min cap
        max_tool_calls=20,
        max_iterations=8,
        max_tokens=300_000,
        max_dollars=2.0,
    ),
)

result = autopilot.run(run_id="py-dict-gotchas")
print(result.status)                    # "completed" | "partial" | "halted" | "failed"
print(result.iterations)
print(result.output[:500])
```

---

## The `BudgetPolicy`

Every cap is **independently honored**. Set any axis to `0` or `None`
to disable it.

| Cap | Default | When it matters |
| --- | --- | --- |
| `max_seconds` | `1800.0` (30 min) | Hard wall-clock ceiling — your 24h runs must opt in by raising this. |
| `max_tool_calls` | `100` | Prevents tool-call storms (a common LLM failure mode). |
| `max_tokens` | `2_000_000` | Coarse token meter. ~$10 on Claude Sonnet 4.5. |
| `max_dollars` | `5.0` | Catches runaway cost. You'll want to override this per run. |
| `max_iterations` | `200` | Safety net against an infinite loop. |

```python
# A conservative overnight run — 8h, ample tool budget, $20 cap.
BudgetPolicy(
    max_seconds=8 * 3600,
    max_tool_calls=2000,
    max_tokens=20_000_000,
    max_dollars=20.0,
    max_iterations=1000,
)
```

A budget trip produces `status="halted"` (no criterion verified) or
`status="partial"` (some satisfied). The `halt_reason` field tells you
which axis tripped.

---

## Status values

| Status | Meaning |
| --- | --- |
| `completed` | Every success criterion verified. |
| `partial` | Some criteria satisfied, then halted (usually budget). |
| `halted` | Budget tripped before any criterion was verified. |
| `failed` | Unhandled exception; the checkpoint captures the crash state. |

---

## Live streaming

```python
for event in autopilot.stream(run_id="py-dict-gotchas"):
    kind = event["kind"]
    if kind == "autopilot.iteration":
        print(f"iter {event['iteration']} — "
              f"{sum(event['criteria_met'])}/{len(event['criteria_met'])} criteria")
    elif kind == "autopilot.result":
        print(f"final: {event['status']}")
```

Full list of event kinds — see [Live streaming](../agent/streaming.md)
and the complete tour notebook `44_complete_tour.ipynb`.

---

## Persistence & resume

Autopilot writes an atomic JSON checkpoint after every iteration to
`~/.shipit_agent/checkpoints/<run_id>.json`. The next call with the
same `run_id` refuses to overwrite unless `resume=True` is passed:

```python
# First run — tiny budget trips, halts partial.
first = Autopilot(..., budget=BudgetPolicy(max_iterations=1)).run(run_id="r1")

# Restart with a bigger budget — picks up at iteration 2.
second = Autopilot(..., budget=BudgetPolicy(max_iterations=6)).resume("r1")
assert second.iterations > first.iterations
```

A crash during save cannot corrupt the checkpoint — we write to a
`.tmp` sibling and `replace()` atomically.

---

## What's in this section

- **[Critic](critic.md)** — reflection loop; terminate the moment criteria are confidently met.
- **[Artifacts](artifacts.md)** — structured deliverables (code, markdown, files) collected during the run.
- **[Fan-out](fanout.md)** — dispatch N children in parallel with a budget-scaled slice each.
- **[Scheduler daemon](scheduler-daemon.md)** — persistent goal queue for 24h operation.
- **[CLI](cli.md)** — `shipit autopilot` / `shipit queue` / `shipit daemon` reference.
- **[Specialists](specialists.md)** — the 47 prebuilt role agents you can hand to any Autopilot.

---

## Full runnable demo — `notebook 37`

Every code block on this page is exercised in
`notebooks/37_autopilot_quickstart.ipynb` against Bedrock Llama 4. Open
it when you want to see output, not just snippets.
