---
title: Agent — Tracing
description: Record, inspect, and visualise every step of an agent run with FileTraceStore, InMemoryTraceStore, and TraceRecord.
---

# Agent — Tracing

Tracing captures every `AgentEvent` emitted during a run — tool calls,
reasoning, retries, planning, and the final output — into a persistent
store you can reload and inspect later.

> **Think of it as your local LangSmith.** Each trace is a complete
> timeline of one agent run, stored as structured JSON you can query,
> visualise, or ship to any observability backend.

---

## Quick start

```python
from shipit_agent import Agent, FileTraceStore

agent = Agent.with_builtins(
    llm=llm,
    trace_store=FileTraceStore(root_dir=".shipit_traces"),
    trace_id="run-001",
)

result = agent.run("Search for Python 3.13 release notes")
```

That's it. Every event is now persisted to
`.shipit_traces/run-001.json`.

---

## Trace stores

| Store | Persistence | Best for |
| --- | --- | --- |
| `InMemoryTraceStore` | In-process only (default) | Tests, throwaway notebooks |
| `FileTraceStore` | One JSON file per trace | Local development, debugging |

Both implement the `TraceStore` protocol:

```python
class TraceStore(Protocol):
    def append_event(
        self, trace_id: str, event: AgentEvent, metadata: dict | None = None
    ) -> None: ...

    def load(self, trace_id: str) -> TraceRecord | None: ...
```

Implement this protocol to back traces on Postgres, S3, or any other
backend.

### FileTraceStore

```python
from shipit_agent import FileTraceStore

store = FileTraceStore(root_dir=".shipit_traces")
# Creates the directory if it doesn't exist.
# Each trace is stored at: .shipit_traces/<trace_id>.json
```

### InMemoryTraceStore

```python
from shipit_agent import InMemoryTraceStore

store = InMemoryTraceStore()
# Lives only in memory — useful for unit tests.
```

---

## Loading and inspecting a trace

```python
from shipit_agent import FileTraceStore

store = FileTraceStore(root_dir=".shipit_traces")
trace = store.load("run-001")

# TraceRecord fields
print(trace.trace_id)    # "run-001"
print(trace.metadata)    # {"session_id": ..., "agent_name": ...}
print(len(trace.events)) # number of events in the run
```

### TraceRecord

```python
@dataclass
class TraceRecord:
    trace_id: str
    metadata: dict[str, Any]           # session_id, agent_name, agent_description
    events: list[AgentEvent]           # every event, in order
```

### Iterate over events

```python
for event in trace.events:
    print(event.type, event.message, event.payload)
```

---

## Pretty-print a trace (LangSmith-style)

Paste this into a notebook cell to get a readable, colour-coded
timeline:

```python
from shipit_agent import FileTraceStore

store = FileTraceStore(root_dir=".shipit_traces")
trace = store.load("run-001")

for event in trace.events:
    t = event.type
    p = event.payload

    if t == "run_started":
        print(f"--- Run Started ---")
        print(f"  Prompt: {p.get('prompt', '')}")

    elif t == "step_started":
        iteration = p.get("iteration", "?")
        tools = p.get("tool_count", 0)
        print(f"\n Step {iteration}  ({tools} tools available)")

    elif t == "reasoning_started":
        print(f"  Thinking...")

    elif t == "reasoning_completed":
        content = p.get("content", "")
        print(f"  Thought: {content[:200]}{'...' if len(content) > 200 else ''}")

    elif t == "planning_started":
        print(f"  Planning...")

    elif t == "planning_completed":
        print(f"  Plan: {p.get('output', '')[:200]}")

    elif t == "tool_called":
        print(f"  -> {event.message}")
        args = p.get("arguments", {})
        for k, v in args.items():
            print(f"       {k}: {v}")

    elif t == "tool_completed":
        output = p.get("output", "")
        print(f"  <- {event.message}")
        print(f"       {output[:150]}{'...' if len(output) > 150 else ''}")

    elif t == "tool_failed":
        print(f"  !! FAILED: {p.get('error', '')}")

    elif t == "tool_retry":
        print(f"  ~~ Retry #{p.get('attempt', '?')}: {p.get('error', '')}")

    elif t == "llm_retry":
        print(f"  ~~ LLM retry #{p.get('attempt', '?')}: {p.get('error', '')}")

    elif t == "context_snapshot":
        usage = p.get("usage", {})
        print(f"  Tokens: {usage}")

    elif t == "run_completed":
        usage = p.get("usage", {})
        content = p.get("content", "")
        print(f"\n--- Run Completed ---")
        print(f"  Tokens: {usage.get('prompt_tokens', 0)} in / "
              f"{usage.get('completion_tokens', 0)} out / "
              f"{usage.get('total_tokens', 0)} total")
        if content:
            print(f"  Output: {content[:500]}")
        else:
            print(f"  Output: (empty — check reasoning events above)")

    else:
        print(f"  [{t}] {event.message}")
```

---

## Read the raw JSON

Every trace file is self-contained JSON you can open in any editor or
feed into a visualisation tool:

```python
import json
from pathlib import Path

raw = json.loads(Path(".shipit_traces/run-001.json").read_text())
print(json.dumps(raw, indent=2))
```

The structure:

```json
{
  "trace_id": "run-001",
  "metadata": {
    "session_id": "...",
    "agent_name": "shipit",
    "agent_description": "..."
  },
  "events": [
    {
      "type": "run_started",
      "message": "Agent run started",
      "payload": { "prompt": "Search for Python 3.13 release notes" }
    },
    {
      "type": "tool_called",
      "message": "Tool called: web_search",
      "payload": { "iteration": 1, "arguments": { "query": "..." } }
    }
  ]
}
```

---

## Tracing with streaming

Tracing works with both `agent.run()` and `agent.stream()`. The trace
store receives events in real time as the agent runs:

```python
agent = Agent.with_builtins(
    llm=llm,
    trace_store=FileTraceStore(root_dir=".shipit_traces"),
    trace_id="run-stream-001",
)

# Stream AND trace simultaneously
for event in agent.stream("What is quantum computing?"):
    print(f"[{event.type}] {event.message}")

# After the stream completes, the full trace is on disk
trace = agent.trace_store.load("run-stream-001")  # not available directly
# Use the store you passed in:
store = FileTraceStore(root_dir=".shipit_traces")
trace = store.load("run-stream-001")
print(f"Captured {len(trace.events)} events")
```

---

## Tracing with sessions

Combine `trace_store` with `session_store` to get both conversation
history and per-run execution traces:

```python
from shipit_agent import Agent, FileTraceStore
from shipit_agent import FileSessionStore

agent = Agent.with_builtins(
    llm=llm,
    session_store=FileSessionStore(root_dir=".shipit_sessions"),
    trace_store=FileTraceStore(root_dir=".shipit_traces"),
    trace_id="chat-turn-001",
)

session = agent.chat_session(session_id="user-42")
session.send("What tools do you have?")

# Session store has the conversation history
# Trace store has the execution timeline for this specific run
```

---

## Comparing traces

Load two traces and diff them side by side:

```python
store = FileTraceStore(root_dir=".shipit_traces")

trace_a = store.load("run-001")
trace_b = store.load("run-002")

print(f"Run A: {len(trace_a.events)} events")
print(f"Run B: {len(trace_b.events)} events")

# Compare tool usage
tools_a = [e.message for e in trace_a.events if e.type == "tool_called"]
tools_b = [e.message for e in trace_b.events if e.type == "tool_called"]

print(f"Run A tools: {tools_a}")
print(f"Run B tools: {tools_b}")

# Compare token usage
for trace, name in [(trace_a, "A"), (trace_b, "B")]:
    done = [e for e in trace.events if e.type == "run_completed"]
    if done:
        usage = done[0].payload.get("usage", {})
        print(f"Run {name}: {usage.get('total_tokens', 0)} tokens")
```

---

## List all traces

`FileTraceStore` stores one file per trace. List them with glob:

```python
from pathlib import Path

traces_dir = Path(".shipit_traces")
for path in sorted(traces_dir.glob("*.json")):
    print(path.stem)  # trace_id
```

---

## Cost tracking from traces

Combine tracing with token usage to estimate costs:

```python
MODEL_COSTS = {
    "bedrock/openai.gpt-oss-120b-1:0": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
}

store = FileTraceStore(root_dir=".shipit_traces")
trace = store.load("run-001")

done = [e for e in trace.events if e.type == "run_completed"]
if done:
    usage = done[0].payload.get("usage", {})
    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)

    # Adjust the model key to match yours
    rates = MODEL_COSTS.get("gpt-4o", {"input": 0, "output": 0})
    cost = (
        prompt_tokens / 1_000_000 * rates["input"]
        + completion_tokens / 1_000_000 * rates["output"]
    )
    print(f"Estimated cost: ${cost:.4f}")
```

---

## Custom trace store

Implement the `TraceStore` protocol to send traces anywhere:

```python
from shipit_agent.tracing import TraceStore, TraceRecord
from shipit_agent.models import AgentEvent

class PostgresTraceStore:
    def __init__(self, connection_string: str):
        self.conn_string = connection_string

    def append_event(
        self, trace_id: str, event: AgentEvent, metadata: dict | None = None
    ) -> None:
        # INSERT INTO traces (trace_id, event_type, message, payload, metadata)
        # VALUES (trace_id, event.type, event.message, json(event.payload), json(metadata))
        ...

    def load(self, trace_id: str) -> TraceRecord | None:
        # SELECT * FROM traces WHERE trace_id = ? ORDER BY id
        ...
```

---

## Metadata captured per event

Every event appended to the trace store includes this metadata
automatically:

| Field | Source |
| --- | --- |
| `session_id` | The runtime's session ID |
| `agent_name` | From `Agent(name=...)` |
| `agent_description` | From `Agent(description=...)` |

---

## See also

- [Streaming](streaming.md) — real-time event consumption
- [Event Types reference](../reference/events.md) — full event schema
- [Sessions & Memory](sessions.md) — conversation persistence
- [Hooks & Middleware](../guides/hooks.md) — intercept events programmatically
- [Examples](examples.md) — runnable code snippets
