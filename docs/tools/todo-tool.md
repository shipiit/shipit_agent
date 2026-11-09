---
title: TodoTool — live task tracking
description: TodoTool is a live, replace-on-write checklist the model maintains while it works, so long agentic runs stay observable. Rendered as a checklist and stored on context.state["todos"]. Included in Agent.with_builtins().
---

# `TodoTool` — live task tracking

`TodoTool` is a live
checklist the model maintains while it works through a multi-step task. Every
call **replaces** the whole list, so the current plan is always one tool call
behind the model's actual progress — which is exactly what makes long agentic
runs **observable** and smooth to follow.

> **TL;DR** —
> The model writes all the steps up front, marks exactly **one** item
> `in_progress` at a time, and flips items to `completed` as it finishes them.
> The normalized list lands on `context.state["todos"]` so your runtime / UI can
> render progress. Included automatically in `Agent.with_builtins()`.

## Schema

The tool takes a single `todos` array. Each item is a `{content, status}`
object:

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `content` | string | yes | What the task is (must be non-empty). |
| `status` | enum | no | `pending` \| `in_progress` \| `completed`. Defaults to `pending`. |

**Replace semantics** — each call passes the **full, updated** list, not a
delta. The previous list is discarded and replaced wholesale. Invalid input
(non-array `todos`, a non-object item, empty `content`, or an unknown `status`)
is rejected with a clear error message and no state change.

```python
agent.run(...)  # the model calls the tool like this:
# todo(todos=[
#     {"content": "Read the spec",        "status": "completed"},
#     {"content": "Write the parser",     "status": "in_progress"},
#     {"content": "Add tests",            "status": "pending"},
# ])
```

## Rendered checklist

The tool returns a glyph-prefixed checklist plus a one-line summary — the same
text that shows up in the trace, so a human watching the run sees the plan
advance in real time:

```text
☑ Read the spec
▶ Write the parser
☐ Add tests
(1/3 completed, 1 in progress, 1 pending)
```

| Glyph | Status |
| --- | --- |
| `☐` | `pending` |
| `▶` | `in_progress` |
| `☑` | `completed` |

## State & metadata

After each call, the normalized list is written to **`context.state["todos"]`**
so the runtime or a UI can render progress between steps:

```python
result = agent.run("Refactor the auth module end to end.")
todos = result.context.state.get("todos", [])
# [{"content": "...", "status": "completed"}, ...]
```

The `ToolOutput.metadata` also carries the structured list and a rollup summary
(this metadata is transient — `persist: False`):

```python
{
    "todos": [{"content": "...", "status": "..."}, ...],
    "summary": {"total": 3, "completed": 1, "in_progress": 1, "pending": 1},
    "persist": False,
}
```

## Attaching it

`TodoTool` ships in the builtin catalogue, so any agent built with
`Agent.with_builtins()` (or `Agent.for_project()`) already has it under the name
`todo`:

```python
from shipit_agent import Agent

agent = Agent.with_builtins(llm=llm, project_root=".")
# `todo` is in agent.tools — the model maintains its own live checklist.
```

To add it to a hand-built agent, pass it in `tools=`:

```python
from shipit_agent import Agent
from shipit_agent.tools import TodoTool

agent = Agent(llm=llm, tools=[TodoTool()])
```

The tool also exposes `prompt_instructions` that tell the model how to use it —
write all steps up front, keep exactly one item `in_progress`, and flip items to
`completed` as they finish — so the checklist discipline is built in.

## Why it matters

On a long, multi-step job an agent can otherwise feel like a black box. By
having the model keep a live checklist, you get:

- **Observability** — at any moment you (and your UI) can see what's done,
  what's in flight, and what's left.
- **Self-discipline** — writing the plan up front keeps the model on track and
  reduces dropped steps on long-horizon tasks.
- **Smooth UX** — progress streams out as the run proceeds instead of arriving
  all at once at the end.

## See also

- [The SHIPIT Workspace](../agent/workspace.md) — `Agent.for_project()` includes
  `TodoTool` by default.
- [Catalog overview](index.md) — the full builtin tool catalogue.
- [Reasoning helpers](reasoning-helpers.md) — the planning / decomposition tools
  that pair with the todo checklist.
