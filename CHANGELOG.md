# Changelog

All notable changes to **shipit-agent** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.3] — 2026-04-11

Major feature release. **Super RAG subsystem**, **DeepAgent factory** with
verification / reflection / goal / sub-agent modes, **live multi-agent chat
REPL** (`shipit chat`), **Agent memory cookbook**, and deep docs + notebook
coverage across every new surface. **521 unit tests. 19 Bedrock end-to-end
smoke tests. All passing.**

### Super RAG (new)

- **`shipit_agent.rag` subsystem** — a self-contained, pluggable
  retrieval-augmented-generation stack:
  - `RAG.default(embedder=...)` one-liner facade
  - `DocumentChunker` with Onyx-style title prefix + metadata suffix +
    sentence boundaries + overlap
  - `Embedder` protocol with `HashingEmbedder` (stdlib-only deterministic)
    and `CallableEmbedder` (wrap any function)
  - `VectorStore` protocol + `InMemoryVectorStore` (pure-Python cosine)
  - `KeywordStore` protocol + `InMemoryBM25Store` (pure-Python BM25)
  - `HybridSearchPipeline` — vector + keyword in parallel, Reciprocal Rank
    Fusion, recency bias, reranker, context expansion (chunks above/below)
  - `LLMReranker` — zero-setup LLM-as-judge reranker
  - `TextExtractor` for TXT/MD/HTML (stdlib) plus lazy PDF/DOCX
  - `RAG.begin_run()` / `end_run()` per-run source tracker with thread-local
    isolation

- **`rag=` parameter on every agent type** — auto-wires three tools
  (`rag_search`, `rag_fetch_chunk`, `rag_list_sources`), augments the system
  prompt with citation instructions, and attaches `RAGSource[]` to
  `AgentResult.rag_sources` with stable `[1]`, `[2]`, … indices.

- **Adapters** — `DrkCacheVectorStore` (pgvector over psycopg2, read existing
  indexes), plus lazy Chroma / Qdrant / pgvector adapters.

### DeepAgent (new)

- **`shipit_agent.deep.DeepAgent`** — power-user factory for long, multi-step
  tasks. Bundles seven deep tools out of the box: `plan_task`,
  `decompose_problem`, `workspace_files`, `sub_agent`, `synthesize_evidence`,
  `decision_matrix`, `verify_output`.

- **One-flag power features**:
  - `verify=True` — runs `verify_output` against success criteria after every
    answer, verdict attached to `result.metadata["verification"]`
  - `reflect=True` — wraps in `ReflectiveAgent` for generate → critique →
    revise loop
  - `goal=Goal(...)` — switches to `GoalAgent` mode for decomposition +
    self-evaluation
  - `rag=RAG(...)` — grounded answers with auto-cited sources
  - `memory=AgentMemory(...)` — seeds inner `Agent.history` from conversation
    summary

- **`agents=` sub-agent delegation** — plug any mix of `Agent`, `DeepAgent`,
  `GoalAgent`, `ReflectiveAgent`, `AdaptiveAgent`, `Supervisor`,
  `PersistentAgent` as named delegates. The deep agent gains a
  `delegate_to_agent` tool it can call to hand off well-scoped sub-tasks
  while still using its own toolset to plan, take notes, and verify.

- **`create_deep_agent()` functional helper** — drop-in factory with
  auto-wrapping of plain Python callables as `FunctionTool` instances.

- **Nested event streaming** — when the parent calls `delegate_to_agent`, the
  tool captures the inner agent's `stream()` events into
  `tool_completed.metadata['events']` so UIs render sub-agent activity live.

- **Clean subpackage layout** — `shipit_agent/deep/deep_agent/{prompt,
  toolset, verification, delegation, factory}.py`.

### Live chat REPL (new)

- **`shipit chat`** — modern interactive terminal REPL that talks to every
  agent type. Switch live with `/agent <type>`, index files mid-session with
  `/index <path>`, set goals with `/goal`, toggle `reflect`/`verify`, save
  and reload conversations, inspect tools and sources.

- **Rich slash commands**: `/help`, `/agent`, `/agents`, `/tools`, `/sources`,
  `/index`, `/rag`, `/goal`, `/reflect`, `/verify`, `/history`, `/clear`,
  `/save`, `/load`, `/reset`, `/quiet`, `/info`, `/exit`.

- **Pluggable LLM provider** via `--provider` (or `$SHIPIT_LLM_PROVIDER`),
  persistent sessions with `--session-dir`, pre-index files with
  `--rag-file`.

### Streaming across every agent type

- **`PersistentAgent.stream()`** added — yields events per step with
  checkpointing between.
- **`DeepAgent.stream()`** covers every execution mode: direct, verified
  (emits extra `run_completed` with verification verdict), reflective,
  goal-driven, and sub-agent delegation (nested events in tool metadata).
- **`rag_sources` event type** added to the runtime, emitted after every
  RAG-backed run with the consolidated citation list.
- **`create_deep_agent()` returns a streamable object** — `.stream()` works
  identically to `.run()`.

### Memory cookbook

- **Dedicated `docs/agent/memory.md` page** — explains the two complementary
  memory systems (`memory_store=` for the LLM's `memory` tool,
  `AgentMemory` for application-curated profiles), the OpenAI-style
  "remember things across sessions" pattern, and how to persist
  `SemanticMemory` across processes.

- **`DeepAgent` memory auto-hydration** — `memory=AgentMemory(...)` seeds the
  inner `Agent.history` from `memory.get_conversation_messages()`
  automatically.

- **`notebooks/26_agent_memory.ipynb`** — runnable end-to-end tour of every
  memory pattern.

### Docs

- **New Agent section** with 6 pages: Overview, Examples, Streaming, With
  RAG, With Tools, Memory, Sessions.
- **New Super RAG section** with 6 pages: Overview, Standalone, Files &
  Chunks, With Agent, With Deep Agents, Adapters, API.
- **New DeepAgent page** — full factory reference.
- **Modernised Architecture + Model Adapters** reference pages.
- **Parameters reference** — every constructor parameter for every agent
  type and key class, with types, defaults, and "use it when" notes.
- **Updated quickstart** — six sections covering Agent, deep agent, and
  Agent + RAG.
- **Updated FAQ** — new "Agent types — which one should I use?" section.
- **5 new notebooks** (22–26): RAG basics, RAG + Agent, RAG + Deep Agents,
  Deep Agent chat, Agent memory.
- **Full-width docs layout + collapsible TOC** with floating toggle,
  persistence via localStorage.

### Build + extras

- **`shipit-chat` script entry point** added in `pyproject.toml`.
- **`[project.optional-dependencies]`** expanded with granular extras: `rag`,
  `rag-openai`, `rag-cohere`, `rag-sentence-transformers`, `rag-chroma`,
  `rag-qdrant`, `rag-pgvector`, `rag-drk-cache`, `rag-pdf`, `rag-docx`,
  `rag-rerank-cohere`, `rag-rerank-cross-encoder`, plus `bedrock`, `google`,
  `groq`, `together`, `ollama`. The `all` extra bundles everything.

### Fixed

- **Tool schema format bug** — `RAGSearchTool`, `RAGFetchChunkTool`,
  `RAGListSourcesTool`, and `WebhookPayloadTool` were returning flat
  `{"name": ..., "description": ..., "parameters": ...}` dicts instead of
  the LiteLLM/OpenAI `{"type": "function", "function": {...}}` wrapper,
  causing Bedrock's Converse API to reject them with
  `validation errors detected: Value '' at 'toolConfig.tools.N.toolSpec.name'`.
  All four tool schemas are now properly wrapped. Regression test in
  `tests/test_tool_schemas_bedrock_compat.py` scans every built-in tool for
  the wrapped shape + non-empty `name`/`description` + Bedrock's regex
  constraint `[a-zA-Z0-9_-]+`.

- **`memory=AgentMemory` coercion bug** — `DeepAgent._resolve_memory` and
  `GoalAgent._build_agent` were auto-assigning `AgentMemory.knowledge` (a
  `SemanticMemory`) into `memory_store=` (which expects a `MemoryStore` with
  a different interface). The runtime later tried to call
  `memory_store.add(MemoryFact(...))` and crashed on the type mismatch. Fix:
  `memory=` now only seeds `history`; users pass `memory_store=` separately
  if they want the runtime's `memory` tool wired up.

- **`Agent.with_builtins(tools=[...])` keyword collision** — passing
  `tools=` alongside `with_builtins` raised
  `TypeError: got multiple values for keyword argument 'tools'` because the
  method built its own tool list and forwarded both. Fix:
  `with_builtins(tools=...)` now merges user tools with the builtin catalogue
  (last-write-wins on name collision).

- **`AgentDelegationTool` events in streaming** — the tool now uses the
  inner agent's `stream()` (when available) and packs events into
  `tool_completed.metadata['events']` so parent streams surface sub-agent
  activity.

### Test coverage

- **521 unit tests** (up from 285) — fully green.
- **19 end-to-end Bedrock smoke tests** in
  `scripts/smoke_bedrock_e2e.py` cover every public surface: plain Agent,
  custom `FunctionTool`, Agent + RAG with citation capture, `Agent.stream()`,
  `Agent.chat_session()`, DeepAgent with seven deep tools, DeepAgent + RAG,
  `DeepAgent.stream()`, `verify=True`, `goal=Goal(...)`,
  `DeepAgent.chat()`, `agents=[...]` sub-agent delegation, `GoalAgent`,
  `ReflectiveAgent`, `AdaptiveAgent`, `Supervisor`, `PersistentAgent`, the
  memory system, and the full-stack composition (`DeepAgent(rag, memory,
  agents, verify)`). All 19 pass against real Bedrock with
  `bedrock/openai.gpt-oss-120b-1:0`.

### Changed

- **`DeepAgent.run()` auto-routes** to `GoalAgent` when `goal=` is set, to
  `ReflectiveAgent` when `reflect=True`, and runs the inner `Agent`
  otherwise. Verification mode is additive on top of all three.

---

## [1.0.2] — 2026-04-10

Major feature release. Adds deep agents, structured output, pipelines, agent
teams, advanced memory, output parsers, and nine runtime power features.
**285 tests. 12 runnable examples. 8 notebooks. 13 new doc pages.**

### Deep Agents — Beyond LangChain

- **`GoalAgent`** — Autonomous goal decomposition with success criteria
  tracking, self-evaluation, and streaming. Supports `.with_builtins()` for
  full tool access and `.stream()` for real-time events with output content.

- **`ReflectiveAgent`** — Self-evaluation and revision loop. Produces output,
  reflects critically (with quality score 0-1), and revises until threshold
  met. Streaming shows each reflection's quality and feedback.

- **`Supervisor` / `Worker`** — Hierarchical agent management. Supervisor
  plans, delegates to workers, reviews quality, sends work back for revision.
  `Supervisor.with_builtins()` creates workers with all tools automatically.

- **`AdaptiveAgent`** — Creates new tools at runtime from Python code.
  Auto-dedents code strings so notebook indentation works. Created tools are
  immediately available for agent runs.

- **`PersistentAgent`** — Checkpoint and resume across sessions. Saves
  progress periodically so long-running tasks survive interruptions.

- **`Channel` / `AgentMessage`** — Typed agent-to-agent communication with
  FIFO queues, acknowledgment, and history tracking.

- **`AgentBenchmark` / `TestCase`** — Systematic agent testing framework.
  Define expected output content, tool usage, and negative checks. Generates
  pass/fail reports with detailed failure reasons.

- **Memory for deep agents** — All deep agents accept `memory` parameter
  for conversation history across runs.

### Structured Output & Parsers

- **`output_schema` on `Agent.run()`** — Pass a Pydantic model or JSON schema
  dict. Returns typed, validated `result.parsed` instance. Schema instructions
  appended to user prompt (not system prompt) for Bedrock compatibility.

- **`JSONParser`** — Handles code fences, surrounding prose, schema validation.

- **`PydanticParser`** — Parse LLM output into Pydantic model instances.

- **`RegexParser`** — Extract structured data with named regex groups.

- **`MarkdownParser`** — Extract code blocks, headings, and lists.

### Composition

- **`Pipeline`** — Deterministic composition with `Pipeline.sequential()`,
  `parallel()`, conditional routing, function steps, and `{key}` template
  references. Supports `.stream()` for real-time step events.

- **`AgentTeam`** — Dynamic LLM-routed multi-agent coordination with
  `TeamAgent.with_builtins()`. Coordinator decides who works. Supports
  `.stream()` with full output content and worker tagging.

### Runtime Power Features

- **Parallel tool execution** — `parallel_tool_execution=True` runs concurrent
  tool calls via `ThreadPoolExecutor`.

- **Graceful tool failure** — Tool exceptions produce error messages instead
  of crashing. LLM can recover and try different approaches.

- **Context window management** — Token usage tracking across iterations.
  `context_window_tokens` enables automatic message compaction.

- **Hooks / middleware** — `AgentHooks` with `@on_before_llm`, `@on_after_llm`,
  `@on_before_tool`, `@on_after_tool` callbacks.

- **Mid-run re-planning** — `replan_interval=N` re-runs planner every N
  iterations.

- **Async runtime** — `AsyncAgentRuntime` with `async run()` and
  `async stream()` for FastAPI/Starlette.

- **Transient error auto-retry** — LLM adapters catch 429/500/502/503
  errors and re-raise as `ConnectionError` for automatic retry.

- **Advanced memory** — `ConversationMemory` (buffer/window/summary/token),
  `SemanticMemory` (embedding-based vector search), `EntityMemory` (track
  people/projects/concepts), `AgentMemory` (unified interface).

### Changed

- **Selective memory storage** (**breaking**) — Only tool results with
  `metadata={"persist": True}` are stored in memory.

- **Safer retry defaults** — `RetryPolicy.retry_on_exceptions` defaults to
  `(ConnectionError, TimeoutError, OSError)` instead of `(Exception,)`.

---

## [1.0.1] — 2026-04-09

Maintenance release. Bug fix in the tool runner plus repo hygiene,
contributor experience, and CI hardening. **Strongly recommended upgrade**
from 1.0.0 if you use Bedrock `gpt-oss-120b` or any model that occasionally
hallucinates `context` as a tool-call argument.

### Fixed

- **`ToolRunner.run_tool_call` argument collision** — Some LLMs (notably
  `bedrock/openai.gpt-oss-120b-1:0`) occasionally emit a `context` key in
  tool-call arguments, which would collide with the positional `context`
  parameter the runner passes to `tool.run()` and raise
  `TypeError: got multiple values for argument 'context'`. The runner now
  strips a reserved set of argument names (`context`, `self`) from tool-call
  arguments before forwarding them. Affects every built-in tool. Regression
  test added in `tests/test_construction_and_runner.py`.

### Added

- **`CHANGELOG.md`** at repo root in [Keep a Changelog](https://keepachangelog.com/) format. Mirrors `docs/changelog.md` but lives where GitHub Releases expects it.
- **`CONTRIBUTING.md`** at repo root with complete development setup, commit conventions, PR checklist, and step-by-step instructions for adding new LLM adapters and built-in tools.
- **GitHub issue templates** (`.github/ISSUE_TEMPLATE/`):
    - `bug_report.yml` — structured bug form with version, OS, provider, repro, traceback fields
    - `feature_request.yml` — structured feature proposal form with problem-first framing
    - `config.yml` — disables blank issues, adds contact links to docs, discussions, and security advisories
- **GitHub pull request template** (`.github/PULL_REQUEST_TEMPLATE.md`) with 12-item verification checklist.
- **Test CI workflow** (`.github/workflows/test.yml`) — runs `pytest -q` on Python 3.11 + 3.12 × Ubuntu + macOS (4 matrix cells). Smoke-tests all 11 LLM adapter imports including `LiteLLMProxyChatLLM` and `VertexAIChatLLM`. Cancels older runs on the same branch via concurrency group.
- **Gitleaks CI workflow** (`.github/workflows/gitleaks.yml`) — secret scanning on every push and PR via the licensed `gitleaks-action@v2`. Full git history scanned (`fetch-depth: 0`). Uploads SARIF findings to the GitHub Security tab, posts inline comments on PRs, and shows findings in the Actions summary panel.
- **Pre-commit config** (`.pre-commit-config.yaml`) — local hooks for trailing whitespace, EOF fixer, YAML/TOML validation, merge-conflict detection, private-key detection, `gitleaks v8.21.2`, and `ruff` lint + format. Install with `pre-commit install` after cloning.
- **Gitleaks allowlist** (`.gitleaks.toml`) — 14 path patterns and 12 regex patterns. Allowlists:
    - `.env.example`, docs, notebooks, tests (placeholder credentials)
    - `.shipit_notebooks/`, `.shipit_workspace/`, `sessions/`, `traces/`, `memory.json` (runtime tool outputs that contain scraped HTML like Pushly domainKeys)
    - Common scraped client-side ID patterns: `pushly(...)`, `UA-xxx`, `G-xxx`, `GTM-xxx`

### Changed

- **`.gitignore`** — rewritten to deduplicate entries and add `site/` (MkDocs build output), `.eggs/`, `pip-wheel-metadata/`. All runtime directories (`.shipit_workspace/`, `.shipit_notebooks/`, `.shipit_notebook_workspace/`) now properly ignored.
- Runtime tool outputs (`sessions/`, `traces/`, `memory.json`, `.shipit_notebooks/**`) untracked from git via `git rm --cached`. They were committed in 1.0.0 because `.gitignore` didn't cover them — gitleaks flagged scraped HTML content as false-positive "leaks" which is how the gap was discovered.

### Security

- **Added secret scanning to CI.** Every push and PR is scanned for leaked API keys, tokens, `.env` contents, and private keys before merge. False positives are managed via `.gitleaks.toml` allowlist.
- **Pre-commit secret scanning.** Contributors who install `pre-commit` hooks get gitleaks scanning on every local `git commit` — catches leaks before they reach GitHub.

### Docs

- **Contributing guide** with sections for "how to add a new LLM adapter" and "how to add a new built-in tool" — documents the patterns used for `VertexAIChatLLM` and `LiteLLMProxyChatLLM` in 1.0.0.
- **Release process** documented for maintainers (version bump → CHANGELOG move → commit → tag → push → CI publishes).

### Internal

- No runtime code changed. `shipit_agent/` module is byte-identical to 1.0.0.
- All 91 tests pass unchanged.
- PyPI package contents identical to 1.0.0 except for bumped version metadata and updated README.

---

## [1.0.0] — 2026-04-09

First stable release. Focused on making the agent loop **observable, interchangeable, and out of the way**.

### 🧠 Live reasoning / thinking events

- `LLMResponse.reasoning_content` field added to carry thinking/reasoning blocks from any provider
- New `_extract_reasoning()` helper handles three provider shapes:
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
- **Nine providers** supported: `openai`, `anthropic`, `bedrock`, `gemini`, `vertex`, `groq`, `together`, `ollama`, and a generic `litellm` / `litellm_proxy` / `proxy` mode
- Per-provider credential validation with clear error messages
- `SHIPIT_OPENAI_TOOL_CHOICE=required` env var to force tool use on lazy models like `gpt-4o-mini`

### 🆕 Vertex AI support

- `VertexAIChatLLM` rewritten with proper Vertex AI credential handling:
    - `service_account_file="/path/to/sa.json"` — sets `GOOGLE_APPLICATION_CREDENTIALS` so `google-auth` picks it up
    - `project_id="my-gcp-project"` — injected as `vertex_project` completion kwarg
    - `location="us-central1"` — injected as `vertex_location` completion kwarg
- `build_llm_from_env('vertex')` reads `SHIPIT_VERTEX_CREDENTIALS_FILE` or `GOOGLE_APPLICATION_CREDENTIALS`, `VERTEXAI_PROJECT` or `GOOGLE_CLOUD_PROJECT`, and `VERTEXAI_LOCATION` or `VERTEX_LOCATION` or `GOOGLE_CLOUD_LOCATION`
- Clear error messages point at the exact env var you need to set

### 🆕 LiteLLM proxy server support

- New `LiteLLMProxyChatLLM` adapter for self-hosted LiteLLM proxy servers
- Accepts `api_base`, `api_key`, and `custom_llm_provider` (defaults to `"openai"` since the proxy always exposes an OpenAI-compatible HTTP API regardless of the upstream provider)
- `build_llm_from_env('litellm')` (or `'proxy'` or `'litellm_proxy'`) auto-detects proxy mode when `SHIPIT_LITELLM_API_BASE` is set, otherwise falls back to direct LiteLLM SDK mode
- Enables centralized proxy patterns: multi-team gateway, rate limiting, credential isolation, cost tracking

### 🌐 In-process Playwright for `open_url`

- `OpenURLTool` now uses Playwright's sync Chromium directly (headless, realistic desktop Chrome UA, 1280×800 viewport)
- Handles JS-rendered pages, anti-bot 503s, modern TLS/ALPN
- Stdlib `urllib` fallback when Playwright is not installed — **zero third-party HTTP dependencies** in the core fallback path
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

### Docs & packaging

- **Full MkDocs Material documentation site** at [shipiit.github.io/shipit_agent](https://shipiit.github.io/shipit_agent/)
- 16-page docs covering Getting Started, Guides, and Reference
- `.github/workflows/docs.yml` — auto-deploys docs on every push to `main`
- `.github/workflows/release.yml` — auto-publishes to PyPI on tag push
- `pyproject.toml`: `[project.urls]` points to correct GitHub org, adds `Documentation` and `Changelog` links
- `.env.example`: expanded with all new env vars documented
- `notebooks/04_agent_streaming_packets.ipynb`: full rewrite with .env loading, credential visibility printer, and live Markdown updates
- `README.md`: new v1.0 release section with 8 headline features, PyPI badges, docs site links

### Breaking changes

None — first stable release. Subsequent 1.x releases will maintain backward compatibility within the 1.x line.

---

[Unreleased]: https://github.com/shipiit/shipit_agent/compare/v1.0.1...HEAD
[1.0.1]: https://github.com/shipiit/shipit_agent/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/shipiit/shipit_agent/releases/tag/v1.0.0
