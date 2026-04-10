# Async Runtime

`AsyncAgentRuntime` provides an async interface for running agents in async Python applications like FastAPI, Starlette, and aiohttp. It supports all the same features as the synchronous runtime — parallel tool execution, hooks, graceful failure recovery, context window management, and mid-run re-planning.

## Quick start

```python
import asyncio
from shipit_agent import AsyncAgentRuntime
from shipit_agent.llms import OpenAIChatLLM

async def main():
    runtime = AsyncAgentRuntime(
        llm=OpenAIChatLLM(model="gpt-4o-mini"),
        prompt="You are a helpful assistant.",
    )
    state, response = await runtime.run("What is 2 + 2?")
    print(response.content)

asyncio.run(main())
```

## Streaming events

```python
async def stream_example():
    runtime = AsyncAgentRuntime(
        llm=OpenAIChatLLM(model="gpt-4o-mini"),
        prompt="You are a helpful assistant.",
    )

    async for event in runtime.stream("Search for Python news"):
        print(f"{event.type:22s} {event.message}")
```

## FastAPI integration

```python
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from shipit_agent import AsyncAgentRuntime
from shipit_agent.llms import OpenAIChatLLM
import json

app = FastAPI()

@app.post("/chat")
async def chat(prompt: str):
    runtime = AsyncAgentRuntime(
        llm=OpenAIChatLLM(model="gpt-4o-mini"),
        prompt="You are a helpful assistant.",
    )
    state, response = await runtime.run(prompt)
    return {"output": response.content}

@app.post("/chat/stream")
async def chat_stream(prompt: str):
    runtime = AsyncAgentRuntime(
        llm=OpenAIChatLLM(model="gpt-4o-mini"),
        prompt="You are a helpful assistant.",
    )

    async def event_generator():
        async for event in runtime.stream(prompt):
            yield json.dumps(event.to_dict()) + "\n"

    return StreamingResponse(event_generator(), media_type="application/x-ndjson")
```

## With tools and parallel execution

```python
from shipit_agent import AsyncAgentRuntime, FunctionTool, AgentHooks

def search_web(query: str) -> str:
    return f"Results for: {query}"

def fetch_url(url: str) -> str:
    return f"Content of {url}"

runtime = AsyncAgentRuntime(
    llm=llm,
    prompt="You are a research assistant.",
    tools=[
        FunctionTool.from_callable(search_web),
        FunctionTool.from_callable(fetch_url),
    ],
    parallel_tool_execution=True,  # run tools concurrently
    hooks=AgentHooks(),            # attach hooks
    context_window_tokens=128000,  # enable context management
)

state, response = await runtime.run("Research quantum computing advances")
```

## How it works

The async runtime wraps synchronous LLM and tool calls in `asyncio.run_in_executor()`, so they run in thread pool workers without blocking the event loop. When parallel tool execution is enabled, multiple tools run as concurrent `asyncio.Task`s via `asyncio.gather()`.

```
Sync runtime                     Async runtime
──────────────                    ─────────────

threading.Thread                  asyncio.Task
  └─ run()                          └─ await run()
      └─ llm.complete()                 └─ await run_in_executor(llm.complete)
      └─ tool.run()                     └─ await run_in_executor(tool.run)

stream() → queue.Queue            stream() → asyncio.Queue
  └─ yield from queue               └─ async for event in queue
```

## Constructor parameters

`AsyncAgentRuntime` accepts the same parameters as `AgentRuntime`:

| Parameter | Type | Default | Description |
|---|---|---|---|
| `llm` | `LLM` | required | The LLM adapter to use |
| `prompt` | `str` | required | System prompt |
| `tools` | `list[Tool]` | `[]` | Tools available to the agent |
| `mcps` | `list[MCPServer]` | `[]` | MCP servers to attach |
| `max_iterations` | `int` | `4` | Maximum tool-calling iterations |
| `parallel_tool_execution` | `bool` | `False` | Run tools concurrently |
| `hooks` | `AgentHooks` | `None` | Lifecycle hooks |
| `context_window_tokens` | `int` | `0` | Enable context compaction (0 = disabled) |
| `replan_interval` | `int` | `0` | Re-plan every N iterations (0 = disabled) |
| `retry_policy` | `RetryPolicy` | default | Retry configuration |
| `memory_store` | `MemoryStore` | in-memory | Persistent memory |
| `session_store` | `SessionStore` | in-memory | Session persistence |
| `trace_store` | `TraceStore` | in-memory | Audit logging |

!!! note
    The synchronous `Agent` class does not have an async mode. Use `AsyncAgentRuntime` directly for async applications. It's intentionally a runtime-level primitive rather than a high-level wrapper.
