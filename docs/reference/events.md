# Event Types Reference

Every `AgentEvent` has:

```python
@dataclass
class AgentEvent:
    type: str              # event type name, e.g. "tool_called"
    message: str           # human-readable label
    payload: dict          # event-specific fields
```

## Full event reference

### `run_started`
Emitted once at the very start of a run.

**Payload:**
- `prompt: str` — the user's input prompt

---

### `mcp_attached`
Emitted once per attached MCP server, after `run_started`.

**Payload:**
- `server: str` — MCP server name

---

### `planning_started`
Emitted if `router_policy.should_plan(prompt)` returns `True`. The `plan_task` tool runs immediately after.

**Payload:**
- `prompt: str`

---

### `planning_completed`
The planner's output is injected into message history as a `user`-role context message (not as a `tool`-role result, to preserve Bedrock tool-pairing).

**Payload:**
- `output: str` — the planner's text output

---

### `step_started`
Each iteration of the tool loop, right before `llm.complete()` is called.

**Payload:**
- `iteration: int` — 1-indexed iteration number
- `tool_count: int` — number of tool schemas sent to the LLM

---

### `reasoning_started`
🧠 The LLM response contained non-empty reasoning / thinking content.

**Payload:**
- `iteration: int`

---

### `reasoning_completed`
Carries the full reasoning text. Always immediately follows `reasoning_started`.

**Payload:**
- `iteration: int`
- `content: str` — the reasoning text

---

### `tool_called`
The model decided to call a tool. Fires **before** execution.

**Message:** `"Tool called: <name>"`

**Payload:**
- `tool: str` — registered tool name
- `call_id: str` — stable ID for pairing calls, chunks, and outcomes
- `iteration: int`
- `arguments: dict` — tool arguments as parsed from the LLM

---

### `tool_output_started`
The runtime opened a tool output stream. This event can repeat if a tool call
is retried.

**Payload:**
- `tool: str`
- `call_id: str`
- `attempt: int`
- `buffered: bool` — `True` when guardrails must sanitize before publication

---

### `tool_output_delta`
One provisional output chunk. Custom generator tools can emit many chunks;
large ordinary and MCP responses are split into bounded chunks for responsive
terminal and browser consumers.

**Payload:**
- `tool: str`
- `call_id: str`
- `chunk: str`
- `chunk_metadata: dict`
- `sequence: int` — monotonically increasing within the call
- `attempt: int`

---

### `tool_completed`
Tool finished successfully.

**Message:** `"Tool completed: <name>"`

**Payload:**
- `tool: str`
- `call_id: str`
- `iteration: int`
- `output: str` — tool output text
- `output_chars: int` — complete canonical output size
- `model_output_chars: int` — size placed in the next model turn
- `model_output_reduced: bool` — deduplication or context limits reduced the model copy
- `metadata: dict` — lightweight metadata; heavy canonical MCP fields remain on `ToolResult`

---

### `tool_retry`
Transient tool failure, retry scheduled by `RetryPolicy`.

**Payload:**
- `iteration: int`
- `attempt: int` — retry attempt number (1-indexed)
- `error: str`

---

### `tool_failed`
Non-retryable tool error, **or** the model hallucinated an unregistered tool name. In the second case, a synthetic `"Error: tool X is not registered"` tool-result message is still appended to keep pairing balanced.

**Payload:**
- `iteration: int`
- `error: str`

---

### `llm_retry`
Transient LLM provider error, retry scheduled.

**Payload:**
- `attempt: int`
- `error: str`

---

### `interactive_request`
A tool returned `metadata.interactive=True`. Your UI can pause and collect input.

**Payload:**
- `kind: str` — e.g. `"ask_user"`, `"human_review"`
- `payload: dict` — tool metadata (usually contains the question and expected response format)

---

### `run_completed`
Final event. Fires once the loop exits or hits the iteration cap.

**Payload:**
- `output: str` — final answer (legacy name)
- `content: str` — final answer (explicit name)
- `format: str` — output format, e.g. `"markdown"`

## Serialization

All events serialize cleanly to JSON via `event.to_dict()`:

```python
{
    "type": "tool_called",
    "message": "Tool called: web_search",
    "payload": {
        "iteration": 1,
        "arguments": {"query": "bitcoin price"}
    }
}
```

## Related

- [Streaming guide](../guides/streaming.md) — high-level usage
- [Architecture](architecture.md) — how events fit into the runtime
