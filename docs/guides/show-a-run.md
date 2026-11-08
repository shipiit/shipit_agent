---
title: Show a run
description: Every way to present an agent run, from the terminal view to HTML, typed rows, trees, JSON and the wire formats for SSE and WebSocket, with real output from one recorded run.
---

# Show a run

One run, many ways to show it. Every view on this page renders the same events, so pick the one that fits where the run is going: a terminal, a log, a web page, your own UI or another service.

The outputs below are real. They come from one recorded run: Claude Haiku 5.5, given a two-file project whose test fails and the task `"The tests in this repo fail. Find the bug, fix it, and run the tests to confirm they pass."` It finished in 5 turns, 6 tool calls and 782 tokens, for $0.0009.

```python
from shipit_agent import Agent
from shipit_agent.llms import build_llm_from_env

agent = Agent.with_builtins(llm=build_llm_from_env(), project_root=".")
task = "The tests in this repo fail. Find the bug, fix it, and run the tests to confirm they pass."
```

| You want | Use | Live or after |
| --- | --- | --- |
| The CLI's compact view | `CompactRenderer` | live |
| A readable transcript | `NarratorRenderer`, `render_transcript()` | live, after |
| Every call with its arguments | `render_tree()` | after |
| Your own UI | `agent.narrate()`, `build_transcript()`, `transcript_json()` | live, after |
| A shareable file | `render_transcript_html()`, `write_transcript()` | after |
| Raw events | `agent.stream()` | live |
| JSON for an API | `event_packet()`, `result_packet()` | live, after |
| Server-Sent Events or WebSocket | `agent.stream_sse()`, `sse_event_packet()`, `websocket_event_packet()` | live |

## The terminal view

`shipit chat` prints this compact view by default: one line per tool call, a short result under it, and the model's words in between. To print it from your own code, feed it the events:

```python
from shipit_agent.narrate.compact import CompactRenderer

renderer = CompactRenderer(model="claude-haiku-5-5")
for event in agent.stream(task):
    renderer.feed(event)
```

```text
⏺ Read(test_calc.py)
  ⎿  Read 10 lines
⏺ Read(calc.py)
  ⎿  Read 7 lines

⏺ The bug is in `add`, which subtracts instead of adding. Fixing it and re-running the tests.
⏺ Update(calc.py, old_text:     return a - b, new_text:     return a + b)
  ⎿  File patched: ~/calc/calc.py (1 occurrence replaced)
⏺ Bash(pytest -q 2>&1 | tail -5)
  ⎿  ..                                                                       [100%]
     2 passed in 0.00s

⏺ The bug was in `add` in `calc.py:3`: it returned `a - b` instead of `a + b`. I changed it to `return a + b`.
                                       782 tokens · $0.0009 · claude-haiku-5-5
```

Long output is never printed whole: a few lines, then how many more.

## A transcript

The transcript groups work into rows ("Read 2 files", "Edited calc.py, ran pytest") with the model's prose between them. Render it live with `NarratorRenderer`, or from a finished run with `render_transcript()`:

```python
from shipit_agent import render_transcript

result = agent.run(task)
print(render_transcript(result, model="claude-haiku-5-5"))
```

```text
  ❯ Ran cd . && ls -la && (pytest -q 2>&1 || npm test 2>&1 || go te… ›
  ▤ Read 2 files ›
    calc.py · test_calc.py

The bug is in `add`, which subtracts instead of adding. Fixing it and re-running the tests.

  ✎ Edited calc.py, ran pytest -q 2>&1 | tail -5 ›
    calc.py · pytest -q 2>&1 | tail -5
  ⌕ Searched for return a [+-] b ›

The bug was in `add` in `calc.py:3`: it returned `a - b` instead of `a + b`. I changed it to `return a + b`.

                                                 782 tokens · claude-haiku-5-5
```

`NarratorRenderer(style="auto")` uses colour on a terminal and plain text elsewhere; pass `style="plain"` for logs.

## Every call, as a tree

`render_tree()` opens every call: its arguments, how long it took, and the first lines of what came back.

```python
from shipit_agent import render_tree

print(render_tree(result, model="claude-haiku-5-5", detail=True))
```

```text
├─ Tool group: Read 2 files
│  ├─ read_file                                     completed  5ms
│  │  ↳ path='calc.py'
│  │    1: def add(a, b):
│  │    2:     """Return the sum of a and b."""
│  │    3:     return a - b
│  │    … 4 more lines
│  └─ read_file                                     completed  4ms
│     ↳ path='test_calc.py'
│
├─ Decision
│  The bug is in `add`, which subtracts instead of adding. Fixing it and re-running the tests.
```

`output_lines` sets how much of each result is shown (default 6). See [Tree view](tree-view.md).

## Rows for your own UI

`agent.narrate()` yields the same rows the transcript shows, as objects, as each one settles. Render them however you like:

```python
for row in agent.narrate(task):
    label = getattr(row, "text", None) or getattr(getattr(row, "group", None), "label", "")
    print(type(row).__name__, label)
```

```text
WorkRow Ran cd . && ls -la && (pytest -q 2>&1 || npm test 2>&1 || go te…
WorkRow Read 2 files
ProseRow The bug is in `add`, which subtracts instead of adding. Fixing it and re-running the tests.
WorkRow Edited calc.py, ran pytest -q 2>&1 | tail -5
WorkRow Searched for return a [+-] b
ProseRow The bug was in `add` in `calc.py:3`: it returned `a - b` instead of `a + b`. …
```

A `WorkRow` holds a group of tool calls (`row.group.calls`, each with its name, arguments, status, output and duration); a `ProseRow` is the model's words. For a finished run, `build_transcript(result)` returns the same rows, and `transcript_json(result)` (from `shipit_agent.narrate`) returns them as JSON.

## A shareable HTML file

`render_transcript_html()` returns one self-contained HTML document; `write_transcript()` writes it to disk:

```python
from shipit_agent import write_transcript

path = write_transcript("run.html", result, title="Fix the failing test", model="claude-haiku-5-5", prompt=task)
print(path)
```

## Events and packets

Every view above is built from `agent.stream()` events. To send them to another program, the packet helpers turn an event or a result into JSON-ready data:

```python
from shipit_agent import event_packet, result_packet, sse_event_packet, websocket_event_packet

for event in agent.stream(task):
    packet = event_packet(event)            # a dict, ready for json.dumps
    frame = sse_event_packet(event)         # one Server-Sent Events frame, as a string
    message = websocket_event_packet(event) # a dict shaped for a WebSocket message
```

One frame of the recorded run, as `shipit serve` streams it:

```text
id: 20
event: tool_called
data: {"type": "tool_called", "durability": "canonical", "sequence": 20, "message": "Tool called: bash", "payload": {"tool": "bash", "arguments": {"command": "pytest -q 2>&1 | tail -5"}, …}}
```

In a web framework, `agent.stream_sse(task)` yields these frames for you, opening with a `stream_hello` and closing with `[DONE]`. To serve an agent over HTTP, see [Deployment](deployment.md).

## See also

- [Streaming](../agent/streaming.md): the events themselves
- [Timeline](timeline.md): a run as a Markdown report
- [Live UI](live-ui.md): a live view in a notebook
