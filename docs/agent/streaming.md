---
title: Agent — Streaming
description: Real-time event streaming from shipit_agent.Agent — event types, terminal renderers, SSE and WebSocket transports.
---

# Agent — Streaming

`agent.stream(prompt)` is a generator that yields `AgentEvent`s the
**instant** they're emitted. There is no buffering: each `tool_called`
event arrives before the tool runs, each `tool_completed` arrives the
moment the tool returns, and `run_completed` is the very last event.

## Event types

| Type | Emitted when | Useful payload fields |
| --- | --- | --- |
| `run_started` | The agent receives a user prompt | `prompt` |
| `step_started` | The runtime begins an LLM iteration | `iteration`, `tool_count` |
| `reasoning_started` | The model surfaces a thinking block | `iteration` |
| `reasoning_completed` | The thinking block is finalised | `content` |
| `planning_started` | Auto-planner is invoked | — |
| `planning_completed` | Planner output is ready | `plan` |
| `tool_called` | A tool is about to run | `tool_name`, `arguments` |
| `tool_completed` | A tool returned successfully | `tool_name`, `metadata`, `output` |
| `tool_failed` | A tool raised | `tool_name`, `error` |
| `interactive_request` | The agent needs the human to answer | `question`, `options` |
| `mcp_attached` | An MCP server has been wired in | `server_name` |
| `llm_retry` | The LLM call is being retried | `attempt`, `error` |
| `tool_retry` | A tool call is being retried | `attempt`, `error` |
| `context_snapshot` | Token usage update | `usage`, `compaction_ratio` |
| `rag_sources` | RAG sources captured during the run | `sources` |
| `run_completed` | The run is over | `output`, `iterations` |

See the [Event Types reference](../reference/events.md) for the
complete schema.

---

## Minimal example

```python
for event in agent.stream("Search the web for SQLite news"):
    print(f"[{event.type}] {event.message}")
```

---

## Coloured terminal renderer

```python
RESET = "\033[0m"
DIM   = "\033[2m"
BOLD  = "\033[1m"
CYAN  = "\033[36m"
GREEN = "\033[32m"
YELL  = "\033[33m"

for event in agent.stream("Find today's BTC price"):
    if event.type == "run_started":
        print(BOLD + "🚀 run started" + RESET)
    elif event.type == "step_started":
        print(DIM + f"  · iter {event.payload.get('iteration')}" + RESET)
    elif event.type == "reasoning_started":
        print(YELL + "  🧠 thinking…" + RESET)
    elif event.type == "reasoning_completed":
        print(YELL + "  🧠 " + event.payload.get('content', '')[:80] + RESET)
    elif event.type == "tool_called":
        print(CYAN + "  ▶ " + event.message + RESET)
    elif event.type == "tool_completed":
        print(GREEN + "  ✓ " + event.message + RESET)
    elif event.type == "rag_sources":
        for s in event.payload.get("sources", []):
            print(DIM + f"    📎 [{s['index']}] {s['source']}" + RESET)
    elif event.type == "run_completed":
        print(BOLD + "✅ done" + RESET)
        print((event.payload.get('output') or '')[:300])
```

`examples/02_streaming_with_reasoning.py` ships a more polished
version of this you can copy verbatim.

---

## Server-Sent Events (SSE)

For web UIs, every event has a built-in SSE encoder
(`shipit_agent.packets.sse_event_packet`):

```python
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

from shipit_agent import Agent
from shipit_agent.packets import sse_event_packet, sse_result_packet

app = FastAPI()
agent = Agent.with_builtins(llm=llm)

@app.get("/stream")
async def stream(q: str):
    def gen():
        for event in agent.stream(q):
            yield sse_event_packet(event)
        # Final marker — useful for clients that watch for `event: done`
        yield "event: done\ndata: {}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")
```

The browser side reads it with `EventSource("/stream?q=…")` and renders
events as they arrive.

---

## WebSocket

```python
from shipit_agent.packets import websocket_event_packet

@app.websocket("/ws")
async def ws(websocket):
    await websocket.accept()
    user_msg = await websocket.receive_text()
    for event in agent.stream(user_msg):
        await websocket.send_json(websocket_event_packet(event))
```

`websocket_event_packet` returns a JSON-friendly dict; pair it with
`send_json` for a clean transport.

---

## Streaming inside a chat session

`AgentChatSession.stream` mirrors `Agent.stream` but also persists each
turn to the session store:

```python
session = agent.chat_session(session_id="user-42")

for event in session.stream("Hi, what can you do?"):
    print(event.message)

# Next turn — same session, same history
for event in session.stream("Search the web for SQLite news"):
    print(event.message)
```

Subscribe to events programmatically with `session.add_event_callback`
or `session.add_packet_callback` if you want a callback API instead of
a generator.

---

## Stopping a stream

A `for event in agent.stream(...):` loop can be exited with `break` —
the runtime cleans up the background thread automatically. For
explicit cancellation from another thread, raise `StopIteration` or
close the generator (`stream.close()`).

---

## See also

- [Examples](examples.md) — every snippet you can copy
- [Event Types reference](../reference/events.md)
- [Packets module](../reference/architecture.md) — SSE / WebSocket helpers
- [Streaming guide](../guides/streaming.md) — deeper background on the runtime
