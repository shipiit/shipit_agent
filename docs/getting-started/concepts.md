---
description: How the agent loop, tools, permissions, context and sessions fit together.
---

# Core concepts

Every agent in shipit, whether built with `Agent` or with `query()`, runs the same loop. Knowing its parts tells you where each setting acts.

## The loop

A run is a series of turns:

1. The model gets the system prompt, the conversation and the tools' schemas.
2. It answers with text, tool calls, or both.
3. Each tool call goes through the permission gate, runs, and its result joins the conversation. Independent read-only calls run in parallel.
4. Back to step 1, until the model answers without calling a tool.

The run also stops at a limit you set: `max_turns`, `max_budget_usd` or a token budget. However it stops, the run ends with a final answer and a summary of how it went: finished, or stopped short and why.

## Tools

A tool is a name, a JSON Schema for its arguments and a `run()` method. The model sees the name, the description and the schema; it never sees your code.

- **Built-in tools** cover files, search, bash, the web, todos, sub-agents and services such as GitHub and Slack. [Tools](../agent/with-tools.md) lists them.
- **Your tools** are functions or classes. [Custom tools](../guides/custom-tools.md).
- **MCP servers** add tools from outside the process, or from in-process `@tool` functions. [MCP](../guides/mcp.md).

Each tool says whether it is read-only. Read-only tools run without asking; the rest go through permissions.

When there are many tools, `deferred_tools` keeps only a core set loaded and lists the others by name. The model loads one when it needs it with `tool_search`, which keeps every request small. [Tool search](../guides/tool-search.md).

## Permissions

Before a tool runs, the permission gate decides: allow, deny or ask.

- **Mode** sets the default. `default` asks before risky actions, `acceptEdits` allows file edits, `plan` allows only reading, `dontAsk` refuses anything not pre-approved, and `bypassPermissions` allows everything.
- **Rules** such as `Bash(git *)` or `Read(src/**)` allow, deny or ask for specific calls.
- **A callback**, `can_use_tool` in the SDK, decides the calls that would ask.
- **Hooks** run your code before and after each tool and at other points in the run.

Bash commands are judged one by one: `ls` and `pytest` run, while `rm`, `git push` or writing outside the project ask. With the OS [sandbox](../guides/sandbox.md) on, commands run where they cannot write outside the project, so they need no approval. [Permissions](../guides/permissions.md).

## Context

Everything the model sees counts against its context window: the prompt, the conversation, the tool schemas and every tool result. shipit keeps it in bounds:

- Long tool output is clipped, and the full text is saved to a file the model can read.
- As the conversation nears the window, older turns are compacted into a summary.
- Optionally, old tool results are cleared once the model has used them.

[Context management](../guides/context-management.md).

## Sessions and memory

A **session** is a conversation you can continue. Give the agent a `session_store` and a `session_id`, and the next run picks up where the last stopped. [Sessions](../agent/sessions.md).

**Memory** outlives a session: facts the agent saves with the `memory` tool, and project instructions it reads at the start of each run from `SHIPIT.md`, `AGENTS.md` or `CLAUDE.md` (also under `.shipit/`), plus your own `~/.shipit/SHIPIT.md`. [Memory](../agent/memory.md).

## Sub-agents and skills

A **sub-agent** is a second agent the main one delegates to, with its own prompt, tools and model. Define them in `agents=` or as files in `.claude/agents/` or `.shipit/agents/`. [Delegation](../guides/delegation.md).

A **skill** is a folder of instructions, and sometimes scripts, that the agent loads when a task matches it. Packaged skills cover common work; your own live in `.shipit/skills/`. [Skills](../guides/skills.md).

## Events

Every step emits an event: the run starting, each model response, each tool call and its result, text as it is written, compaction, the final summary. `stream()` yields them; `run()` collects them on the result. [Streaming](../agent/streaming.md) and [Event types](../reference/events.md).
