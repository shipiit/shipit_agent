# Architecture

SHIPIT Agent is built around a small, focused runtime with clean boundaries between concerns.

## Component diagram

```
┌─────────────────────────────────────────────────────────────┐
│                         Agent                               │
│  (profile: llm, tools, mcps, prompt, policies, stores)      │
└────────────────────┬────────────────────────────────────────┘
                     │
          ┌──────────▼──────────┐
          │    AgentRuntime     │
          │  run() / stream()   │
          └──────────┬──────────┘
                     │
     ┌───────────────┼────────────────┐
     │               │                │
     ▼               ▼                ▼
┌─────────┐    ┌──────────┐    ┌────────────┐
│   LLM   │    │   Tool   │    │    MCP     │
│ Adapter │    │ Registry │    │  Servers   │
└─────────┘    └────┬─────┘    └─────┬──────┘
                    │                │
                    ▼                ▼
              ┌──────────┐     ┌────────────┐
              │ToolRunner│     │ Transport  │
              └──────────┘     └────────────┘
                    │
           ┌────────┼────────┐
           ▼        ▼        ▼
      ┌─────┐  ┌─────┐  ┌─────┐
      │Tools│  │Tools│  │Tools│
      └─────┘  └─────┘  └─────┘
```

## The runtime loop

```python
def run(user_prompt):
    state = RuntimeState()
    load_session()
    emit("run_started")

    if should_plan(user_prompt):
        run_planner()
        emit("planning_completed")  # injected as user-role message

    for iteration in range(1, max_iterations + 1):
        emit("step_started")
        response = llm.complete(messages=state.messages, tools=tool_schemas)

        if response.reasoning_content:
            emit("reasoning_started")
            emit("reasoning_completed")

        if not response.tool_calls:
            break

        append_assistant_message_with_tool_uses(response)
        for tool_call in response.tool_calls:
            emit("tool_called")
            result = run_tool(tool_call)
            append_tool_result_message(result)  # always — even on failure
            emit("tool_completed" or "tool_failed")

    if hit_iteration_cap:
        emit("step_started")  # final summarization turn
        response = llm.complete(tools=[])  # force prose answer

    save_session()
    save_memory()
    emit("run_completed")
```

## Key invariants

### 1. Tool use/result pairing

Every `toolUse` block in an assistant turn is matched by exactly one `toolResult` block in the next user turn. This is enforced unconditionally:

- If a tool succeeds → real tool-result message appended
- If a tool raises retryable error → retry loop, then append real or error message
- If a tool raises non-retryable error → append error message, continue
- If the model hallucinates an unregistered tool name → append synthetic `"Error: tool X is not registered"` message
- The planner's output is **never** appended as a `role="tool"` message — always as `role="user"` context

This invariant is what makes Bedrock's Converse API work reliably across multi-iteration tool loops.

### 2. Reasoning extraction

The LLM adapter populates `LLMResponse.reasoning_content` from whatever shape the provider returns. The runtime treats reasoning as a first-class signal and emits events for it without any configuration.

### 3. Events are immutable and ordered

Every emitted event is a frozen dataclass. The stream is strictly ordered: events are yielded in emission order, there's no reordering, no deduplication, no batching.

### 4. Background thread for `stream()`

`stream()` runs the runtime on a background daemon thread and yields events via a `queue.Queue`. The consumer thread blocks on `queue.get()` until a new event arrives or a sentinel marks completion. Worker exceptions are captured and re-raised on the consumer side so errors surface correctly.

## Module layout

```
shipit_agent/
├── agent.py              # Agent dataclass + profile composition
├── runtime.py            # AgentRuntime (run/stream)
├── models.py             # Message, ToolCall, ToolResult, AgentEvent, AgentResult
├── policies.py           # RetryPolicy, RouterPolicy
├── registry.py           # ToolRegistry (name → tool lookup)
├── construction.py       # build_tool_schemas, construct_tool_registry
├── tool_runner.py        # ToolRunner (executes a tool call with ToolContext)
├── chat_session.py       # AgentChatSession (stream_packets, WebSocket/SSE)
├── builtins.py           # get_builtin_tools()
├── doctor.py             # AgentDoctor (health report)
├── mcp.py                # RemoteMCPServer, transports, persistent sessions
├── reasoning.py          # ReasoningRuntime (non-streaming reasoning helper)
├── stores/               # MemoryStore, SessionStore, TraceStore implementations
├── llms/                 # LLM adapters (base, openai, anthropic, litellm, simple)
├── tools/                # Built-in tools (web_search, open_url, tool_search, …)
└── prompts/              # Default system prompts
```

## Related

- [Event types](events.md) — full event payload reference
- [Model adapters](adapters.md) — adapter-specific details
