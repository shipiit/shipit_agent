---
title: Streaming
description: Watch a run as it happens, render it in a terminal, notebook or web UI, and stream tool output and answer text.
---

# Streaming

`agent.stream()` runs the same loop as `run()` and yields an event for each step as it happens: the model's responses, every tool call and its output, the answer as it is written, and a summary at the end. The run executes on a background thread and events reach your loop the moment they are emitted.

```python
from shipit_agent import Agent
from shipit_agent.llms import build_llm_from_env

agent = Agent.with_builtins(llm=build_llm_from_env(), project_root=".")

for event in agent.stream("Run the tests and summarise what fails."):
    print(f"{event.type:22} {event.message}")
```

## An event

```python
event.type       # "tool_called"
event.message    # "Tool called: bash"
event.payload    # {"tool": "bash", "call_id": "...", "arguments": {"command": "pytest -q"}}
event.timestamp
event.to_dict()  # for JSON, SSE or WebSocket
```

## The events you will use most

| Event | When | Payload |
| :- | :- | :- |
| `run_started` | The run begins. | `prompt` |
| `step_started` | Before each model call. | `iteration` |
| `text_delta` | A piece of the model's text as it is written. | `chunk` |
| `reasoning_completed` | The model's visible thinking, on models that show it. | `content` |
| `assistant_message` | A complete model response. | the response's text and tool calls |
| `tool_called` | A tool is about to run. | `tool`, `call_id`, `arguments` |
| `tool_output_delta` | A piece of a tool's output, for tools that stream. | `call_id`, `chunk` |
| `tool_completed` | A tool finished; the full result. | `tool`, `call_id`, `output` |
| `tool_failed` | A tool raised, or the model called a tool that does not exist. | `error` |
| `tool_denied` | The permission gate refused a call. | `tool`, `reason` |
| `context_compacted` | Older turns were summarised to stay within the window. | token counts |
| `run_summary` | How the run went: turns, tool calls, tokens, cost, how it ended. | the run summary |
| `run_completed` | The run is over. | `output` |

[Event types](../reference/events.md) lists all of them with every payload field.

`text_delta` and `tool_output_delta` are provisional: show them as they arrive, then replace them with the complete `assistant_message` or `tool_completed`. A client that reconnects should drop provisional text it has not seen completed.

## In a terminal

`run_live()` streams a run with a ready-made renderer: tool calls, their results and the answer, with a summary at the end.

```python
answer = agent.run_live("Refactor utils.py into smaller functions.")
```

For your own loop, `StreamRenderer` renders events one at a time, and `format_event_line(event)` turns one event into one line.

```python
from shipit_agent import StreamRenderer

renderer = StreamRenderer(show_tool_output=False)
for event in agent.stream("Find dead code in src/"):
    renderer.feed(event)
renderer.close()
```

## In a notebook

```python
from IPython.display import Markdown, clear_output, display

lines = []
for event in agent.stream("Compare these two CSV files.", files=["a.csv", "b.csv"]):
    lines.append(f"`{event.type}` {event.message}")
    clear_output(wait=True)
    display(Markdown("\n\n".join(lines)))
```

## Over the web

A chat session streams packets ready to send: event dicts for a WebSocket, or SSE-formatted strings.

```python
chat = agent.chat_session(session_id="web-42")

for packet in chat.stream_packets("Summarise the incident report.", transport="sse"):
    send_to_browser(packet)  # your transport
```

`shipit serve` exposes an agent as an OpenAI-compatible HTTP endpoint with SSE streaming, if you would rather not write the server.

## From async code

```python
async for event in agent.astream("Draft the release notes."):
    print(event.type)
```

## Streaming a tool's output

A tool that yields its output instead of returning it streams to the client as `tool_output_delta` events. The model still receives one complete result.

```python
from shipit_agent import ToolOutputChunk
from shipit_agent.tools import FunctionTool


def follow_build():
    """Run the build and report each phase as it finishes."""
    yield ToolOutputChunk("compiling...\n", {"phase": "compile"})
    yield ToolOutputChunk("testing...\n", {"phase": "test"})
    yield "passed\n"


build_tool = FunctionTool.from_callable(follow_build)
```

With guardrails on, a tool's output is checked as a whole before any of it is streamed, so nothing unchecked reaches a client.

## Errors and stopping

An error inside the run is raised in your loop when the stream ends, never swallowed. Stopping early is safe: leave the loop, and the run is cancelled.

```python
try:
    for event in agent.stream("Migrate the database schema."):
        if event.type == "tool_denied":
            break
except RuntimeError as error:
    print("The run failed:", error)
```

## With the SDK API

`query()` yields typed messages instead of events: `AssistantMessage`, `UserMessage` with tool results, and a final `ResultMessage`. Set `include_partial_messages=True` for `StreamEvent`s carrying text as it is written. [Agent SDK API](../guides/agent-sdk.md#messages).
