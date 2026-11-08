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

Every keyword `Agent(...)`, `Agent.with_builtins(...)` and `Agent.for_project(...)` take. Generated from `shipit_agent/agent_setup/settings.py`, where each is documented in full.

### Core

| Parameter | Default | What it does |
| :- | :- | :- |
| `llm` | required | The model adapter. |
| `decision_llm` | `None` | Accepted for compatibility and no longer used for progress narration, which costs no model call at all now. Kept so existing callers keep working rather than raising on an unexpected keyword. |
| `progress_summaries` | `False` | Emit public `agent_decision` / `agent_observation` progress events. Decisions use only prose the primary model already produced; observations use factual tool metadata. |
| `reminder` | `None` | Short standing instruction placed at the very END of the context on every step. Use it for the one or two requirements that must hold every time; a model attends far more reliably to the tokens closest to generation than to the top of a long system prompt. |
| `evict_prior_tool_outputs` | `True` | Replace earlier turns' tool payloads with a short notice, keeping the calls and arguments. A tool result is re-sent on every request of every later turn; once its content is in the answer below it, the payload is pure cost. |
| `media_parser` | `None` | A `shipit_agent.multimodal.MediaParser` (or compatible). When set, inline media references in the user prompt — `[https://…/x.png]`, `![alt](url)`, `[media:id]` — are turned into image/document content blocks on the user turn. |
| `prompt` | the default prompt | The system prompt. |
| `tools` | empty | The tools the agent may call. |
| `mcps` | empty | MCP servers whose tools join the agent's. |
| `required_tools` | empty | Tool names that must execute before this run may finish. The runtime advertises only these tools and uses native required-tool mode first, then resets to automatic selection after they have run. |
| `require_tool_call` | `False` | Require at least one available tool on the first model step, without constraining which one. Mirrors provider `tool_choice="required"`. |
| `max_required_tool_text_chars` | `2048` | Stop a provider that ignores required tool choice from spending its whole output budget narrating a call. The partial prose is discarded and the bounded recovery step receives the same required tool contract. |
| `max_completion_text_chars` | `0` | Optional provider-neutral circuit breaker for one completion's visible text. Zero leaves the provider's token limit authoritative. |
| `max_tool_argument_chars` | `65536` | Provider-neutral circuit breaker for one structured tool call's JSON arguments. This bounds runaway generations before they reach a tool; increase it for tools that intentionally accept very large documents. |
| `name` | `'shipit'` | The agent's name, in events and traces. |
| `description` | `''` | What the agent does; used when it is a tool of another agent. |
| `metadata` | empty | Free-form data carried on events and results. |
| `history` | empty | Messages to start the conversation with. |

### Persistence

| Parameter | Default | What it does |
| :- | :- | :- |
| `memory_store` | `None` | Where the `memory` tool saves facts. [Memory](../agent/memory.md). |
| `session_store` | `None` | Where conversations are saved between runs. [Sessions](../agent/sessions.md). |
| `credential_store` | `None` | Where connector credentials are read from. |
| `trace_store` | `None` | Where run traces are written. |
| `observability` | `'auto'` | Report this agent's runs through shipit-watcher — traces, the agent graph, scores, datasets and the local ledger.  `True` attaches it, `False` never does, and the default `"auto"` attaches it only when shipit-watcher is installed *and* configured with credentials. |
| `session_id` | `None` | The conversation to continue. |
| `trace_id` | `None` | The trace id for this agent's runs. |

### Runtime tuning

| Parameter | Default | What it does |
| :- | :- | :- |
| `max_iterations` | `None` | Most model steps a run may take. `None` (the default) means no limit: the run ends when the model answers without calling a tool, as in the Claude Agent SDK. |
| `max_turns` | `None` | The Claude Agent SDK's name for `max_iterations`; set either one. |
| `retry_policy` | empty | Retries for transient model and tool errors. [RetryPolicy](#retrypolicy). |
| `fallback_model` | `None` | Used when the model fails after its retries: a model id, ids separated by commas, an adapter, or a list of them (see `llms/fallback.py`). |
| `router_policy` | empty | When to plan before the first turn. [RouterPolicy](#routerpolicy). |
| `parallel_tool_execution` | `True` | Run a response's tool calls concurrently when every one is read-only. Writes and unknown tools always run one at a time, in order. |
| `max_tool_concurrency` | `None` | None means no cap; otherwise bound concurrent local tool calls per turn. |
| `hooks` | `None` | Code run before and after model calls and tools. [Hooks](../guides/hooks.md). |
| `plugins` | empty | Drop-in plugin packs: Plugin objects or catalog names. Each contributes tools and lifecycle hooks, folded in at construction (see shipit_agent.plugins). |
| `gate_unavailable_tools` | `True` | Hide tools whose declared dependency is missing (a CLI binary not on PATH, an unset env var, a failing `check_fn`) so their schema never costs tokens and the model never wastes a turn calling something that cannot run. Only tools that *declare* requirements can be gated, so this is safe to leave on: a tool with no declaration is always kept. |
| `context_window_tokens` | `0` | 0 = automatic model limit; positive = explicit limit; -1 = disabled. |
| `clear_tool_results` | `None` | Clear old tool results from each request on long tasks (the history keeps them): True, or a ToolResultClearing. See context/tool_result_clearing.py. |
| `fixed_prefix_tokens` | `0` | The fixed prompt prefix (system prompt + tool schemas) is sent on every call but lives outside `messages`, so the compaction trigger under-counts the real prompt by this whole prefix unless it is told. A host that knows its prefix size can pass an estimate here to make compaction accurate from the first turn; leaving it 0 lets the token calibrator learn the gap over a few completions instead. |
| `max_tool_output_chars` | `16000` | Bound only the model-visible copy; AgentResult keeps complete tool output. Capped by default: a message list is cumulative, so one 138,000-character tool result is not paid once — it is re-sent on every turn that follows it. |
| `max_tool_output_group_chars` | `48000` | Parallel calls share this model-context budget. Complete outputs remain available in AgentResult and live tool events. |
| `persist_large_tool_outputs` | `False` | Optimized agents spill complete large results under .shipit so the model can fetch omitted sections without paying for the whole body every turn. |
| `replan_interval` | `0` | Re-plan every N turns; `0` never. [Re-planning](../guides/replanning.md). |
| `stream_queue_maxsize` | `256` | How many events `stream()` buffers before the run waits for the reader. |
| `cancel_on_stream_close` | `True` | Cancel the run when the reader stops iterating `stream()`. |
| `stream_join_timeout` | `2.0` | Seconds to wait for the run's thread when a stream closes. |

### RAG

| Parameter | Default | What it does |
| :- | :- | :- |
| `rag` | `None` | A RAG the agent searches and cites. [RAG with an agent](../rag/with-agent.md). |

### Verifier

| Parameter | Default | What it does |
| :- | :- | :- |
| `verifier` | `None` | Optional `VerifierNetwork` that runs pre-tool veto checks on every tool call and (when used in autopilot-style loops) progress checks between iterations. See `shipit_agent/verifier/`. |

### Permissions

| Parameter | Default | What it does |
| :- | :- | :- |
| `permission_mode` | `'default'` | Rule-based gate over tool calls. Set a mode ("default" \| "acceptEdits" \| "plan" \| "bypass"), or pass a full `PermissionEngine` / kwargs dict via `permissions`, or a `permission_callback(name, args) -> PermissionResult \| None` for programmatic human-in-the-loop approval. |
| `permissions` | `None` | A `PermissionEngine`, a mode name or a dict of its settings. [Permissions](../guides/permissions.md). |
| `permission_callback` | `None` | `(tool_name, arguments) -> PermissionResult \| None`, for calls that would ask. |
| `harness` | `None` | A :class:`~shipit_agent.harness.Harness`: plugins and settings files. |
| `allowed_tools` | empty | Pre-approved calls, as SDK rules: `"Read"`, `"Bash(npm test *)"`. They approve; they do not restrict the other tools. |
| `disallowed_tools` | empty | A bare name removes the tool from the run; a scoped rule such as `"Bash(rm *)"` denies matching calls in every permission mode. |

### Guardrails

| Parameter | Default | What it does |
| :- | :- | :- |
| `guardrails` | `None` | A `Guardrails` instance: blocks prompt-injection inputs, redacts secrets/PII from outputs, and denies tool calls whose arguments match configured patterns. See `shipit_agent.guardrails`. |

### Deferred approvals

| Parameter | Default | What it does |
| :- | :- | :- |
| `approvals` | `None` | An `ApprovalQueue` (or `True` for a fresh one). Side-effecting tools the policy marks `ask` are queued instead of blocking the run; you approve later, in bulk. |

### Code mode

| Parameter | Default | What it does |
| :- | :- | :- |
| `code_mode` | `False` | Collapse the tool catalogue into a small core set plus an `env` of resource bindings reachable from `execute_code`. Cuts the tool-schema block by ~79% and lets one call compose several resources. |

### Deferred tool loading

| Parameter | Default | What it does |
| :- | :- | :- |
| `deferred_tools` | `'auto'` | Default "auto": above ten tools, keep nine core capabilities and a discovery tool. discovery_priority on a tool overrides core ranking; ties follow registration order. |

### Lockdown

| Parameter | Default | What it does |
| :- | :- | :- |
| `lockdown` | `None` | Once a tool reports it returned sensitive data, the run may only make observations — every action is denied for the rest of the run, so the data cannot leave through another tool. Honours declarations by default and detects nothing; pass a LockdownPolicy to add detection, or False to disable. |
| `verify_before_stop` | `False` | Evidence-gated coding: refuse to finish a turn that edited code without fresh passing tests (the verification ledger + verify-on-stop guard). Off by default — it changes the loop's stop behaviour, so a caller opts in. |

### Delegation

| Parameter | Default | What it does |
| :- | :- | :- |
| `delegation` | `None` | Reach for sub-agents without being asked: guarantee a `sub_agent` tool exists, and when a task carries delegation signals (a per-item verb, an enumerated work list, a wide sweep) append a directive naming what was detected. The model still decides — it decides with the tool present and the case put plainly. |

### Self-healing tool calls

| Parameter | Default | What it does |
| :- | :- | :- |
| `heal_tool_calls` | `True` | Promote tool calls that small models emit as TEXT (<tool_call> tags, fenced JSON, bare call-shaped JSON) into structured calls. Response- side only; only declared tool names qualify. |

### Project and file tools

| Parameter | Default | What it does |
| :- | :- | :- |
| `project_root` | `'/tmp'` | The folder the file tools and bash work in; paths outside it are refused. |

### Workspace

| Parameter | Default | What it does |
| :- | :- | :- |
| `auto_project_memory` | `True` | Auto-load SHIPIT.md / AGENTS.md project instructions into the system prompt, and expand `/slash` commands from .shipit/commands/ on run(). |

### Skills

| Parameter | Default | What it does |
| :- | :- | :- |
| `skill_registry` | `None` | A `SkillRegistry` to choose skills from. |
| `skill_source` | see code | A folder or catalog file to load skills from. |
| `auto_use_skills` | `True` | Pick skills that match the prompt automatically. |
| `auto_project_skills` | `True` | Load skills from the project's `.shipit/skills/`. |
| `skills` | empty | Skills to attach to every run, by id or object. |
| `default_skill_ids` | empty | Skill ids always active. |
| `skill_match_limit` | `3` | Most skills chosen for one prompt. |
| `progressive_skills` | `True` | Skills load on demand, as in Claude Code: the prompt lists each in one line and the model reads one with `load_skill` when it needs it. False restores keyword matching that injects whole skills. |
| `advertise_packaged_skills` | `False` | List the library's packaged skill catalog too. Off by default: the catalog lists the project's own SKILL.md files and any registry you pass; packaged skills stay usable by id through `skills=[...]`. |
| `agents` | empty | Named sub-agents, as in the Claude Agent SDK: `{"reviewer": { "description": ..., "prompt": ..., "tools": [...], "model": ...}}`. Defining any gives the agent a `sub_agent` tool that lists them. |
| `auto_project_agents` | `True` | Also read sub-agents from `.shipit/agents/*.md` and `.claude/agents/*.md`. |
| `max_task_tokens` | `None` | Stop the run after this many tokens. |
| `max_budget_usd` | `None` | Stop a run, between steps, once its estimated cost reaches this many US dollars. Needs pricing data for the model; without it the run stops rather than spend unchecked. |
| `max_session_tokens` | `None` | Soft stop across every run of this agent (or one chat session), checked between steps. Clones start fresh; reset with reset_session_usage(). |

### Rules

| Parameter | Default | What it does |
| :- | :- | :- |
| `rules` | empty | Durable behavioural policy (AGENTS.md house-style), scoped to paths/tools and ordered by priority — the complement to skills' capability. Strings, dicts, or Rule objects; discovered `.shipit/rules/*.md` are merged in when auto_project_rules is on. |
| `auto_project_rules` | `True` | Read rules from the project's `AGENTS.md` and rule files. |

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
| `max_tool_concurrency` | `int \| None` | `None` | Cap concurrently executing tools. | `DeepAgent.for_project()` defaults this to `4`. |
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
    max_llm_retries=3,
    max_tool_retries=1,
    llm_retry_base_delay=0.5,
    llm_retry_max_delay=30.0,
    request_timeout=120.0,
)
```

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `max_llm_retries` | `int` | `2` | Retries for a transient model error (rate limit, overload, network). |
| `max_tool_retries` | `int` | `1` | Retries for a tool that raised one of `retry_on_exceptions`. |
| `retry_on_exceptions` | `tuple[type[Exception], ...]` | `(ConnectionError, TimeoutError, OSError)` | Tool exceptions worth retrying. |
| `llm_retry_base_delay` | `float` | `0.5` | First backoff delay in seconds; it doubles each retry. |
| `llm_retry_max_delay` | `float` | `30.0` | Longest backoff delay. A provider's `Retry-After` is honoured up to this. |
| `llm_retry_jitter` | `bool` | `True` | Randomise delays so parallel agents do not retry in step. |
| `request_timeout` | `float \| None` | `None` | Seconds before a model call is abandoned. |
| `fallback_llms` | `tuple` | `()` | Models to try, in order, when the main one keeps failing. |

---

## `RouterPolicy`

```python
from shipit_agent.policies import RouterPolicy

policy = RouterPolicy(auto_plan=True, long_prompt_threshold=200)
```

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `auto_plan` | `bool` | `False` | Run the planner before the first turn when the prompt looks like a planning task. |
| `plan_keywords` | `tuple[str, ...]` | `("plan", "build", "create", ...)` | Words that make a prompt a planning task. |
| `long_prompt_threshold` | `int` | `160` | A prompt longer than this many characters is planned too. |

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
| `FileSessionStore` | `shipit_agent.stores` | `FileSessionStore("path/")` |
| `InMemoryMemoryStore` | `shipit_agent.stores` | `InMemoryMemoryStore()` |
| `FileMemoryStore` | `shipit_agent.stores` | `FileMemoryStore("path.json")` |
| `InMemoryTraceStore` | `shipit_agent` | `InMemoryTraceStore()` |
| `FileTraceStore` | `shipit_agent` | `FileTraceStore("path/")` |

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
