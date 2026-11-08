---
title: Agent — Verifier Network
description: Process supervision for agent runs. A second cheap LLM vetoes hallucinated tool calls before they fire and detects when the main agent is stalling. Catches whole classes of failures that observability alone can't fix.
---

# Agent — Verifier Network

A second, typically cheap LLM (Haiku, gpt-oss-20b) sits next to your
main agent and answers two questions:

1. **"Should this tool call actually run?"** — before each tool fires.
2. **"Are we making progress?"** — after each iteration.

Both checks are opt-in, both fail open (verifier failures never block
the main agent), and both ship with hard caps so the verifier can't
itself become a runaway cost.

> **TL;DR** — `Agent(verifier=VerifierNetwork(llm=cheap_llm))` and your
> agent now has process supervision. Hallucinated tools get vetoed,
> stalling agents get nudged. ~$0.005 per agent run on Haiku.

---

## Why this matters

Most agent debugging today is post-hoc: you read traces *after* the
agent burned $20 on the wrong tool. Process supervision prevents the
failure mode in the first place.

Three kinds of failure that the verifier catches:

1. **Hallucinated tool names / args** — model invents
   `delete_all_files()`, verifier vetoes, agent re-plans.
2. **Wrong-target actions** — model calls
   `send_message(channel='#general', text='...')` when the goal said
   "draft only", verifier vetoes.
3. **Stalling** — model loops calling the same tool with tiny
   variations. Progress score drops below threshold for N iterations,
   nudge gets injected: "you're stuck — try a different angle".

LangGraph's `ToolNode` has no per-call gating. LangChain's
`RunnableWithMessageHistory` has no progress detector. **Process
supervision in shipit is one constructor argument.**

---

## Quickstart

```python
from shipit_agent import Agent
from shipit_agent.verifier import VerifierNetwork, VerifierConfig

verifier = VerifierNetwork(
    llm=cheap_llm,                                  # Haiku, gpt-oss-20b, etc.
    config=VerifierConfig(
        veto_enabled=True,
        progress_enabled=True,
        veto_min_confidence=0.6,
        progress_threshold=0.4,
        progress_window=3,
    ),
    goal="Audit security of merged PRs from this week.",
)

agent = Agent(
    llm=opus_llm,                                   # main agent (expensive)
    tools=[GitHubTool(), GrepSearchTool(), FileReadTool()],
    verifier=verifier,
)

result = agent.run("Run the audit.")

# Telemetry — how often the verifier acted
print(verifier.stats.pretool_veto)         # vetoes triggered
print(verifier.stats.pretool_rewrite)      # arg-fix interventions
print(verifier.stats.nudges_injected)      # progress-stall nudges
```

That's the whole API. The verifier auto-wraps every tool the agent
sees; the wrapper is transparent to the runtime.

---

## Pre-tool veto — full control flow

```
Agent decides to call tool                                              │
         ↓                                                              │
verifier.check_tool(name, args, recent_history)                         │
         ↓                                                              │
verifier LLM responds: {"verdict": "...", "reason": "...",              │
                        "confidence": 0.0-1.0, "new_args": ...}         │
         ↓                                                              │
verdict ALLOW   → tool runs unchanged                                   │
verdict VETO    → tool DOES NOT run; synthetic error tool-result        │
                  returned to agent ("[verifier-veto] ...")             │
                  → agent sees the error → re-plans                     │
verdict REWRITE → tool runs with `new_args`                             │
                                                                        │
confidence < veto_min_confidence → downgraded to ALLOW (avoid           │
                                  over-blocking on uncertain calls)
```

### Example trace

User goal: *"Send a friendly reminder to the QA team about Friday's release."*

| Iteration | Tool call | Verifier verdict | What happens |
| --- | --- | --- | --- |
| 1 | `slack_search(query='QA channel')` | `allow` (0.95) | Runs |
| 2 | `slack_send(channel='#engineering', text='...')` | `veto` (0.92, "wrong channel; user said QA team") | Synthetic error returned to agent |
| 3 | `slack_send(channel='#qa', text='...')` | `allow` (0.91) | Runs successfully |

Without the verifier, the agent would have posted the wrong message
to the wrong channel.

---

## Progress check — full control flow

```
After each agent iteration:                                             │
                                                                        │
verifier.evaluate_step(last_step_summary, recent_history)               │
         ↓                                                              │
verifier LLM responds: {"score": 0.0-1.0, "summary": "...",             │
                        "suggested_action": "..." or null}              │
         ↓                                                              │
score recorded → if score < progress_threshold: streak++                │
                else:                            streak = 0             │
         ↓                                                              │
verifier.maybe_nudge(last_check)                                        │
         ↓                                                              │
streak >= progress_window?                                              │
   yes → return {"role": "user", "content": "[progress-check] ..."}     │
         caller appends to messages → agent sees nudge → resets streak  │
   no  → return None
```

### Example trace

| Iteration | Score | Streak | Nudge |
| --- | --- | --- | --- |
| 1 | 0.7 | 0 | — |
| 2 | 0.3 | 1 | — |
| 3 | 0.2 | 2 | — |
| 4 | 0.2 | 3 | **fired** ("you're stalling — try grep instead of read_file") |
| 5 | 0.6 | 0 | — (streak reset) |

The nudge appears in the conversation as a regular user message; the
agent treats it like any other instruction.

---

## Configuration deep dive

```python
from shipit_agent.verifier import VerifierConfig

VerifierConfig(
    # Pre-tool veto
    veto_enabled=True,                  # disable to skip verifier on tool calls
    veto_min_confidence=0.6,            # downgrade verdicts below this to ALLOW

    # Progress check
    progress_enabled=True,              # disable to skip per-iteration checks
    progress_threshold=0.4,             # below = no progress
    progress_window=3,                  # consecutive sub-threshold → nudge

    # Hard caps so the verifier itself can't run away
    max_pretool_calls_per_run=50,
    max_progress_calls_per_run=30,
)
```

| Setting | Lower values mean | Higher values mean |
| --- | --- | --- |
| `veto_min_confidence` | More vetoes (some false positives) | Fewer vetoes (some false negatives) |
| `progress_threshold` | More tolerant of slow steps | Faster nudge on slow steps |
| `progress_window` | Faster nudge | More confidence before nudging |
| `max_pretool_calls_per_run` | Cheaper, less coverage | More expensive, full coverage |

Production defaults assume Haiku-tier verifier and Opus-tier main agent.
Adjust if your main agent is also small (you may want a tighter
threshold) or if calls are very expensive (you may want lower caps).

---

## Cost analysis

Per 100-iteration agent run with the defaults:
* **Pre-tool calls** — capped at 50, ~250 input tokens each → **12.5K tokens**
* **Progress calls** — capped at 30, ~300 input tokens each → **9K tokens**
* **Output** — verifier responses are tiny (~50 tokens), so ~80 × 50 = **4K tokens**
* **Total** — ~25K tokens. On Haiku ($0.25 / $1.25 per Mtok), **~$0.005 / run.**

If your main agent costs $1+ per run on Opus, the verifier is a 0.5%
overhead. The first time it vetoes a destructive action, it's already
paid back its cost a hundred times over.

---

## Standalone use

You can use either component without the other:

### Veto only — wrap individual tools

```python
from shipit_agent.verifier import PreToolVerifier, wrap_tool_with_verifier

veto = PreToolVerifier(llm=cheap_llm)
safe_rm = wrap_tool_with_verifier(my_rm_tool, veto, goal="cleanup tmp files")

# Now `safe_rm.run(...)` calls the verifier first.
```

### Progress only — long-running custom loops

```python
from shipit_agent.verifier import ProgressVerifier

progress = ProgressVerifier(llm=cheap_llm)
goal = "Refactor the auth module"

for i, step in enumerate(my_custom_loop()):
    check = progress.evaluate(goal=goal, last_step_summary=step.summary)
    print(f"step {i} score: {check.score}")
    nudge = progress.maybe_nudge(check)
    if nudge:
        print("ALERT — agent stalling:", nudge["content"])
        # inject the nudge into your loop's conversation
```

---

## When NOT to use it

* **Single-tool runs** — the veto adds latency without much upside
  on simple "run this one tool" tasks.
* **Strict-real-time agents** — verifier adds ~200-400ms per tool
  call.
* **Cost-bound runs <$0.01** — the 0.5% overhead becomes a real
  fraction at the very low end.

For everything else (research, code generation, long-horizon agents,
production tools that touch real systems), turn it on by default.

---

## Combining with other features

### With Autopilot
```text
from shipit_agent import Goal
from shipit_agent.autopilot import Autopilot, BudgetPolicy

autopilot = Autopilot(
    llm=opus_llm,
    goal=Goal(objective="...", success_criteria=[...]),
    budget=BudgetPolicy(max_dollars=50, max_seconds=86400),
    verifier=VerifierNetwork(llm=haiku_llm, ...),
)
```

When Autopilot is the orchestrator, the verifier shines — it catches
the failure modes that overnight runs are most exposed to (hallucinated
tools, infinite loops on a stuck subgoal).

### With DeepAgent
```text
from shipit_agent import create_deep_agent

deep = create_deep_agent(
    llm=opus_llm,
    rag=my_rag,
    verify=True,
    reflect=True,
    verifier=VerifierNetwork(llm=haiku_llm, ...),
)
```

DeepAgent's verify/reflect run after the answer; the verifier runs
during. Both belt-and-suspenders.

---

## API reference

### `VerifierNetwork`
```text
VerifierNetwork(
    *, llm,                              # the verifier LLM
    config: VerifierConfig | None = None,
    goal: str = "",                      # human-readable, used in pre-tool prompts
)
```

| Method | Returns | Use |
| --- | --- | --- |
| `wrap_tools(tools)` | `list[Tool]` | Wrap tools so each call goes through veto. |
| `check_tool(...)` | `PreToolDecision` | Manual veto check (use this if you compose your own runtime). |
| `evaluate_step(...)` | `ProgressCheck` | Score one iteration. |
| `maybe_nudge(check)` | `dict \| None` | Returns a user-message dict if nudge fired, else `None`. |
| `reset()` | `None` | Clear per-run state between independent runs. |
| `.stats` | `VerifierStats` | Telemetry — calls, verdicts, nudges. |

### `VerifierVerdict`
Enum: `ALLOW` / `VETO` / `REWRITE`.

### `PreToolDecision`
| Field | Type | Description |
| --- | --- | --- |
| `verdict` | `VerifierVerdict` | The decision. |
| `reason` | `str` | Human-readable rationale (surfaced on veto/rewrite). |
| `new_args` | `dict \| None` | When verdict is REWRITE, the modified args. |
| `confidence` | `float` | 0..1; below `veto_min_confidence` → downgraded. |

### `ProgressCheck`
| Field | Type | Description |
| --- | --- | --- |
| `score` | `float` | 0..1; below `progress_threshold` counts toward nudge streak. |
| `summary` | `str` | Short rationale. |
| `suggested_action` | `str \| None` | Optional hint surfaced in the nudge. |

---

## Going deeper

* [Structured output](../guides/structured-output.md) — typed results with
  validation retry; pairs naturally with the verifier
* [Autopilot overview](../autopilot/index.md) — long-running budgeted
  agent runs that benefit most from process supervision
* [DeepAgent → Reflective Agent](../deep-agents/reflective-agent.md) —
  post-hoc self-critique; complementary to the in-loop verifier
