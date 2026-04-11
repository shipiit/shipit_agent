---
title: Parameters Reference
description: Every constructor parameter for every agent type, RAG, memory, and storage class — with types, defaults, and when-to-use notes.
---

# Parameters Reference

A single-page reference to every public constructor parameter in
`shipit_agent`. Use this as the cheat sheet you keep open in another
tab while you build.

Conventions:

- **Type** — Python type hint
- **Default** — value when omitted (or `required` for required args)
- **What it does** — one-line description
- **Use it when** — concrete trigger for setting it

---

## `Agent`

The core class. Every other agent type wraps an `Agent` internally.

```python
from shipit_agent import Agent

agent = Agent(
    llm=llm,
    rag=my_rag,
    max_iterations=8,
    parallel_tool_execution=True,
)
```

| Parameter | Type | Default | What it does | Use it when |
| --- | --- | --- | --- | --- |
| `llm` | `LLM` | required | The LLM client used for every completion. | Always. |
| `prompt` | `str` | `DEFAULT_AGENT_PROMPT` | The system prompt. | Override to give the agent a persona or domain framing. |
| `tools` | `list[Tool]` | `[]` | Tools the agent can call. | Pass your own tool list. Use `with_builtins()` for the full catalogue. |
| `mcps` | `list[MCPServer]` | `[]` | MCP servers attached at run time. | Connect to remote / local MCP tool servers. |
| `name` | `str` | `"shipit"` | Agent identifier surfaced in events and traces. | Multi-agent setups — give each one a name. |
| `description` | `str` | `""` | Free-form description (used in traces and supervisor delegation). | Multi-worker supervisors. |
| `metadata` | `dict[str, Any]` | `{}` | Arbitrary metadata attached to every event. | Tag runs with request id, user id, etc. |
| `history` | `list[Message]` | `[]` | Pre-existing conversation messages to seed the run. | Resume a chat from previous context. |
| `memory_store` | `MemoryStore \| None` | `None` | Long-term memory store. | Cross-conversation knowledge persistence. |
| `session_store` | `SessionStore \| None` | `None` | Conversation history store. | Multi-turn chat with persistence. |
| `credential_store` | `CredentialStore \| None` | `None` | OAuth tokens / API keys. | Tools that need credentials (Slack, Gmail, …). |
| `trace_store` | `TraceStore \| None` | `None` | Audit log of every event. | Production observability. |
| `session_id` | `str \| None` | `None` | Logical session identifier. | Multi-turn chat with `session_store`. |
| `trace_id` | `str \| None` | `None` | Logical trace identifier. | Distributed tracing. |
| `max_iterations` | `int` | `4` | Hard cap on LLM iterations per run. | Bump higher for deep reasoning, lower to fail fast. |
| `retry_policy` | `RetryPolicy` | `RetryPolicy()` | LLM/tool retry behaviour. | Production with flaky upstreams. |
| `router_policy` | `RouterPolicy` | `RouterPolicy()` | Auto-planning + tool routing. | Disable auto-plan with `RouterPolicy(auto_plan=False)`. |
| `parallel_tool_execution` | `bool` | `False` | Run independent tool calls in parallel. | Latency-sensitive runs with multiple parallel calls. |
| `hooks` | `AgentHooks \| None` | `None` | Pre/post-LLM and tool middleware. | Custom logging, redaction, instrumentation. |
| `context_window_tokens` | `int` | `0` | Auto-compact messages above this token count (0 = off). | Long runs against models with finite context. |
| `replan_interval` | `int` | `0` | Re-run the planner every N iterations (0 = off). | Long-horizon tasks where the plan should evolve. |
| `rag` | `RAG \| None` | `None` | Auto-wires RAG tools + system prompt + source tracker. | Grounded answers with citations. |

**Class methods:**

- `Agent.with_builtins(llm=..., **kwargs)` — also wires the full builtin tool catalogue (web search, code exec, file workspace, integrations, …).

---

## `DeepAgent`

Power-user `create_deep_agent` factory. Strict superset of LangChain's
`create_deep_agent`. See [DeepAgent docs](../deep-agents/deep-agent.md).

```python
from shipit_agent.deep import DeepAgent

agent = DeepAgent.with_builtins(
    llm=llm,
    rag=rag,
    verify=True,
    reflect=True,
    max_iterations=20,
)
```

| Parameter | Type | Default | What it does | Use it when |
| --- | --- | --- | --- | --- |
| `llm` | `LLM` | required | Backing LLM client. | Always. |
| `name` | `str` | `"shipit-deep-agent"` | Agent identifier. | Multi-agent setups. |
| `description` | `str` | `"A deep agent that plans, verifies, and uses a workspace."` | Free-form description. | Supervisor delegation. |
| `prompt` | `str` | `DEEP_AGENT_PROMPT` | Opinionated deep-agent system prompt. | Override only if you know what you're doing. |
| `extra_tools` | `list[Tool]` | `[]` | User tools to add on top of the deep tool set. | Add domain-specific tools. |
| `mcps` | `list[MCPServer]` | `[]` | MCP servers. | Tool servers. |
| `workspace_root` | `str` | `".shipit_workspace"` | Filesystem root for `workspace_files`. | Customise where the agent's notes live. |
| **Power features** | | | | |
| `rag` | `RAG \| None` | `None` | Auto-wired RAG with source citations. | Grounded answers. |
| `memory` | `AgentMemory \| None` | `None` | Long-term cross-session memory. | Multi-session knowledge retention. |
| `memory_store` | `MemoryStore \| None` | `None` | Backing memory store. | Custom persistence. |
| `session_store` | `SessionStore \| None` | `None` | Session backing for `chat()`. | Persistent chat. |
| `verify` | `bool` | `False` | Run `verify_output` after every answer; verdict on `result.metadata["verification"]`. | High-stakes answers that must be checked. |
| `reflect` | `bool` | `False` | Wrap in `ReflectiveAgent` — generate, critique, revise loop. | Quality matters more than latency. |
| `reflect_threshold` | `float` | `0.8` | Quality target (0..1) for reflection. | Tune how strict reflection is. |
| `reflect_max_iterations` | `int` | `3` | Max self-critique iterations. | Cap reflection cost. |
| `goal` | `Goal \| None` | `None` | Switch to goal-driven mode (delegates to `GoalAgent`). | You have explicit success criteria. |
| **Runtime tuning** | | | | |
| `max_iterations` | `int` | `8` | Max LLM iterations. | Deeper reasoning vs faster fails. |
| `parallel_tool_execution` | `bool` | `True` | Parallelise independent tool calls. | Default on — disable for debugging. |
| `context_window_tokens` | `int` | `0` | Auto-compact above N tokens. | Very long runs against finite-context models. |
| `retry_policy` | `RetryPolicy \| None` | `None` | Override retry behaviour. | Flaky upstreams. |
| `router_policy` | `RouterPolicy \| None` | `None` | Override routing. | Disable auto-plan. |
| `hooks` | `AgentHooks \| None` | `None` | Middleware. | Custom logging / redaction. |
| `trace_store` | `TraceStore \| None` | `None` | Audit log. | Production observability. |
| `credential_store` | `CredentialStore \| None` | `None` | OAuth tokens. | Connector tools. |
| **Builtins** | | | | |
| `use_builtins` | `bool` | `False` | Bundle the regular built-in tool catalogue. | Default on for `with_builtins()`. |
| `web_search_provider` | `str` | `"duckduckgo"` | Web search backend. | `"brave"`, `"tavily"`, `"serper"`, `"playwright"`. |
| `web_search_api_key` | `str \| None` | `None` | API key for the web search provider. | Required for everything except DDG. |

**Methods:** `run`, `stream`, `chat`, `add_tool`, `add_mcp`. See [DeepAgent docs](../deep-agents/deep-agent.md).

---

## `create_deep_agent` (functional helper)

LangChain-compatible spelling.

```python
from shipit_agent.deep import create_deep_agent

agent = create_deep_agent(
    llm=llm,
    tools=[my_tool, plain_python_function],
    system_prompt="...",
    rag=rag,
    verify=True,
)
```

| Parameter | Type | Default | What it does |
| --- | --- | --- | --- |
| `llm` | `LLM` | required | LLM client. |
| `tools` | `list[Tool \| Callable]` | `None` | Tools or plain Python functions. Functions are auto-wrapped as `FunctionTool`. |
| `system_prompt` | `str` | `DEEP_AGENT_PROMPT` | System prompt. |
| `rag` | `RAG \| None` | `None` | RAG instance. |
| `use_builtins` | `bool` | `False` | Bundle the builtin tool catalogue. |
| `verify` | `bool` | `False` | Verification mode. |
| `reflect` | `bool` | `False` | Reflective mode. |
| `goal` | `Goal \| None` | `None` | Goal-driven mode. |
| `memory` | `AgentMemory \| None` | `None` | Long-term memory. |
| `max_iterations` | `int` | `8` | Iteration cap. |
| `**kwargs` | — | — | Forwarded to `DeepAgent.__init__`. |

---

## `GoalAgent`

Decompose → execute → self-evaluate.

```python
from shipit_agent.deep import Goal, GoalAgent

goal_agent = GoalAgent.with_builtins(
    llm=llm,
    goal=Goal(
        objective="Build a calculator CLI",
        success_criteria=["Handles +,-,*,/", "Has tests", "Has error handling"],
    ),
    rag=rag,
)
result = goal_agent.run()  # GoalResult
```

| Parameter | Type | Default | What it does |
| --- | --- | --- | --- |
| `llm` | `LLM` | required | LLM client. |
| `goal` | `Goal` | required | Objective + success criteria + max_steps. |
| `tools` | `list[Tool]` | `[]` | Tools the inner agent can use. |
| `mcps` | `list[MCPServer]` | `[]` | MCP servers. |
| `use_builtins` | `bool` | `False` | Bundle the builtin tool catalogue. |
| `prompt` | `str` | `"You are a helpful assistant. Complete the task thoroughly."` | System prompt. |
| `memory` | `AgentMemory \| None` | `None` | Long-term memory. |
| `rag` | `RAG \| None` | `None` | RAG instance — forwarded to every inner Agent build. |
| `**agent_kwargs` | — | — | Forwarded to the inner `Agent`. |

`Goal` fields:

| Field | Type | Default |
| --- | --- | --- |
| `objective` | `str` | required |
| `success_criteria` | `list[str]` | `[]` |
| `max_steps` | `int` | `20` |

---

## `ReflectiveAgent`

Generate → critique → revise.

```python
from shipit_agent.deep import ReflectiveAgent

agent = ReflectiveAgent.with_builtins(
    llm=llm,
    quality_threshold=0.8,
    max_reflections=3,
    rag=rag,
)
```

| Parameter | Type | Default |
| --- | --- | --- |
| `llm` | `LLM` | required |
| `tools` | `list[Tool]` | `[]` |
| `mcps` | `list[MCPServer]` | `[]` |
| `reflection_prompt` | `str` | `"Check for accuracy, completeness, and clarity."` |
| `max_reflections` | `int` | `3` |
| `quality_threshold` | `float` | `0.8` |
| `use_builtins` | `bool` | `False` |
| `prompt` | `str` | `"You are a helpful assistant."` |
| `memory` | `AgentMemory \| None` | `None` |
| `**agent_kwargs` | — | Forwarded to inner `Agent` (so `rag=` works). |

---

## `AdaptiveAgent`

Writes new tools at runtime.

```python
from shipit_agent.deep import AdaptiveAgent

agent = AdaptiveAgent.with_builtins(
    llm=llm,
    can_create_tools=True,
    sandbox=True,
)
```

| Parameter | Type | Default |
| --- | --- | --- |
| `llm` | `LLM` | required |
| `tools` | `list[Tool]` | `[]` |
| `mcps` | `list[MCPServer]` | `[]` |
| `can_create_tools` | `bool` | `True` |
| `sandbox` | `bool` | `True` |
| `use_builtins` | `bool` | `False` |
| `prompt` | `str` | `"You are a helpful assistant."` |
| `**agent_kwargs` | — | Forwarded to inner `Agent`. |

---

## `Supervisor`

Coordinates multiple worker agents.

```python
from shipit_agent.deep import Supervisor

supervisor = Supervisor.with_builtins(
    llm=llm,
    worker_configs=[
        {"name": "researcher", "prompt": "You research."},
        {"name": "writer", "prompt": "You write."},
    ],
    rag=rag,
    max_delegations=15,
)
```

| Parameter | Type | Default |
| --- | --- | --- |
| `llm` | `LLM` | required |
| `workers` | `list[Worker]` | required (use `with_builtins(worker_configs=...)` for the easy path) |
| `strategy` | `str` | `"plan_and_delegate"` |
| `allow_parallel` | `bool` | `False` |
| `max_delegations` | `int` | `15` |
| `rag` | `RAG \| None` | `None` — wired into every `with_builtins` worker |
| `**agent_kwargs` | — | Forwarded to every worker `Agent` built via `with_builtins`. |

`Worker` fields:

| Field | Type | Default |
| --- | --- | --- |
| `name` | `str` | required |
| `agent` | `Any` | required |
| `capabilities` | `list[str]` | `[]` |

---

## `PersistentAgent`

Long-running checkpointed task.

```python
from shipit_agent.deep import PersistentAgent

agent = PersistentAgent(
    llm=llm,
    checkpoint_dir="./checkpoints",
    checkpoint_interval=5,
    max_steps=50,
    rag=rag,
)
agent.run("long task", agent_id="task-1")
agent.resume(agent_id="task-1")  # after a crash
```

| Parameter | Type | Default |
| --- | --- | --- |
| `llm` | `LLM` | required |
| `tools` | `list[Tool]` | `[]` |
| `checkpoint_dir` | `str` | `".shipit_checkpoints"` |
| `checkpoint_interval` | `int` | `5` |
| `max_steps` | `int` | `50` |
| `rag` | `RAG \| None` | `None` |
| `**agent_kwargs` | — | Forwarded to inner `Agent`. |

---

## `RAG`

The Super RAG facade. See [Super RAG docs](../rag/index.md).

```python
from shipit_agent.rag import RAG, HashingEmbedder

rag = RAG.default(embedder=HashingEmbedder(dimension=512))
rag.index_file("docs/manual.pdf")
ctx = rag.search("python version", top_k=5, enable_reranking=True)
```

| Parameter | Type | Default | What it does |
| --- | --- | --- | --- |
| `vector_store` | `VectorStore` | required | Cosine vector index. |
| `embedder` | `Embedder \| Callable` | required | Anything coercible to an `Embedder`. |
| `keyword_store` | `KeywordStore \| None` | `None` | Optional BM25 index for hybrid search. |
| `reranker` | `Reranker \| None` | `None` | LLM / Cohere / cross-encoder reranker. |
| `chunker` | `DocumentChunker \| None` | `DocumentChunker()` | Chunking strategy. |
| `auto_embed_on_add` | `bool` | `True` | Set `False` when reloading chunks that already have embeddings. |

`RAG.search` keyword arguments:

| Parameter | Type | Default | What it does |
| --- | --- | --- | --- |
| `query` | `str` | required | Natural-language query. |
| `top_k` | `int` | `5` | Max chunks returned. |
| `filters` | `IndexFilters \| None` | `None` | Scope by source, document_id, metadata, time. |
| `hybrid_alpha` | `float` | `0.5` | 1.0 = pure vector, 0.0 = pure BM25. |
| `enable_reranking` | `bool` | `False` | Run the reranker over top candidates. |
| `enable_recency_bias` | `bool` | `False` | Exponential decay over `created_at`. |
| `chunks_above` | `int` | `0` | Number of preceding neighbouring chunks to expand. |
| `chunks_below` | `int` | `0` | Number of following neighbouring chunks to expand. |

---

## `DocumentChunker`

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `target_tokens` | `int` | `512` | Preferred chunk size. |
| `overlap_tokens` | `int` | `64` | Character-overlap budget between consecutive chunks. |
| `title_prefix_chars` | `int` | `64` | Title characters prepended to `text_for_embedding`. |

---

## `HashingEmbedder` / `CallableEmbedder`

```python
from shipit_agent.rag import HashingEmbedder, CallableEmbedder

# Stdlib-only deterministic embedder (great for tests / demos)
hash_emb = HashingEmbedder(dimension=384, seed="shipit-rag")

# Wrap any callable
def embed(texts: list[str]) -> list[list[float]]:
    return my_provider.embed(texts)

custom_emb = CallableEmbedder(fn=embed, dimension=1536)
```

| Class | Parameter | Default |
| --- | --- | --- |
| `HashingEmbedder` | `dimension` | `384` |
| `HashingEmbedder` | `seed` | `"shipit-rag"` |
| `CallableEmbedder` | `fn` | required |
| `CallableEmbedder` | `dimension` | required |

---

## `LLMReranker`

```python
from shipit_agent.rag import LLMReranker

reranker = LLMReranker(llm=my_llm, batch_size=10)
```

| Parameter | Type | Default |
| --- | --- | --- |
| `llm` | `LLM` | required |
| `batch_size` | `int` | `10` |

---

## `AgentMemory`

```python
from shipit_agent import AgentMemory

memory = AgentMemory.default(llm=llm, embedding_fn=embed)
```

`AgentMemory` is the unified facade over `ConversationMemory`,
`SemanticMemory`, and `EntityMemory`. See the
[Advanced Memory guide](../guides/advanced-memory.md) for the full
parameter set on each component class.

---

## `RetryPolicy`

```python
from shipit_agent.policies import RetryPolicy

policy = RetryPolicy(
    max_retries=3,
    base_delay=1.0,
    max_delay=30.0,
    backoff_factor=2.0,
    retry_on_tool_failure=True,
)
```

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `max_retries` | `int` | `3` | Max retry attempts. |
| `base_delay` | `float` | `1.0` | Initial delay in seconds. |
| `max_delay` | `float` | `30.0` | Cap on delay between retries. |
| `backoff_factor` | `float` | `2.0` | Exponential backoff multiplier. |
| `retry_on_tool_failure` | `bool` | `True` | Retry tools on transient failures. |

---

## `RouterPolicy`

```python
from shipit_agent.policies import RouterPolicy

policy = RouterPolicy(
    auto_plan=True,
    use_tool_search=True,
    tool_search_top_k=5,
)
```

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `auto_plan` | `bool` | `True` | Auto-invoke `plan_task` before the first LLM call. |
| `use_tool_search` | `bool` | `False` | Use `tool_search` to short-list tools. |
| `tool_search_top_k` | `int` | `5` | Number of tools surfaced by `tool_search`. |

---

## `AgentChatSession` (`Agent.chat_session()`, `DeepAgent.chat()`)

```python
session = agent.chat_session(session_id="user-42", trace_id="req-1")
for event in session.stream("Hi"):
    print(event.message)
```

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `agent` | `Agent` | required | The underlying agent. |
| `session_id` | `str` | required | Logical session identifier. |
| `trace_id` | `str \| None` | `None` | Distributed-trace id. |
| `session_store` | `SessionStore \| None` | `None` | Backing store. Defaults to `agent.session_store` or `InMemorySessionStore`. |

---

## Storage backends

| Class | Module | Constructor |
| --- | --- | --- |
| `InMemorySessionStore` | `shipit_agent.stores` | `InMemorySessionStore()` |
| `FileSessionStore` | `shipit_agent.stores` | `FileSessionStore(root="path/")` |
| `InMemoryMemoryStore` | `shipit_agent.stores` | `InMemoryMemoryStore()` |
| `FileMemoryStore` | `shipit_agent.stores` | `FileMemoryStore(root="path/")` |
| `InMemoryTraceStore` | `shipit_agent` | `InMemoryTraceStore()` |
| `FileTraceStore` | `shipit_agent` | `FileTraceStore(root="path/")` |

All four protocols (`SessionStore`, `MemoryStore`, `TraceStore`,
`CredentialStore`) are documented in [Architecture](architecture.md).

---

## CLI — `shipit chat`

```bash
shipit chat [--agent TYPE] [--provider NAME] [--session-id ID]
            [--session-dir PATH] [--workspace PATH]
            [--rag-file PATH ...] [--rag-dim INT]
            [--reflect] [--verify]
            [--goal TEXT] [--criteria TEXT ...]
            [--no-builtins] [--quiet]
```

| Flag | Type | Default | Description |
| --- | --- | --- | --- |
| `--agent` | choice | `deep` | One of `agent`, `deep`, `goal`, `reflective`, `adaptive`, `supervisor`, `persistent`. |
| `--provider` | str | `$SHIPIT_LLM_PROVIDER` | LLM provider override. |
| `--session-id` | str | random | Resume a specific session id. |
| `--session-dir` | path | (in-memory) | Persist sessions to disk. |
| `--workspace` | path | `.shipit_workspace` | Workspace root for `workspace_files`. |
| `--rag-file` | path (repeatable) | `[]` | Index a file before the session starts. |
| `--rag-dim` | int | `512` | `HashingEmbedder` dimension when `--rag-file` is used. |
| `--reflect` | flag | off | Enable reflective mode (`DeepAgent`). |
| `--verify` | flag | off | Enable verification mode (`DeepAgent`). |
| `--goal` | str | none | Goal objective (use with `--agent goal`). |
| `--criteria` | str (repeatable) | `[]` | Goal success criterion. |
| `--no-builtins` | flag | off | Skip the regular builtin tool catalogue. |
| `--quiet` | flag | off | Hide intermediate event stream. |

Slash commands inside the REPL: `/help`, `/agent`, `/agents`, `/tools`,
`/sources`, `/index`, `/rag`, `/goal`, `/reflect`, `/verify`,
`/history`, `/clear`, `/save`, `/load`, `/reset`, `/quiet`, `/info`,
`/exit`, `/quit`. See [DeepAgent docs](../deep-agents/deep-agent.md#live-chat-shipit-chat).

---

## See also

- [Architecture](architecture.md) — runtime internals
- [Event Types](events.md) — every event the runtime emits
- [Deep Agents API](deep-agents-api.md) — programmatic API for deep agents
- [Tools manifest](tools.md) — every built-in tool
