---
title: Time-Travel Replay
description: Load any saved trace, fork from any event, edit the prompt, and resume on a fresh agent. Side-by-side diff between two traces. Replay.io for AI agents — open, in-memory, no SaaS required.
---

# Time-Travel Replay

Agent debugging today is brutal: you read 2000 lines of logs and guess
what went wrong. **Time-travel replay** turns it into "click the bad
step, fork, try a different prompt, see if it works".

Three things you get:

1. **Inspect** — load any `TraceRecord` and walk events programmatically.
2. **Fork** — pick any event, capture the conversation state up to there,
   optionally edit the user prompt at the fork.
3. **Resume** — feed the checkpoint to a fresh `Agent.run()` to continue
   from the fork point.

Plus a `diff_traces()` helper for side-by-side comparison of two runs.

Whole thing is **pure Python** — no extra dependencies, works against the
existing `FileTraceStore` / `InMemoryTraceStore`.

> **TL;DR** —
> ```python
> replayer = TraceReplayer.from_store(store, trace_id='abc')
> fork = replayer.fork(at_event=12, edit_user_message='Try a narrower question.')
> result = fork.continue_from(agent=fresh_agent)
> ```

---

## Why this matters

The closest equivalents in the LLM tooling space are LangSmith's
"playground" and Inngest's branching — both proprietary, both SaaS-only.
Ours is library-level, open-source, and works against the trace store
**you already have**.

Three failure modes time-travel solves cleanly:

1. **"Why did the agent pick that tool?"** — fork before the call,
   change the prompt, re-run. See if a clearer prompt produces a better
   tool choice.
2. **"What if I'd used Opus instead of Sonnet at step 5?"** — fork, swap
   the LLM on the resumed agent, diff the result.
3. **"This run from yesterday failed — was it the data or the prompt?"**
   — fork at the failure point, vary one thing at a time, build a small
   matrix of replayed runs.

---

## Quick start

```python
from shipit_agent.replay import TraceReplayer
from shipit_agent.tracing import FileTraceStore

# 1. Load a saved trace
store = FileTraceStore('./traces')
replayer = TraceReplayer.from_store(store, trace_id='run-2026-05-09-abc')

# 2. Inspect — find every tool call
tool_indices = replayer.event_indices_by_type('tool_called')
for i in tool_indices:
    ev = replayer.events[i]
    print(f"event {i}: {ev.payload.get('tool')}")

# 3. Fork before the third tool call, with a tweaked prompt
fork = replayer.fork(
    at_event=tool_indices[2],
    edit_user_message='Try answering without searching the web first.',
)

# 4. Resume on a fresh agent
from shipit_agent import Agent
result = fork.continue_from(agent=Agent(llm=my_llm))

print(result.output)
```

---

## Loading traces — three ways

```python
# From an in-memory or file-backed store
TraceReplayer.from_store(store, trace_id='abc')

# Already-loaded record
TraceReplayer.from_record(record)

# Direct JSON file (FileTraceStore format)
TraceReplayer.from_file('./traces/run-abc.json')
```

The `TraceReplayer` accepts the same JSON shape `FileTraceStore` writes,
so anything written through the standard tracing pipeline can be replayed
with no extra plumbing.

---

## Inspection API

```python
replayer.trace_id                                # 'run-abc'
replayer.events                                  # list[AgentEvent]
replayer.metadata                                # dict carried with the trace
len(replayer)                                    # number of events

# Find events by type — useful for tool-call analysis
replayer.event_indices_by_type('tool_called')    # → [3, 7, 12]
replayer.event_indices_by_type('tool_completed') # → [4, 8, 13]

# Reconstruct messages as they existed at any point
replayer.messages_at(event_index=12)             # list[Message]

# All user messages with their event indices
replayer.find_user_messages()                    # → [(0, 'first prompt'), ...]
```

`messages_at(N)` walks events 0..N inclusive, accumulating any messages
embedded in payloads — `run_started` user prompts, `tool_completed`
results, `run_completed` outputs. Tolerant of payload schema variation;
events without message data are skipped silently.

---

## Forking

```python
fork = replayer.fork(
    at_event=12,                            # 0-indexed event to fork at
    edit_user_message='Try a narrower question.',  # optional
    extra_metadata={'reason': 'debug-1'},   # merged into checkpoint metadata
)
# returns a ReplayCheckpoint
```

Two fork modes:

| Mode | What happens |
| --- | --- |
| `edit_user_message=None` | Resume continues from the original prompt — use this to "re-run from this point with no changes" (e.g. retry a flaky tool). |
| `edit_user_message='...'` | Replace the most recent user message with your new text. The trailing user message is dropped from history so the agent sees the new prompt as a fresh turn. |

The `ReplayCheckpoint` is a snapshot — independent of the original
`TraceReplayer`. You can hold many forks side-by-side and resume them
in any order.

---

## Resuming

```python
result = fork.continue_from(agent=fresh_agent, max_validation_retries=2)
```

`continue_from()`:

1. Pre-fills `agent.history` with the reconstructed messages.
2. Calls `agent.run(user_prompt, **kwargs)`.
3. Returns a `ReplayResult` bundling the agent result + the fork metadata.

You can pass any `Agent.run()` kwarg through — `output_schema=`,
`max_validation_retries=`, etc.

Every replay records its own `ForkPoint` (source trace ID + event index +
edits applied), so the lineage is preserved as you build a tree of
explorations.

---

## Diffing two traces

```python
from shipit_agent.replay import diff_traces

d = diff_traces(baseline_replayer, fork_replayer)

if d.identical:
    print("Same behaviour — your edit had no effect.")
else:
    print(f"Diverged at event {d.diverged_at}")
    print(f"  matched events: {d.matched}")
    print(f"  type mismatches: {len(d.type_mismatches)}")
    for line in d.to_lines():
        print(line)
```

The diff walks both event lists in order. As soon as event types disagree,
every later event is reported under `only_in_left` / `only_in_right`. The
`to_lines()` method renders a human-readable summary capped at a configurable
line count.

---

## Concrete debugging recipe

Suppose your nightly autopilot run failed at iteration 14. The trace is
saved as `run-2026-05-09-abc.json`. Walk through:

```python
replayer = TraceReplayer.from_file('./traces/run-2026-05-09-abc.json')

# 1. What was the last tool that ran successfully?
tool_completes = replayer.event_indices_by_type('tool_completed')
print(f"last successful tool at event {tool_completes[-1]}")

# 2. What did the agent see right before the failure?
last_good = tool_completes[-1]
context = replayer.messages_at(last_good)
print(f"history at fork point: {len(context)} messages")

# 3. Fork there with a more constrained prompt
fork = replayer.fork(
    at_event=last_good,
    edit_user_message=(
        "We've already gathered the data we need — "
        "don't search the web again. Just produce the report."
    ),
)

# 4. Resume on a fresh agent
from shipit_agent import Agent
result = fork.continue_from(agent=Agent(llm=opus_llm, tools=[ReportTool()]))

# 5. Compare to baseline
baseline = TraceReplayer.from_file('./traces/run-2026-05-09-abc.json')
fresh = TraceReplayer.from_record(result.agent_result.events_as_record())
print('\n'.join(diff_traces(baseline, fresh).to_lines()))
```

This turns "rerun from yesterday's logs and tweak one thing" from a
~30-minute manual exercise into a 5-line script.

---

## What this beats

| Tool | Time-travel? | Open / self-host? | Library-level API? |
| --- | --- | --- | --- |
| LangSmith | Playground (separate UI) | ❌ SaaS only | ❌ |
| Inngest | Branching | ❌ SaaS only | ❌ |
| OpenTelemetry traces | View only | ✅ | ❌ (read-only) |
| **shipit_agent.replay** | ✅ fork from any event | ✅ pure Python | ✅ |

Replay.io for AI agents. Yours.

---

## API reference

### `TraceReplayer`
```text
TraceReplayer(record: TraceRecord)
TraceReplayer.from_record(record)
TraceReplayer.from_store(store, trace_id)
TraceReplayer.from_file(path)
```

| Property / Method | Returns | Notes |
| --- | --- | --- |
| `.trace_id` | `str` | The source trace ID. |
| `.events` | `list[AgentEvent]` | Defensive copy. |
| `.metadata` | `dict` | Defensive copy. |
| `len(...)` | `int` | Number of events. |
| `.event_indices_by_type(t)` | `list[int]` | Indices where `event.type == t`. |
| `.messages_at(event_index)` | `list[Message]` | Reconstructed history up to (and including) that event. |
| `.find_user_messages()` | `list[(int, str)]` | All user messages with their event indices. |
| `.fork(*, at_event, edit_user_message=None, extra_metadata=None)` | `ReplayCheckpoint` | Capture a fork point. |
| `.to_dict()` | `dict` | Round-trips with `from_file`. |

### `ReplayCheckpoint`
| Field / Method | Notes |
| --- | --- |
| `.fork: ForkPoint` | Lineage info (source ID, event, edits). |
| `.messages: list[Message]` | Reconstructed history at the fork point. |
| `.user_prompt: str` | What to feed `agent.run(prompt=)`. |
| `.metadata: dict` | Carry-over from the source trace. |
| `.continue_from(*, agent, **run_kwargs)` | Run the agent from this state. |

### `diff_traces(left, right) → TraceDiff`
| `TraceDiff` field | Notes |
| --- | --- |
| `.matched` | Count of events that paired up by type. |
| `.diverged_at` | First event index where types disagreed (or where one trace ended). |
| `.type_mismatches` | `[(idx, left_type, right_type), ...]`. |
| `.only_in_left` / `.only_in_right` | Events past the common length. |
| `.identical` | True iff matched = max length, no mismatches. |
| `.to_lines(limit=40)` | Human-readable rendering. |

---

## Going deeper

* [Agent → Tracing](./tracing.md) — how the underlying `TraceStore`
  records events
* [Reference → Events](../reference/events.md) — full event taxonomy
* [Verifier network](./verifier.md) — process supervision in the
  *forward* direction; replay is the backwards complement
