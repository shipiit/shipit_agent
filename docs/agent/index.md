---
title: Agent
description: The core shipit_agent.Agent class — what it is, when to use it, and how to compose it with tools, RAG, memory, and sessions.
---

# Agent

`shipit_agent.Agent` is the core building block of the entire library.
Every other agent type — `DeepAgent`, `GoalAgent`, `ReflectiveAgent`,
`AdaptiveAgent`, `Supervisor`, `PersistentAgent` — wraps an `Agent`
internally. If you understand `Agent`, you understand the runtime.

> **TL;DR** — `Agent.with_builtins(llm=llm).run(prompt)` is the
> minimum viable agent. Add `tools=`, `rag=`, `memory_store=`, or
> `session_store=` as you need them.

---

## When to use plain `Agent`

| Use plain `Agent` when… | Use a deep agent when… |
| --- | --- |
| The task fits in one linear pass of "tool → tool → answer". | The task needs explicit planning or multi-step decomposition. |
| Latency matters more than perfect output. | Quality matters more than latency. |
| You want minimal ceremony. | You want self-verification, reflection, or sub-agent delegation. |
| You're building chat features, simple Q&A, or quick automations. | You're building research, code generation, or long-horizon workflows. |

The rule of thumb: **start with `Agent`. When the task starts to feel
too long for a single linear run, switch to `DeepAgent` — you keep all
the same tools and gain planning, workspace, sub-agent delegation, and
the option to enable verification or reflection with one extra flag.**

---

## Quick start

```python
from shipit_agent import Agent
from examples.run_multi_tool_agent import build_llm_from_env

llm = build_llm_from_env()             # reads SHIPIT_LLM_PROVIDER from .env
agent = Agent.with_builtins(llm=llm)   # 30+ built-in tools, ready to go

result = agent.run("Find today's Bitcoin price in USD from a reputable source.")
print(result.output)
```

`with_builtins()` ships ~30 tools out of the box: web search, browser
automation, code execution, file workspace, Slack, Gmail, Jira, Linear,
Notion, Confluence, and more.

---

## Streaming

Replace `agent.run(...)` with `agent.stream(...)` to watch each step
happen live:

```python
for event in agent.stream("Find today's BTC price."):
    print(f"[{event.type}] {event.message}")
```

You'll see `run_started`, `step_started`, `reasoning_started`,
`reasoning_completed`, `tool_called`, `tool_completed`, `run_completed`
events as they happen — not buffered until the end. Every event is a
plain dataclass; render them however your UI wants.

See the [Streaming guide](../guides/streaming.md) for the full event
reference and the [Examples](examples.md) page for a colored terminal
renderer you can copy.

---

## Composition checklist

| Need | Pass | Docs |
| --- | --- | --- |
| Tools | `tools=[…]` or `with_builtins()` | [Custom tools](../guides/custom-tools.md) |
| MCP servers | `mcps=[…]` | [MCP integration](../guides/mcp.md) |
| Grounded answers with citations | `rag=my_rag` | [RAG + Agent](../rag/with-agent.md) |
| Long-term memory | `memory_store=…` | [Advanced memory](../guides/advanced-memory.md) |
| Multi-turn chat | `session_store=…` + `agent.chat_session(…)` | [Sessions guide](../guides/sessions.md) |
| Audit trail | `trace_store=…` | [FAQ — production](../faq.md#how-do-i-monitor-production-runs) |
| Hooks (before/after LLM, tool wrappers) | `hooks=AgentHooks(…)` | [Hooks guide](../guides/hooks.md) |
| Parallel tool calls | `parallel_tool_execution=True` | [Parallel execution](../guides/parallel-execution.md) |
| Auto context compaction | `context_window_tokens=200_000` | [Context management](../guides/context-management.md) |
| Retry policy | `retry_policy=RetryPolicy(…)` | [Error recovery](../guides/error-recovery.md) |
| Higher iteration cap | `max_iterations=20` | [Re-planning](../guides/replanning.md) |

Every parameter is documented with type, default, and "use it when" in
the [Parameters Reference](../reference/parameters.md#agent).

---

## What's in this section

- [Examples](examples.md) — Hello-world, web search, custom tools,
  multi-turn chat, parsers, structured output.
- [Streaming](streaming.md) — Real-time event handling with rendering
  recipes for terminals, notebooks, and SSE/WebSocket transports.
- [With RAG](with-rag.md) — Wire a knowledge base into an `Agent` with
  one parameter and read citations off `result.rag_sources`.
- [With Tools](with-tools.md) — Extend the agent with custom tools, MCP
  servers, and runtime tool factories.
- [Memory](memory.md) — `AgentMemory`, conversation summaries, semantic
  facts, entity tracking, and the OpenAI-style "remember things across
  sessions" pattern.
- [Sessions & Memory](sessions.md) — Persistent multi-turn chat,
  long-term memory, and conversation forking.

For agentic patterns above plain `Agent` (planning, reflection,
delegation, goal-driven), see the [Deep Agents](../deep-agents/index.md)
section.

---

## See also

- [Quickstart](../getting-started/quickstart.md) — five-minute tour
- [DeepAgent](../deep-agents/deep-agent.md) — when you need more than
  plain `Agent`
- [Parameters Reference](../reference/parameters.md) — every
  constructor parameter
- [FAQ — agent types](../faq.md#agent-types-which-one-should-i-use) —
  pick the right agent for the task
