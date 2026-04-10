# Parallel Tool Execution

When the LLM returns multiple tool calls in a single turn, SHIPIT Agent can run them concurrently instead of sequentially. This can dramatically speed up agents that call independent tools like web search + URL fetch + code execution in the same turn.

## Enabling parallel execution

```python
from shipit_agent import Agent
from shipit_agent.llms import OpenAIChatLLM

agent = Agent.with_builtins(
    llm=OpenAIChatLLM(model="gpt-4o"),
    parallel_tool_execution=True,   # run tools concurrently
)

result = agent.run("Search for Python 3.13 release notes and today's weather in NYC")
```

## How it works

```
Sequential (default)              Parallel (parallel_tool_execution=True)
─────────────────────             ──────────────────────────────────────

LLM returns 3 tool calls          LLM returns 3 tool calls
  │                                 │
  ├─ tool_a  (2s)                   ├─ tool_a  (2s) ─┐
  │    done                         ├─ tool_b  (3s) ─┼─ all done (3s total)
  ├─ tool_b  (3s)                   ├─ tool_c  (1s) ─┘
  │    done                         │
  ├─ tool_c  (1s)                   Results appended in original order
  │    done                         (deterministic message sequencing)
  │
  Total: 6s                        Total: 3s
```

The runtime uses `ThreadPoolExecutor` internally. Each tool call gets its own thread. After all futures complete, results are appended to the message history in the **original order** so the LLM always sees a deterministic message sequence.

## When to use it

| Use case | Recommendation |
|---|---|
| Agent calls 2+ independent tools per turn | Enable parallel |
| Tools share mutable state (e.g. filesystem) | Keep sequential |
| Latency-sensitive production agents | Enable parallel |
| Debugging tool interactions | Keep sequential (easier to trace) |

## Via the profile builder

```python
from shipit_agent import AgentProfileBuilder

profile = (
    AgentProfileBuilder("fast-researcher")
    .tools([web_search, open_url, code_exec])
    .parallel_tool_execution(True)
    .build_profile()
)

agent = profile.build(llm=llm)
```

## Event ordering

When parallel execution is enabled, `tool_called` and `tool_completed` events from the same turn may arrive in non-deterministic order. However, the tool result **messages** appended to the conversation are always in the original tool call order.

!!! tip
    Single tool calls are always run sequentially, even when `parallel_tool_execution=True`. The parallel path only activates when the LLM returns 2 or more tool calls in one turn.
