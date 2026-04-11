---
title: Architecture
description: How shipit_agent is built — runtime loop, layers, key invariants, and how every subsystem (RAG, deep agents, sessions, MCP) plugs in.
---

# Architecture

`shipit_agent` is built around a small, focused runtime with clean
boundaries between concerns. There are no chains, no graphs, no
mandatory inheritance hierarchies — just a runtime that executes
LLM calls and tool calls with strong invariants on streaming, error
recovery, and tool/result pairing.

Everything in this page is the result of reading the actual source —
`shipit_agent/runtime.py` is one file you can hold in your head.

---

## The big picture

```
                    ┌──────────────────────────────────────────────────┐
                    │                  user code                       │
                    │     Agent / DeepAgent / GoalAgent / ...          │
                    └──────────────────────┬───────────────────────────┘
                                           │
                       ┌───────────────────┼───────────────────┐
                       │                   │                   │
                       ▼                   ▼                   ▼
                ┌──────────┐         ┌───────────┐       ┌──────────────┐
                │ DeepAgent│         │ AgentChat │       │ shipit chat  │
                │ (factory)│         │  Session  │       │     CLI      │
                └────┬─────┘         └─────┬─────┘       └──────┬───────┘
                     │                     │                    │
                     ▼                     ▼                    ▼
                ┌──────────────────────────────────────────────────┐
                │                       Agent                      │
                │  llm · tools · mcps · prompt · policies · stores │
                │  rag · memory · session · trace · credentials    │
                └──────────────────────┬───────────────────────────┘
                                       │
                          ┌────────────▼────────────┐
                          │      AgentRuntime       │
                          │   run() / stream()      │
                          └────────────┬────────────┘
                                       │
        ┌───────────────┬──────────────┼──────────────┬──────────────┐
        ▼               ▼              ▼              ▼              ▼
  ┌─────────┐    ┌────────────┐  ┌──────────┐   ┌──────────┐   ┌──────────┐
  │   LLM   │    │    Tool    │  │   MCP    │   │   RAG    │   │  Stores  │
  │ Adapter │    │  Registry  │  │ Servers  │   │ subsystem│   │ session/ │
  └─────────┘    └─────┬──────┘  └────┬─────┘   └─────┬────┘   │  memory/ │
                       │              │               │        │  trace   │
                       ▼              ▼               ▼        └──────────┘
                 ┌──────────┐    ┌──────────┐  ┌────────────┐
                 │  Builtin │    │ Transport│  │ Vector +   │
                 │   Tools  │    │  layer   │  │ Keyword +  │
                 │   (30+)  │    │          │  │ Reranker   │
                 └──────────┘    └──────────┘  └────────────┘
```

---

## The runtime loop

The heart of the library is `AgentRuntime.run` (and its streaming
counterpart `AgentRuntime.stream`). Pseudo-code:

```python
def run(user_prompt):
    state = RuntimeState()
    load_session()
    if rag is not None: rag.begin_run()           # source tracking starts here
    emit("run_started")

    if router_policy.auto_plan:
        run_planner()
        emit("planning_completed")  # injected as user-role message

    for iteration in range(1, max_iterations + 1):
        emit("step_started")
        compacted = maybe_compact_messages(state.messages, context_window_tokens)
        response = llm.complete(messages=compacted, tools=tool_schemas)
        track_usage(response)

        if response.reasoning_content:
            emit("reasoning_started")
            emit("reasoning_completed")

        if not response.tool_calls:
            break

        append_assistant_message_with_tool_uses(response)
        for tool_call in response.tool_calls:
            emit("tool_called")
            try:
                result = run_tool(tool_call)            # may use parallel pool
                append_tool_result_message(result)
                emit("tool_completed")
            except Exception as exc:
                append_synthetic_tool_error_message(exc)
                emit("tool_failed")

    if hit_iteration_cap:
        # one final summarisation turn with tools=[] so the answer
        # is never empty.
        response = llm.complete(tools=[])

    save_session()
    save_memory()
    if rag is not None:
        sources = rag.end_run()
        emit("rag_sources", sources=sources)
    emit("run_completed")
    return state, response
```

Real source: `shipit_agent/runtime.py` — readable end-to-end in a sitting.

---

## Key invariants

These guarantees are what make the runtime predictable across providers
and across long, multi-step runs.

### 1. Tool use/result pairing

Every `toolUse` block in an assistant turn is matched by exactly one
`toolResult` block in the next user turn. This is enforced
unconditionally:

| Outcome | Result message appended |
| --- | --- |
| Tool succeeds | Real `ToolOutput` content |
| Tool raises a retryable error | Retry loop, then real or synthetic error |
| Tool raises non-retryable error | Synthetic `"Error: …"` message |
| Model hallucinates an unknown tool name | Synthetic `"Error: tool X is not registered"` |
| Planner runs | Output injected as `role="user"` context — **never** as `role="tool"` |

This is why Bedrock's strict Converse API works reliably across
multi-iteration tool loops.

### 2. Reasoning extraction

The LLM adapter populates `LLMResponse.reasoning_content` from whatever
shape the provider returns (OpenAI o-series, Anthropic extended
thinking, Bedrock gpt-oss, DeepSeek R1, …). The runtime emits
`reasoning_started` / `reasoning_completed` events automatically — no
configuration required.

### 3. Events are immutable, ordered, and incremental

Every event is a frozen `AgentEvent` dataclass. The stream is strictly
ordered: events are yielded in emission order with no reordering, no
deduplication, no batching.

`stream()` runs the runtime on a background daemon thread and yields
events via a `queue.Queue` so each event arrives the **instant** it's
emitted. Worker exceptions are re-raised on the consumer side.

### 4. Tool/result pairing extends to parallel execution

When `parallel_tool_execution=True`, the runtime fans tool calls out
across a `ThreadPoolExecutor`. Results are collected and appended in
the same order as the original `tool_calls` list, so pairing is still
guaranteed.

### 5. RAG source tracking is per-run and thread-local

`Agent.run` calls `rag.begin_run()` at the top and `rag.end_run()` at
the bottom. The tracker uses **thread-local state** so concurrent runs
on different threads don't bleed citations into each other. The
captured `RAGSource` list is attached to `result.rag_sources` and (in
streaming mode) emitted as a final `rag_sources` event.

### 6. The runtime is the only thing that talks to the LLM

Every other subsystem (`RAG`, deep agents, hooks, sessions, …) goes
through the runtime. There is no second code path. This is what keeps
the public surface coherent.

---

## Layered composition

Agent types stack on top of each other. Reading bottom-up:

| Layer | Class | What it adds |
| --- | --- | --- |
| 1 | `LLM` adapter | Provider-specific request shaping + reasoning extraction |
| 2 | `AgentRuntime` | The loop above — events, pairing, retries, compaction |
| 3 | `Agent` | High-level facade — tools, RAG, memory, sessions, hooks |
| 4 | `AgentChatSession` | Multi-turn chat over a single agent + session store |
| 5 | `GoalAgent` / `ReflectiveAgent` / `AdaptiveAgent` / `Supervisor` / `PersistentAgent` | Specialised behaviours that wrap an inner `Agent` |
| 6 | `DeepAgent` | Power-user factory — bundles seven deep tools, an opinionated prompt, and one-flag access to verification, reflection, goal mode, sub-agents |
| 7 | `shipit chat` REPL | Live multi-agent terminal CLI on top of any of the above |

Each layer is independent: you can drop straight in at layer 3
(`Agent`) without ever touching layer 6, or you can chain the layers
arbitrarily — `DeepAgent.with_builtins(agents=[GoalAgent(...), DeepAgent(...)])`
is a perfectly valid topology.

---

## Subsystem snapshot

### Tools

`Tool` is a 4-method protocol (`name`, `description`, `schema`, `run`).
The `ToolRegistry` looks up tools by name; `ToolRunner` executes a
single call with a `ToolContext` (prompt, metadata, state, session id).
Built-in tools live under `shipit_agent/tools/`. Tool creation at
runtime is supported by `AdaptiveAgent`.

### MCP

`MCPServer` wraps a transport (`MCPSubprocessTransport`,
`MCPHTTPTransport`, `PersistentMCPSubprocessTransport`,
`RemoteMCPServer`) and exposes its tools through the same `Tool`
protocol. Discovery failures log a warning and continue — they don't
crash the agent.

### RAG (Super RAG)

`shipit_agent.rag` is a self-contained subsystem with its own
`VectorStore`, `KeywordStore`, `Embedder`, and `Reranker` protocols.
The `RAG` facade ties them together with a `HybridSearchPipeline`
(vector + BM25 + RRF + optional rerank + context expansion). When you
pass `rag=` to `Agent`, three tools are auto-wired and a per-run
`SourceTracker` captures every retrieved chunk into
`AgentResult.rag_sources`. Adapters in
`shipit_agent.rag.adapters` (DRK_CACHE, Chroma, Qdrant, pgvector) plug
into the same protocols. See [Super RAG](../rag/index.md).

### Stores

Three orthogonal store protocols, each with `InMemory*` and `File*`
implementations:

| Store | Stores | Used by |
| --- | --- | --- |
| `SessionStore` | `SessionRecord` (messages + metadata) | `AgentChatSession`, multi-turn chat |
| `MemoryStore` | `MemoryFact` (timestamped knowledge) | Long-term memory |
| `TraceStore` | `TraceRecord` (event audit log) | Production observability |
| `CredentialStore` | `CredentialRecord` (OAuth tokens, API keys) | Connector tools |

All four are dataclass-backed, JSON-serialisable, and pluggable.

### Hooks

`AgentHooks` exposes `before_llm`, `after_llm`, `before_tool`, and
`after_tool`. Use it for custom logging, redaction, instrumentation,
and side-channels. Hooks fire on the runtime thread; long-running work
should be deferred to a queue.

### Policies

| Policy | Purpose |
| --- | --- |
| `RetryPolicy` | Per-LLM-call and per-tool-call retry config |
| `RouterPolicy` | `auto_plan`, `use_tool_search`, `tool_search_top_k` |

---

## Module layout

```
shipit_agent/
├── agent.py              Agent dataclass + profile composition
├── runtime.py            AgentRuntime (run/stream)  ← the loop above
├── async_runtime.py      AsyncAgentRuntime (asyncio variant)
├── models.py             Message, ToolCall, ToolResult, AgentEvent, AgentResult
├── policies.py           RetryPolicy, RouterPolicy
├── registry.py           ToolRegistry (name → tool lookup)
├── construction.py       build_tool_schemas, construct_tool_registry
├── tool_runner.py        ToolRunner (executes a tool call with ToolContext)
├── chat_session.py       AgentChatSession (stream / packets / WebSocket / SSE)
├── chat_cli.py           Modern multi-agent terminal REPL — `shipit chat`
├── cli.py                `shipit run` and `shipit chat` entry points
├── builtins.py           get_builtin_tools()
├── doctor.py             AgentDoctor (health report)
├── reasoning.py          ReasoningRuntime helper
├── context_tracker.py    ContextTracker (token budget snapshots)
├── schedule.py           ScheduleRunner (cron-driven runs)
├── session_manager.py    SessionManager (create/resume/fork/archive)
├── templates.py          PromptTemplate ({var.path} substitution)
├── webhook_payload tool  Triggering payload exposed to the agent
├── stores/               SessionStore, MemoryStore, TraceStore (in-memory + file)
├── tracing.py            FileTraceStore + InMemoryTraceStore
├── memory/               ConversationMemory, SemanticMemory, EntityMemory, AgentMemory
├── llms/                 LLM adapters (openai, anthropic, litellm, simple, …)
├── tools/                30+ built-in tools (web_search, code_execution, …)
├── deep/                 Deep agents
│   ├── goal_agent.py
│   ├── reflective_agent.py
│   ├── adaptive_agent.py
│   ├── supervisor.py
│   ├── persistent_agent.py
│   ├── benchmark.py      AgentBenchmark
│   ├── channel.py        Channel + AgentMessage
│   └── deep_agent/       create_deep_agent factory
│       ├── prompt.py     DEEP_AGENT_PROMPT
│       ├── toolset.py    deep_tool_set + merge_tools
│       ├── verification.py  verify_text helper
│       ├── delegation.py    AgentDelegationTool (sub-agent delegation)
│       └── factory.py    DeepAgent class + create_deep_agent
├── rag/                  Super RAG subsystem
│   ├── types.py          Document, Chunk, RAGContext, RAGSource, …
│   ├── chunker.py        DocumentChunker (sentence-aware, title prefix)
│   ├── embedder.py       Embedder protocol + HashingEmbedder, CallableEmbedder
│   ├── vector_store.py   VectorStore + InMemoryVectorStore
│   ├── keyword_store.py  KeywordStore + InMemoryBM25Store
│   ├── reranker.py       Reranker + LLMReranker
│   ├── search_pipeline.py HybridSearchPipeline (RRF + recency + rerank + expand)
│   ├── extractors.py     TextExtractor (TXT/MD/HTML/PDF/DOCX)
│   ├── rag.py            RAG facade
│   ├── tools.py          rag_search / rag_fetch_chunk / rag_list_sources
│   └── adapters/         drk_cache, chroma, qdrant, pgvector
├── pipeline/             Pipeline + Step (sequential/parallel composition)
├── team/                 AgentTeam, TeamRound, TeamResult (multi-agent coordination)
├── parsers/              JSONParser, MarkdownParser, PydanticParser, RegexParser
├── integrations/         OAuth helpers + CredentialStore
├── packets.py            SSE / WebSocket event encoders
├── hooks.py              AgentHooks (before/after LLM + tool middleware)
├── profiles.py           AgentProfile (reusable configuration bundles)
├── exceptions.py         ShipitAgentError, DuplicateToolError
└── prompts/              Default system prompts
```

---

## Streaming guarantees in one paragraph

`Agent.stream` runs the runtime on a background daemon thread, pushes
each `AgentEvent` onto a `queue.Queue` the moment it's emitted, and
yields them on the consumer thread. There is no buffering. There is no
batching. There is no reordering. If the worker raises, the exception
is re-raised on the consumer the next time it pulls from the queue, so
errors surface as if they happened inline. Closing the generator (or
breaking out of the `for` loop) cleans up the worker thread
automatically.

---

## Related

- [Event types](events.md) — full event payload reference
- [Model adapters](adapters.md) — provider-specific details
- [Parameters reference](parameters.md) — every constructor parameter
- [Deep agents API](deep-agents-api.md)
- [Super RAG API](../rag/api.md)
