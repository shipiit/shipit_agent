# Error Recovery & Retry Policies

SHIPIT Agent handles failures gracefully at every level — LLM provider errors, tool execution failures, and hallucinated tool names all produce recoverable error messages instead of crashing the agent run.

## How error recovery works

When a tool fails after exhausting retries, the runtime produces an error `ToolResult` message and sends it back to the LLM. The LLM sees the error and can decide to try a different tool, adjust its approach, or report the issue to the user.

```
LLM: "Call web_search with query='latest news'"
         │
         ▼
    web_search raises ConnectionError
         │
    retry 1 → still fails
         │
         ▼
    Runtime creates error message:
    "Error running tool 'web_search': connection refused"
         │
         ▼
    LLM sees error, decides to try open_url instead
         │
         ▼
    Agent continues running
```

This is the same pattern used for hallucinated tool names — every tool call gets a paired result message, whether success or error, keeping the conversation balanced for all providers (especially Bedrock).

## Retry policy

```python
from shipit_agent import Agent, RetryPolicy

agent = Agent(
    llm=llm,
    retry_policy=RetryPolicy(
        max_llm_retries=2,           # retry LLM calls up to 2 times
        max_tool_retries=1,          # retry tool calls up to 1 time
        retry_on_exceptions=(        # only retry these exception types
            ConnectionError,
            TimeoutError,
            OSError,
        ),
    ),
)
```

### Default exceptions

The default `retry_on_exceptions` is `(ConnectionError, TimeoutError, OSError)` — network and I/O errors that are typically transient. This is intentionally narrow:

| Exception type | Retried by default | Why |
|---|---|---|
| `ConnectionError` | Yes | Network hiccup, retry likely succeeds |
| `TimeoutError` | Yes | Server slow, retry may succeed |
| `OSError` | Yes | I/O issue, often transient |
| `RuntimeError` | No | Usually a bug, retrying won't help |
| `ValueError` | No | Bad data, same input = same error |
| `TypeError` | No | Code bug, fix the code |
| `KeyError` | No | Missing data, not transient |

To retry on additional exceptions:

```python
RetryPolicy(
    retry_on_exceptions=(ConnectionError, TimeoutError, OSError, RuntimeError),
)
```

## Events emitted during failures

| Event | When | Key payload |
|---|---|---|
| `tool_retry` | Tool failed, retrying | `attempt`, `error`, `iteration` |
| `tool_failed` | Tool failed permanently (or hallucinated name) | `error`, `iteration` |
| `llm_retry` | LLM call failed, retrying | `attempt`, `error` |

## Before vs. after (the old behavior)

| Scenario | Before (v1.0.0) | After (v1.0.2) |
|---|---|---|
| Tool raises after retries | **Agent crashes**, caller gets exception | Error message sent to LLM, agent continues |
| Hallucinated tool name | Error message sent to LLM | Error message sent to LLM (unchanged) |
| LLM provider error | Retried, then crashes | Retried, then crashes (unchanged) |

!!! warning "Breaking change from 1.0.0"
    If you were catching tool exceptions from `agent.run()`, note that tool failures no longer propagate as exceptions. The agent will continue running and include the error in its response. Check `result.events` for `tool_failed` events if you need to detect failures programmatically.
