---
title: Claude-style memory tool
description: ClaudeMemoryTool — the Anthropic memory_20250818 tool shape, a single command-driven tool the model uses to read and write a sandboxed, cross-session memory directory. New in v1.0.11.
---

# `ClaudeMemoryTool`

New in **v1.0.11**, `ClaudeMemoryTool` is shipit_agent's implementation of
Anthropic's **`memory_20250818`** tool shape: a single tool the model invokes
with a `command` argument to read and write a persistent, **sandboxed**
memory directory that survives across sessions. It's how an agent builds up
durable notes, intermediate results, and learnings on long-horizon tasks so a
future run can pick up where it left off.

> **TL;DR** —
> `Agent(tools=[ClaudeMemoryTool()])` gives the model a `view` / `create` /
> `str_replace` / `insert` / `delete` / `rename` memory directory under
> `.shipit_workspace/memories`. Paths that escape the root are rejected.

## Commands

The model passes a `command` and the relevant arguments. All paths are
confined to the sandbox root:

| Command | What it does | Key args |
| --- | --- | --- |
| `view` | List a directory or show a file (with line numbers) | `path` |
| `create` | Create or overwrite a file | `path`, `file_text` |
| `str_replace` | Replace a single unique occurrence of a string | `path`, `old_str`, `new_str` |
| `insert` | Insert text after a line (`0` = start of file) | `path`, `insert_line`, `insert_text` |
| `delete` | Delete a file | `path` |
| `rename` | Move / rename a file | `old_path`, `new_path` |

## Attaching it

It's a regular tool — pass it in `Agent(tools=[...])`:

```python
from shipit_agent import Agent, ClaudeMemoryTool

agent = Agent(
    llm=llm,
    tools=[ClaudeMemoryTool()],
)

# The model can now persist and recall notes across runs.
agent.run("Research our top 3 competitors and save findings to memory.")
# ... later, a fresh process ...
agent.run("Continue the competitor research where you left off.")
```

The tool injects a short prompt telling the model to **check memory first**
(`view`) at the start of a task before redoing work, and to keep entries
concise and factual in small, well-named files — exactly the Anthropic memory
tool guidance.

## Sandboxing

Every command is confined to `root_dir`, which defaults to
`.shipit_workspace/memories`. Paths are resolved and any path that escapes
the root — `..` traversal or an absolute path outside the sandbox — is
**rejected** before it can touch the wider filesystem. Construction is
side-effect free: instantiating the tool does not create the directory, so
importing it never litters your repo.

```python
from shipit_agent import ClaudeMemoryTool

# Point memory at a custom, per-tenant directory.
memory = ClaudeMemoryTool(root_dir="/var/agent/tenant-42/memories")

agent = Agent(llm=llm, tools=[memory])
```

## Cross-session learning

Because the directory persists on disk, a memory written in one run is
available to the next — even in a brand-new process. This is what makes the
tool useful for long-horizon work:

- **Resumable research** — accumulate findings across runs instead of
  starting cold each time.
- **Durable learnings** — record what worked and what didn't so the agent
  improves over repeated tasks.
- **Intermediate state** — checkpoint partial results on a long pipeline.

For the framework's own structured memory systems (semantic facts, entity
tracking, conversation summaries), see [Agent — Memory](../agent/memory.md)
and [Memory consolidation](../agent/memory-consolidation.md). `ClaudeMemoryTool`
complements them: it's the **model-driven, file-based** memory the LLM
manages itself.

## When to use

- You want the **Anthropic memory tool shape** specifically (`memory_20250818`)
  for parity with Claude's native memory behaviour.
- The agent runs **repeatedly over time** and should carry learnings forward.
- You want memory the **model controls directly** via tool calls, sandboxed
  to a directory you choose.

## See also

- [Agent — Memory](../agent/memory.md) — the framework's `MemoryStore` and
  `AgentMemory` facade.
- [Memory consolidation](../agent/memory-consolidation.md) — episodic memory.
