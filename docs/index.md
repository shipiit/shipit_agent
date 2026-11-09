---
description: ShipIt Agent is an open-source Python runtime for agents that use tools, MCP servers and any model, with an async SDK API alongside the Agent class.
---

# ShipIt Agent

ShipIt Agent is an open-source Python runtime for agents that do real work: they read and edit files, run commands, call tools and MCP servers, and check their own results. It runs in your process, with any model, and offers two ways in: the `Agent` class, or an async SDK API with typed messages.

```python
from shipit_agent import Agent
from shipit_agent.llms import build_llm_from_env

agent = Agent.with_builtins(llm=build_llm_from_env())
result = agent.run("Find every TODO in this repository and group them by file.")
print(result.output)
```

## What it gives you

| | |
| :- | :- |
| **One agent loop** | Tool calling, parallel tools, retries, context compaction and a final answer on every run, whatever the model. |
| **Any model** | Opus, Sonnet and Haiku, GPT, Gemini, Gemma, Llama, Mistral and more, through 18 provider profiles or LiteLLM. Switching is a one-line change. |
| **The async SDK API** | `query()`, `AgentClient`, `AgentOptions`, hooks, permission modes, `@tool` and in-process MCP servers, with typed messages. |
| **Tools that work** | 66 built-in tools (files, search, bash, web, sub-agents, GitHub, Slack, Jira and more) with read tracking, bounded output and safe defaults. |
| **Safety you can see** | Permission modes and rules, approval callbacks, hooks, guardrails and an OS sandbox for commands. |
| **Measured** | An 18-task benchmark ships in the repo; Anthropic Sonnet 5.5 and Gemma 4 both pass all 18. |

## Two ways in

**The `Agent` class** is shipit's own API: construct an agent, call `run()` or `stream()`, and set any of its options directly. Start with the [Quickstart](getting-started/quickstart.md).

**The SDK API** is the async way in: `query(prompt, options=AgentOptions(...))` yields typed messages, and `AgentClient` keeps a conversation open. Use it when you want typed messages or async code. See [Agent SDK API](guides/agent-sdk.md).

Both run the same loop, so everything in these docs applies to either.

## Where to go next

- **New here?** [Install](getting-started/install.md), then the [Quickstart](getting-started/quickstart.md), then [Core concepts](getting-started/concepts.md).
- **Building a coding agent?** [Tools](agent/with-tools.md), [Permissions](guides/permissions.md), [Sandbox](guides/sandbox.md) and [Hooks](guides/hooks.md).
- **Prefer async code and typed messages?** [Agent SDK API](guides/agent-sdk.md) lists every option.
- **Upgrading from 2.x?** [Upgrading to 3.0](guides/upgrading.md).
