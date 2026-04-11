# Changelog

## v1.0.3 — 2026-04-11

Major feature release. **Super RAG subsystem**, **DeepAgent factory** (verify / reflect / goal / sub-agents), **live multi-agent chat REPL** (`shipit chat`), **Agent memory cookbook**, plus deep docs + notebook coverage. **521 unit tests. 19 Bedrock end-to-end smoke tests. All passing.**

### Super RAG

- **`shipit_agent.rag` subsystem** — pluggable chunker + embedder + vector store + keyword store + hybrid pipeline (vector + BM25 + RRF + recency bias + rerank + context expansion).
- **`rag=` on every agent type** — auto-wires `rag_search` / `rag_fetch_chunk` / `rag_list_sources` tools, augments the system prompt with citation instructions, and attaches `result.rag_sources` with stable `[N]` citation indices.
- **Adapters** — `DrkCacheVectorStore` (pgvector over psycopg2) + lazy Chroma / Qdrant / pgvector.
- **Thread-local per-run source tracker** so concurrent runs never leak citations.

### DeepAgent

- **`shipit_agent.deep.DeepAgent`** — power-user factory bundling seven deep tools: `plan_task`, `decompose_problem`, `workspace_files`, `sub_agent`, `synthesize_evidence`, `decision_matrix`, `verify_output`. [Guide](deep-agents/deep-agent.md)
- **One-flag power features**: `verify=True`, `reflect=True`, `goal=Goal(...)`, `rag=RAG(...)`, `memory=AgentMemory(...)`.
- **`agents=` sub-agent delegation** — plug any mix of agent types as named delegates via a built-in `delegate_to_agent` tool.
- **`create_deep_agent()` functional helper** — auto-wraps plain Python callables as tools.
- **Nested event streaming** — sub-agent events surface inside `tool_completed.metadata['events']`.

### Live chat REPL

- **`shipit chat`** — modern multi-agent terminal REPL. Switch agent types live, index files mid-session, save/load conversations, toggle `reflect`/`verify`, inspect tools and sources. [Guide](deep-agents/deep-agent.md#live-chat-shipit-chat)
- Rich slash commands: `/agent`, `/agents`, `/tools`, `/sources`, `/index`, `/rag`, `/goal`, `/reflect`, `/verify`, `/history`, `/save`, `/load`, `/reset`, `/info`, …
- Pluggable LLM provider via `--provider`; persistent sessions via `--session-dir`.

### Streaming

- **`DeepAgent.stream()`** covers every execution mode (direct, verified, reflective, goal-driven, sub-agent delegation).
- **`PersistentAgent.stream()`** added with per-step checkpointing.
- **`rag_sources` event type** added — emitted after every RAG-backed run.

### Memory

- **Dedicated Agent → Memory cookbook** explaining the two memory systems (`memory_store=` for the LLM's `memory` tool vs `AgentMemory` for application-curated profiles). [Guide](agent/memory.md)
- **DeepAgent auto-hydration** — `memory=AgentMemory(...)` seeds the inner agent's `history` from the conversation summary.
- **Notebook 26** — runnable end-to-end tour.

### Docs

- **New Agent section** (6 pages): Overview, Examples, Streaming, With RAG, With Tools, Memory, Sessions.
- **New Super RAG section** (6 pages): Overview, Standalone, Files & Chunks, With Agent, With Deep Agents, Adapters, API.
- **New DeepAgent page**. [Reference](deep-agents/deep-agent.md)
- **Parameters Reference** — every constructor parameter for every agent type and key class. [Reference](reference/parameters.md)
- **Updated Architecture + Model Adapters** reference pages.
- **Updated quickstart** with Agent / Deep Agent / RAG sections.
- **Updated FAQ** with "Agent types — which one should I use?".
- **5 new notebooks** (22–26): RAG basics, RAG + Agent, RAG + Deep Agents, DeepAgent chat, Agent memory.
- **Full-width docs layout + collapsible TOC** with floating toggle, persistence via localStorage.

### Build

- **`shipit-chat`** script entry point.
- **Granular extras**: `rag`, `rag-openai`, `rag-cohere`, `rag-chroma`, `rag-qdrant`, `rag-pgvector`, `rag-drk-cache`, `rag-pdf`, `rag-docx`, `rag-rerank-cohere`, `rag-rerank-cross-encoder`, plus `bedrock`, `google`, `groq`, `together`, `ollama`. The `all` extra bundles everything.

### Fixed

- **Tool schema format bug** — `RAGSearchTool`, `RAGFetchChunkTool`, `RAGListSourcesTool`, `WebhookPayloadTool` now use the wrapped `{"type": "function", "function": {...}}` shape. Previously they were returning flat dicts and Bedrock's Converse API was rejecting them with empty-name validation errors. New regression test scans every tool for Bedrock compatibility.
- **`memory=AgentMemory` type coercion** — `DeepAgent` and `GoalAgent` no longer auto-assign `AgentMemory.knowledge` (a `SemanticMemory`) into `memory_store=` (which expects a `MemoryStore`). `memory=` now only seeds `history`; users pass `memory_store=` explicitly for the runtime's `memory` tool.
- **`Agent.with_builtins(tools=[...])` keyword collision** — the method now accepts and merges user `tools=` with the builtin catalogue (last-write-wins on name collision).
- **`AgentDelegationTool` streaming** — uses inner agent's `stream()` and packs events into `tool_completed.metadata['events']`.

### Test coverage

- **521 unit tests** (up from 285) — green.
- **19 end-to-end Bedrock smoke tests** in `scripts/smoke_bedrock_e2e.py` cover every public surface end-to-end against real Bedrock.

---

## v1.0.2 — 2026-04-10

Major feature release. Deep agents, structured output, pipelines, agent teams, advanced memory, output parsers, and runtime power features. **285 tests. 12 examples. 8 notebooks. 13 new doc pages.**

### Deep Agents

- **GoalAgent** — Autonomous goal decomposition with success criteria, streaming, and `.with_builtins()`. [Guide](guides/deep-agents.md)
- **ReflectiveAgent** — Self-evaluation with quality scores and revision loop. [Guide](guides/deep-agents.md)
- **Supervisor / Worker** — Hierarchical delegation with quality review. [Guide](guides/deep-agents.md)
- **AdaptiveAgent** — Runtime tool creation from Python code. [Guide](guides/deep-agents.md)
- **PersistentAgent** — Checkpoint and resume across sessions. [Guide](guides/deep-agents.md)
- **Channel / AgentMessage** — Typed agent-to-agent communication. [Guide](guides/deep-agents.md)
- **AgentBenchmark** — Systematic agent testing framework. [Guide](guides/deep-agents.md)
- **Deep Agents API Reference** — Full constructor, method, and return type docs. [Reference](reference/deep-agents-api.md)

### Structured Output & Parsers

- **`output_schema` on Agent.run()** — Pydantic models + JSON schemas. [Guide](guides/parsers-and-structured-output.md)
- **JSONParser, PydanticParser, RegexParser, MarkdownParser**. [Guide](guides/parsers-and-structured-output.md)

### Composition

- **Pipeline** — Sequential, parallel, conditional, function steps, streaming. [Guide](guides/pipelines-and-teams.md)
- **AgentTeam** — LLM-routed multi-agent coordination with streaming. [Guide](guides/pipelines-and-teams.md)

### Advanced Memory

- **ConversationMemory** — buffer/window/summary/token strategies. [Guide](guides/advanced-memory.md)
- **SemanticMemory** — Embedding-based vector search. [Guide](guides/advanced-memory.md)
- **EntityMemory** — Track people, projects, concepts. [Guide](guides/advanced-memory.md)
- **AgentMemory** — Unified interface with `.default()`. [Guide](guides/advanced-memory.md)

### Runtime Power Features

- **Parallel tool execution**. [Guide](guides/parallel-execution.md)
- **Graceful tool failure**. [Guide](guides/error-recovery.md)
- **Context window management**. [Guide](guides/context-management.md)
- **Hooks & middleware**. [Guide](guides/hooks.md)
- **Mid-run re-planning**. [Guide](guides/replanning.md)
- **Async runtime**. [Guide](guides/async-runtime.md)
- **Transient error auto-retry** (429/500/503).

### Changed

- **Selective memory storage** (**breaking**) — Only `persist=True` tool results stored.
- **Safer retry defaults** — `(ConnectionError, TimeoutError, OSError)` instead of `(Exception,)`.

---

## v1.0.1 — 2026-04-09

Maintenance release. Bug fix in the tool runner plus repo hygiene, contributor experience, and CI hardening. **Strongly recommended upgrade** from 1.0.0 if you use Bedrock `gpt-oss-120b`.

### Fixed

- **`ToolRunner` argument collision** — Fixed `TypeError: got multiple values for argument 'context'` when an LLM (notably `bedrock/openai.gpt-oss-120b-1:0`) emits `context` as a tool-call argument. The runner now strips reserved argument names (`context`, `self`) from tool-call arguments before forwarding. Affects every built-in tool.

### Added

- **`CHANGELOG.md`** at repo root in Keep a Changelog format
- **`CONTRIBUTING.md`** with dev setup, commit conventions, PR checklist, and "how to add a new LLM adapter / tool" guides
- **GitHub issue templates** — structured bug report, feature request, and config forms
- **PR template** with 12-item verification checklist
- **Test CI** — `pytest -q` on Python 3.11 + 3.12 × Ubuntu + macOS (4 matrix cells), with smoke-test of all 11 LLM adapter imports
- **Gitleaks secret scanning CI** with SARIF upload to GitHub Security tab, inline PR comments, Actions summary
- **Pre-commit hooks** — trailing whitespace, EOF fixer, YAML/TOML validation, gitleaks v8.21.2, ruff lint + format
- **Gitleaks allowlist** for runtime tool outputs (scraped HTML contains false-positive "API keys" like Pushly domainKeys)

### Changed

- `.gitignore` rewritten to dedupe entries and cover all runtime directories (`site/`, `.eggs/`, `pip-wheel-metadata/`)
- Runtime tool outputs untracked from git (`sessions/`, `traces/`, `memory.json`, `.shipit_notebooks/**`) — they were accidentally committed in 1.0.0

### Security

- Added CI and pre-commit secret scanning to prevent future credential leaks
- No runtime code changed — `shipit_agent/` module is byte-identical to 1.0.0

---

## v1.0.0 — 2026-04-09

First stable release. Focused on making the agent loop **observable, interchangeable, and out of the way**.

### 🧠 Live reasoning / thinking events

- `LLMResponse.reasoning_content` field added to carry thinking/reasoning blocks from any provider
- New `_extract_reasoning()` helper handles three shapes:
    - Flat `reasoning_content` on the response message (OpenAI o-series, `gpt-oss`, DeepSeek R1, Anthropic via LiteLLM)
    - Anthropic `thinking_blocks[*].thinking` (Claude extended thinking)
    - `model_dump()` fallback for pydantic dumps
- Runtime emits `reasoning_started` + `reasoning_completed` events whenever reasoning content is non-empty
- **All three LLM adapters** — `OpenAIChatLLM`, `AnthropicChatLLM`, `LiteLLMChatLLM` / `BedrockChatLLM` — share the extraction helper
- `OpenAIChatLLM` auto-passes `reasoning_effort="medium"` for reasoning-capable models (`o1*`, `o3*`, `o4*`, `gpt-5*`, `deepseek-r1*`)
- `AnthropicChatLLM` supports `thinking_budget_tokens=N` to enable Claude extended thinking

### ⚡ Truly incremental streaming

- `agent.stream()` now runs the agent on a background daemon thread
- Events are pushed through a thread-safe `queue.Queue` as they're emitted
- Consumer loop yields events **the instant they happen** — no buffering, no batched delivery
- Worker exceptions are captured and re-raised on the consumer thread
- Works in Jupyter, VS Code, JupyterLab, WebSocket/SSE transports, and plain terminals

### 🛡️ Bulletproof Bedrock tool pairing

- Planner output is now injected as a `user`-role context message rather than an orphan `role="tool"` message — fixes Bedrock's *"number of toolResult blocks exceeds number of toolUse blocks"* error
- Every `response.tool_calls` entry gets a tool-result message unconditionally:
    - Success → real tool-result
    - Retry → retries first, then final result or error
    - Unknown tool → synthetic `"Error: tool X is not registered"` tool-result
- Stable `call_{iteration}_{index}` tool_call_ids round-trip through message metadata
- Multi-iteration tool loops on Bedrock Claude, gpt-oss, and Anthropic native now work without `modify_params` band-aids

### 🔑 Zero-friction provider switching

- `build_llm_from_env()` walks upward from CWD to discover `.env`, so notebooks and scripts work regardless of where they're launched from
- Seven providers: `openai`, `anthropic`, `bedrock`, `gemini`, `vertex`, `groq`, `together`, `ollama`, plus a generic `litellm` provider
- Per-provider credential validation with clear error messages
- `SHIPIT_OPENAI_TOOL_CHOICE=required` env var to force tool use on lazy models like `gpt-4o-mini`

### 🌐 In-process Playwright for `open_url`

- `OpenURLTool` now uses Playwright's sync Chromium directly (headless, realistic desktop Chrome UA, 1280×800 viewport)
- Handles JS-rendered pages, anti-bot 503s, modern TLS/ALPN
- Stdlib `urllib` fallback when Playwright is not installed — zero third-party HTTP dependencies in the core fallback path
- Errors never raise out of the tool: they return as `ToolOutput` with a `warnings` list in metadata
- Rich metadata: `fetch_method`, `status_code`, `final_url`, `title`

### 🔍 Upgraded `ToolSearchTool`

- Replaced binary substring match with drk_cache-style fuzzy scoring: `SequenceMatcher.ratio() + 0.12 × token_hits`
- Configurable `limit` parameter, clamped to `[1, max_limit]`
- New init kwargs: `max_limit`, `default_limit`, `token_bonus`
- Structured error output for empty queries
- Ranked output with scores and "when to use" hints from `prompt_instructions`
- Noise filter: results below `score=0.05` dropped

### 🪵 Full event taxonomy

14 distinct event types with documented payloads:

`run_started`, `mcp_attached`, `planning_started`, `planning_completed`, `step_started`, `reasoning_started`, `reasoning_completed`, `tool_called`, `tool_completed`, `tool_retry`, `tool_failed`, `llm_retry`, `interactive_request`, `run_completed`

### 🔁 Iteration-cap summarization fallback

- If the model is still calling tools when `max_iterations` is reached, the runtime gives it one more turn with `tools=[]` to force a natural-language summary
- `run_completed` is never empty for normal runs
- Guarded with try/except so summarization failures can't mask the rest of the run

### Other changes

- `pyproject.toml`: `[project.urls]` now points to correct GitHub org, adds `Documentation` and `Changelog` links
- `.env.example`: expanded with all new env vars documented
- `notebooks/04_agent_streaming_packets.ipynb`: full rewrite with .env loading, credential visibility printer, and live Markdown updates
- `README.md`: new v1.0 release section with 8 headline features
- Full MkDocs Material documentation site at [shipiit.github.io/shipit_agent](https://shipiit.github.io/shipit_agent/)

### Breaking changes

None — this is the first stable release. Subsequent 1.x releases will maintain backward compatibility within the 1.x line.
