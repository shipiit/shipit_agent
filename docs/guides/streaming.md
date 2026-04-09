# Streaming Events

`agent.stream()` yields `AgentEvent` objects as the runtime executes. Under the hood, the agent runs on a background thread and pushes events through a thread-safe queue, so **every event reaches your loop the instant it's emitted** — no buffering, no batched delivery.

## Basic usage

```python
from shipit_agent import Agent
from examples.run_multi_tool_agent import build_llm_from_env

agent = Agent.with_builtins(llm=build_llm_from_env('openai'))

for event in agent.stream("Find today's Bitcoin price in USD."):
    print(f"{event.type:22s} {event.message}")
```

## Event reference

| Event type | When it fires | Key payload fields |
|---|---|---|
| `run_started` | Very first event of a run, once per `stream()`/`run()` call. | `prompt` |
| `mcp_attached` | Once per attached MCP server, right after `run_started`. | `server` |
| `planning_started` | Router policy decided the prompt is complex enough to invoke `plan_task`. Fires **before** the first LLM call. | `prompt` |
| `planning_completed` | Planner returned. Output is injected into history as a `user`-role context message (Bedrock tool-pairing safe). | `output` |
| `step_started` | Each iteration of the tool loop, right before calling the LLM. | `iteration`, `tool_count` |
| `reasoning_started` | 🧠 LLM response contained a thinking/reasoning block. | `iteration` |
| `reasoning_completed` | Immediately after `reasoning_started`, carrying the full reasoning text. | `iteration`, `content` |
| `tool_called` | Model decided to call a tool. Fires **before** execution. | `iteration`, `arguments` |
| `tool_completed` | Tool finished successfully. | `iteration`, `output` |
| `tool_retry` | Transient tool failure, retry scheduled by `RetryPolicy`. | `iteration`, `attempt`, `error` |
| `tool_failed` | Non-retryable tool error, **or** model hallucinated an unregistered tool name (synthetic error result still appended for pairing balance). | `iteration`, `error` |
| `llm_retry` | Transient LLM provider error, retry scheduled. | `attempt`, `error` |
| `interactive_request` | A tool returned `metadata.interactive=True` (e.g. `ask_user`, human review). UI can pause and collect input. | `kind`, `payload` |
| `run_completed` | Final event. Fires once the loop exits or hits the iteration cap. | `output`, `content`, `format` |

## Event structure

```python
@dataclass
class AgentEvent:
    type: str                # e.g. "tool_called"
    message: str             # human-readable, e.g. "Tool called: web_search"
    payload: dict[str, Any]  # event-specific fields
```

Serialize with `event.to_dict()` for WebSocket/SSE transport.

## Typical event trace

A Bedrock `gpt-oss-120b` run with two tool calls:

```
1.  run_started          Agent run started
2.  step_started         iteration=1, tool_count=28
3.  reasoning_started    🧠 iteration=1
4.  reasoning_completed  🧠 "The user wants two BTC price sources. I'll start with web_search..."
5.  tool_called          Tool called: web_search
6.  tool_completed       Tool completed: web_search
7.  step_started         iteration=2
8.  reasoning_completed  🧠 "Now I'll open both URLs to confirm..."
9.  tool_called          Tool called: open_url
10. tool_completed       Tool completed: open_url
11. tool_called          Tool called: open_url
12. tool_completed       Tool completed: open_url
13. step_started         iteration=3
14. reasoning_completed  🧠 "Both sources agree within $40..."
15. run_completed        "**Bitcoin Price — 2026-04-09** ..."
```

## Live UI updates in Jupyter

```python
from IPython.display import Markdown, clear_output, display

lines = []
for event in agent.stream(prompt):
    lines.append(f"{event.type} — {event.message}")
    clear_output(wait=True)
    display(Markdown("## Live Stream\n\n" + "\n".join(lines)))
```

Uses `clear_output(wait=True) + display(...)` for reliable incremental rendering in Jupyter, VS Code, and JupyterLab.

## WebSocket/SSE packet transports

```python
session = agent.chat_session(session_id='demo')

for packet in session.stream_packets("Research Bitcoin", transport='websocket'):
    print(packet)   # serialized AgentEvent dict

for packet in session.stream_packets("Research Bitcoin", transport='sse'):
    print(packet)   # SSE-formatted string
```

Both transports yield packets incrementally — no buffering.

## Error handling

Errors raised during the run (LLM provider exceptions, non-retryable tool failures) are captured on the background worker thread and **re-raised on the consumer thread** when the stream terminates. Nothing gets silently swallowed.

```python
try:
    for event in agent.stream(prompt):
        ...
except RuntimeError as exc:
    print("Agent run failed:", exc)
```

## Related

- [Reasoning guide](reasoning.md) — how reasoning events are extracted from providers
- [Event types reference](../reference/events.md) — full payload schemas
