---
title: Glossary
description: Definitions for the terms and concepts used throughout shipit-agent.
---

# Glossary

Quick reference for the terminology used in shipit-agent and its docs.

---

## A

### Agent
The top-level dataclass that bundles an LLM, a tool registry, MCP servers, prompts, policies, and stores into a runnable unit. Construct with `Agent(...)` or `Agent.with_builtins(...)`. See [`agent.py`](https://github.com/shipiit/shipit_agent/blob/main/shipit_agent/agent.py).

### `AgentEvent`
A structured event emitted by the runtime during a `run()` or `stream()` call. Contains `type`, `message`, and `payload`. 14 distinct types exist — see [event types reference](reference/events.md).

### `AgentResult`
The return value of `agent.run()`. Contains the final answer (`output`), the full message history, every event emitted, every tool result, and metadata.

### `AgentRuntime`
The internal class that actually executes an agent. You normally don't construct this directly — `Agent.run()` and `Agent.stream()` create one for you. Lives in [`runtime.py`](https://github.com/shipiit/shipit_agent/blob/main/shipit_agent/runtime.py).

### Artifact
A named file output (markdown report, JSON blob, generated code) produced by the `build_artifact` tool. Tracked separately from conversation history on `AgentResult.artifacts`.

---

## B

### Background thread
The pattern shipit-agent uses for `agent.stream()`. The runtime runs on a daemon thread and pushes events through a `queue.Queue` so the consumer (your code) yields events the instant they're emitted. See [architecture](reference/architecture.md#4-background-thread-for-stream).

### Bedrock tool pairing
AWS Bedrock's Converse API enforces strict 1:1 pairing between `toolUse` blocks in an assistant turn and `toolResult` blocks in the next user turn. shipit-agent guarantees this invariant — see [tool lifecycle](reference/architecture.md#1-tool-useresult-pairing).

---

## C

### `CredentialStore`
Pluggable storage for OAuth tokens and API keys used by connector tools. Implementations: `InMemoryCredentialStore`, `FileCredentialStore`. Custom stores implement the `CredentialStore` protocol.

### `ChatSession`
A thin wrapper around `Agent` that manages conversation state across multiple turns and exposes WebSocket/SSE packet streaming. See [sessions guide](guides/sessions.md).

---

## E

### Event
See `AgentEvent`.

### Event stream
The sequence of `AgentEvent` objects yielded by `agent.stream()`. Strictly ordered, never buffered, never reordered.

---

## I

### Iteration
One pass through the runtime's tool loop. Each iteration: emits `step_started`, calls the LLM, processes any tool calls, returns to the top. Capped by `max_iterations` (default 4).

### Iteration cap
The maximum number of iterations a single `run()` call will perform. If the cap is reached while the model is still requesting tool calls, the runtime gives the model one more turn with `tools=[]` to force a final summary — so `run_completed` is never empty for normal runs.

### `interactive_request`
An event type emitted when a tool returns `metadata.interactive=True` (e.g. `ask_user`, `human_review`). Used for human-in-the-loop flows where the agent pauses and waits for input.

---

## L

### LLM adapter
A class implementing the `LLM` protocol that wraps a specific LLM provider (OpenAI, Anthropic, Bedrock, Vertex AI, etc.) into a unified interface. All adapters return `LLMResponse` with optional `reasoning_content`. See [adapters reference](reference/adapters.md).

### LLM proxy
A self-hosted LiteLLM proxy server that routes requests to multiple LLM providers behind a single OpenAI-compatible API. Use `LiteLLMProxyChatLLM` to talk to one.

### `LLMResponse`
The dataclass returned by every LLM adapter's `complete()` method. Contains `content`, `tool_calls`, `metadata`, and `reasoning_content`.

---

## M

### MCP (Model Context Protocol)
A standard protocol for connecting agents to remote tool servers. shipit-agent has native support via three transports: HTTP, stdio subprocess, and persistent subprocess sessions. See [MCP guide](guides/mcp.md).

### `MemoryStore`
Pluggable storage for facts the agent learns over time. Implementations: `InMemoryMemoryStore`, `FileMemoryStore`. The runtime auto-stores tool results as memory facts.

### `Message`
A single conversation message with `role` (`system`/`user`/`assistant`/`tool`), `content`, and `metadata`. Built into the runtime's message history.

---

## P

### Planner
The built-in `plan_task` tool that generates a structured execution plan before the main work begins. Can run automatically (controlled by `RouterPolicy.auto_plan`) or be invoked explicitly by the model.

---

## R

### Reasoning content
The "thinking" or reasoning block surfaced by some LLMs (OpenAI o-series, Claude extended thinking, Bedrock gpt-oss, DeepSeek R1). shipit-agent extracts this automatically and emits it as `reasoning_started` / `reasoning_completed` events. See [reasoning guide](guides/reasoning.md).

### `RetryPolicy`
The runtime configuration that controls how transient failures are retried. Configurable: `max_llm_retries`, `max_tool_retries`, and which exception types are retryable.

### `RouterPolicy`
The runtime configuration that controls auto-planning and other routing decisions. Set `auto_plan=False` to disable the planner.

### `RuntimeState`
The internal state object the runtime mutates during a run — holds messages, events, and tool results. Returned to the caller via `AgentResult`.

---

## S

### `SessionStore`
Pluggable storage for conversation history. Implementations: `InMemorySessionStore`, `FileSessionStore`. Persists messages so the agent can resume across script restarts. See [sessions guide](guides/sessions.md).

### Streaming
Yielding `AgentEvent` objects incrementally as they're emitted, via `agent.stream()`. Distinct from "non-streaming" `agent.run()` which returns a complete `AgentResult` at the end.

### Sub-agent
A focused subtask delegated by the parent agent to a lightweight LLM call via the `sub_agent` tool. Used for fan-out patterns where the parent decomposes work and farms out pieces.

---

## T

### `Tool`
The protocol every tool implements: `name`, `description`, `prompt_instructions`, `schema()`, `run(context, **kwargs)`. Built-in tools live in `shipit_agent/tools/`. Custom tools follow the same pattern — see [custom tools guide](guides/custom-tools.md).

### `ToolCall`
A model-issued request to invoke a specific tool with specific arguments. Contains `name` and `arguments`. Multiple tool calls per assistant turn are supported.

### `ToolContext`
The first positional argument to every tool's `run()` method. Carries the prompt, system prompt, agent metadata, runtime state, and session ID.

### `ToolOutput`
The return value of a tool's `run()` method. Contains `text` (the LLM-visible output) and `metadata` (structured fields the runtime tracks but the LLM doesn't see directly).

### `ToolRegistry`
The runtime's name-indexed collection of all attached tools. Built from the agent's `tools` list and any MCP-discovered tools.

### `ToolResult`
The runtime's record of a single tool execution: name, output text, metadata. Tracked on `RuntimeState.tool_results` and surfaced on `AgentResult`.

### `ToolRunner`
The internal class that executes tool calls. Strips reserved argument names (`context`, `self`) before forwarding to prevent the [`v1.0.1` collision bug](changelog.md#v101-2026-04-09).

### `tool_search`
A built-in tool that ranks all currently-registered tools by relevance to a plain-language query. Solves the "28 tools in context bloats every prompt" problem. See [tool search guide](guides/tool-search.md).

### `TraceStore`
Pluggable storage for full event logs. Implementations: `InMemoryTraceStore`, `FileTraceStore`. Used for audit logs and replay.

### Trusted publishing
PyPI's OIDC-based release flow where GitHub Actions publishes packages without any API token — the workflow proves its identity to PyPI via signed JWT. Configured at https://pypi.org/manage/project/shipit-agent/settings/publishing/.

---

## See also

- [Architecture reference](reference/architecture.md)
- [Event types reference](reference/events.md)
- [FAQ](faq.md)
