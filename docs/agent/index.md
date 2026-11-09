---
title: The Agent
description: Construct an Agent, run it, stream it, hold a conversation, and choose its tools, limits and stores.
---

# The Agent

`shipit_agent.Agent` is the runtime. Every other agent in the library, including `DeepAgent`, `GoalAgent` and the SDK's `query()`, runs an `Agent` underneath.

## Three ways to build one

```python
from shipit_agent import Agent
from shipit_agent.llms import build_llm_from_env

llm = build_llm_from_env()

# Only the tools you give it.
agent = Agent(llm=llm, tools=[...])

# Every built-in tool: files, search, bash, the web, todos, sub-agents and services.
agent = Agent.with_builtins(llm=llm, project_root=".")

# A project agent: built-in tools, plus the repository's .shipit/settings.json,
# SHIPIT.md or AGENTS.md instructions and /slash commands from .shipit/commands/.
agent = Agent.for_project(llm=llm, project_root=".", optimized=True)
```

`optimized=True` turns on the defaults for long runs: code mode (the tool catalog exposed progressively), compaction at the model's real context window, parallel tools, bounded tool output saved to files when long, and progress summaries. With `for_project`, it also keeps sessions and memory under `.shipit/`. Values you pass always win.

## Running it

| Call | Returns | Use it for |
| :- | :- | :- |
| `agent.run(prompt)` | `AgentResult` | A task you want the answer to. |
| `agent.stream(prompt)` | events, as they happen | Showing progress in a terminal or UI. |
| `await agent.arun(prompt)` | `AgentResult` | The same, from async code. |
| `agent.astream(prompt)` | async events | Streaming from async code. |

```python
result = agent.run("Summarise the open issues in docs/ROADMAP.md")
print(result.output)

for event in agent.stream("Run the tests and fix what fails"):
    print(event.type, event.message)
```

Every call takes `images=` and `files=`: paths or URLs the model sees with the prompt.

```python
agent.run("What changed between these two screens?", images=["before.png", "after.png"])
agent.run("Check the contract against the spec.", files=["contract.pdf", "spec.md"])
```

## The result

| Field | Holds |
| :- | :- |
| `output` | The final answer. |
| `parsed` | The validated object, when you passed `output_schema`. |
| `messages` | The whole conversation, including tool calls and results. |
| `events` | Every event the run emitted. |
| `tool_results` | Each tool call's result. |
| `rag_sources` | The sources cited, when the agent has a `rag`. |
| `metadata["usage"]` | Token counts. |
| `metadata["run_summary"]` | How the run ended (`completion_status`, `subtype`), turns, tool calls and `estimated_cost_usd`. |

## Structured answers

Pass a Pydantic model or a JSON Schema, and the answer comes back validated in `result.parsed`. If the model's answer does not validate, it is asked to correct it, up to `max_validation_retries` times.

```python
from pydantic import BaseModel


class Invoice(BaseModel):
    number: str
    total: float
    due: str


result = agent.run("Extract the invoice details.", files=["invoice.pdf"], output_schema=Invoice)
invoice = result.parsed
```

[Structured output](../guides/structured-output.md) covers schemas and streaming.

## A conversation

`chat_session()` keeps the history between turns. With a `session_store`, the conversation survives a restart: build the agent again, open the same session id, and carry on.

```python
from shipit_agent import Agent, FileSessionStore
from shipit_agent.llms import build_llm_from_env

agent = Agent.with_builtins(llm=build_llm_from_env(), session_store=FileSessionStore(".shipit/sessions"))
chat = agent.chat_session(session_id="support-42")
chat.send("The export button does nothing on Safari.")
chat.send("It started after Tuesday's release.")
```

[Sessions](sessions.md) covers stores, forking and resuming.

## The settings that matter most

| Need | Setting |
| :- | :- |
| Stop runaway runs | `max_turns=30`, `max_budget_usd=2.0`, `max_task_tokens=500_000` |
| Decide what may run | `permission_mode=`, `permissions=`, `permission_callback=` ([Permissions](../guides/permissions.md)) |
| Run code before or after tools | `hooks=` ([Hooks](../guides/hooks.md)) |
| Tools from MCP servers | `mcps=[...]` ([MCP](../guides/mcp.md)) |
| Many tools, small requests | `deferred_tools=True` ([Tool search](../guides/tool-search.md)) |
| A fallback when the model fails | `fallback_model=` and `retry_policy=` ([Error recovery](../guides/error-recovery.md)) |
| Remember across sessions | `memory_store=` ([Memory](memory.md)) |
| Ground answers in documents | `rag=` ([RAG with an agent](../rag/with-agent.md)) |
| Sub-agents | `agents={...}` ([Sub-agents](../guides/delegation.md)) |
| Keep long runs within the window | `context_window_tokens=`, `clear_tool_results=` ([Context management](../guides/context-management.md)) |

[Agent parameters](../reference/parameters.md) lists all of them.

## When to reach for a deep agent

Start with `Agent`. It plans with its todo list, delegates to sub-agents and checks its own work. Reach for a [deep agent](../deep-agents/index.md) when you want a fixed shape around it: a goal with success criteria (`GoalAgent`), a write-critique-revise loop (`ReflectiveAgent`), or a supervisor handing work to specialists (`Supervisor`).
