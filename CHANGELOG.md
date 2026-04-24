# Changelog

All notable changes to **shipit-agent** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.6] — 2026-04-24

**Bulletproof 24-hour Autopilot, dashboard renderer tool, and LiteLLM-proxy
plug-in.** The long-running runtime is now hardened for multi-day jobs:
cumulative budgets across resume, SIGTERM-safe shutdown, dollar tracking
wired end-to-end, corrupt-checkpoint quarantine. New `render_dashboard` tool
turns a JSON spec into a Claude-Desktop-style HTML one-pager (metrics, chart,
timeline, cards, verdict). Full LiteLLM proxy support so companies can point
every agent at their own proxy URL + key in three fields.

### Added

- **`Autopilot` — bulletproof for 24-hour runs:**
  - `CheckpointStore.save()` now writes the full `BudgetUsage` (seconds,
    tool calls, tokens, dollars, iterations) and schema version. A crash
    at hour 12 → resume for another 12 trips a 24-hour cap exactly at
    hour 24.
  - `CheckpointStore.load()` quarantines corrupt JSON as
    `<run_id>.corrupted.<timestamp>.json` instead of silently dropping it.
  - `CheckpointStore.usage_from_payload()` helper handles both v1 and v2
    checkpoint schemas transparently.
  - Dollar accounting: `usage.dollars` accumulates from LLM response
    metadata using `shipit_agent.costs.pricing`, with Bedrock / LiteLLM
    prefix handling and a coarse fallback estimate for unpriced models.
  - `Autopilot(..., install_signal_handlers=True)` (default) installs
    `SIGTERM` / `SIGHUP` handlers so `systemd stop` / `launchd stop`
    halt cleanly with one final checkpoint. Opt out with
    `install_signal_handlers=False` (tests / worker threads).
  - `Autopilot.request_stop(reason)` — thread-safe external halt for
    daemons and UIs; the loop exits at the next iteration boundary.
  - First-iteration heartbeat so a slow first step never looks like a
    hang.
  - `BudgetPolicy.remaining(usage)` and `would_exceed_after(...)` for
    pre-iteration projection and UI ETA bars.
  - `autopilot.iteration` / `autopilot.heartbeat` events now carry a
    `remaining` per-axis dict.
- **`shipit_agent.tools.dashboard_render` package:**
  - `DashboardRenderTool` — renders metric tiles, line / bar charts,
    ranked bars, event timelines, trait cards, lifestyle grids, phase
    stacks, callouts, and verdict boxes from a structured spec.
  - Produces a standalone HTML document (inline CSS; Chart.js via CDN
    only when a chart section is present). All user strings are
    HTML-escaped; colors pass through a hex allow-list to prevent
    CSS injection.
  - Returns `{'artifact': True, 'kind': 'file', 'name', 'content'}`
    metadata so `ArtifactCollector.ingest_tool_metadata` surfaces the
    rendered dashboard as an Autopilot artifact with zero glue code.
  - `render_dashboard(spec)` helper for direct (no-LLM) rendering.
  - Path-traversal on `export` is neutralised — the file is always
    written inside the workspace root.
- **LiteLLM proxy — bring your own URL + key:**
  - `BedrockChatLLM` now only injects `modify_params=True` for Anthropic
    models; Nova, Titan, Llama, and Mistral on Bedrock work without the
    previous "extraneous key [modify_params]" error.
  - `AgentRegistry.all()` — convenience alias for `list_all()` so the
    `.all()` idiom works.
- **Notebook 46 — `46_dashboard_render_tool_and_litellm.ipynb`:**
  - Covers LLM-provider choice (Bedrock / LiteLLM direct / **self-hosted
    LiteLLM proxy with URL + key**), the direct renderer, an agent with
    the tool, and the Autopilot artifact ingest path.
  - Regenerator script `notebooks/_nb46_builder.py`.
- **Python 3.13 and 3.14 support:**
  - Added `Programming Language :: Python :: 3.13` and `:: 3.14`
    classifiers to `pyproject.toml`; `requires-python = ">=3.11"` already
    covered them, but the classifiers make the support discoverable on
    PyPI.
  - CI matrix expanded to `['3.11', '3.12', '3.13', '3.14']` on
    `ubuntu-latest` and `macos-latest`.
  - Replaced the two remaining `datetime.utcnow()` call sites
    (`costs.tracker.CostRecord`, `notifications.base.Notification`) with
    `datetime.now(timezone.utc)`. `utcnow()` emits a DeprecationWarning
    in 3.12+ and will be removed — the swap is forward-compatible and
    behaviourally identical.

### Changed

- Notebooks 44 and 45 now call `AgentRegistry.default()` (bundled agents)
  and `AgentDefinition.max_iterations` (snake_case field). Previous
  snapshots called `AgentRegistry()` (empty) and `.maxIterations`
  (nonexistent attribute).
- `Autopilot.stream()` path updated alongside `run()` for the same
  cumulative-usage / SIGTERM / dollar-tracking / `remaining` payload.

### Tests

- `tests/test_autopilot_hardening.py` — 14 tests covering full-usage
  persistence, v1 checkpoint back-compat, corruption quarantine, dollar
  tracking (explicit / pricing / disabled), SIGTERM stop, first-iter
  heartbeat, `remaining` payload, and pre-iteration budget projection.
- `tests/test_autopilot_long_task.py` — 6 compressed-time simulations
  (many iterations, 5-crash resume chain, SIGTERM mid-run, mid-run
  corruption recovery, 50-child fan-out) + 1 opt-in Bedrock soak
  gated on `SHIPIT_AUTOPILOT_SOAK=<seconds>`.
- `tests/test_autopilot_bedrock_e2e.py` — 7 end-to-end tests against a
  real Bedrock LLM (`SHIPIT_BEDROCK_E2E=1`), covering run / stream /
  resume cumulative / artifacts / critic / fan-out.
- `tests/test_dashboard_render.py` — 20 tests covering every section
  type, HTML escaping, color allow-list, chart config, export +
  traversal guard, `ArtifactCollector` ingest, and a realistic
  full-spec life-vision dashboard.
- `tests/test_notebook_assets.py` — locks the current notebook-44/45
  API usage so the fixes can't regress.

### Fixed

- A resumed Autopilot previously reset wall-clock, tokens, tool-calls
  and dollars to zero — only iteration count survived the checkpoint.
  A 12-hour crash plus a 12-hour resume would run 24 hours under a
  "24-hour" cap even though the cap should have fired. Now the full
  usage round-trips through the checkpoint.
- `usage.dollars` was never incremented, so `max_dollars` budgets
  could only trip when a caller set them to zero. Dollars now flow
  from provider `usage` metadata through the pricing table.
- `BedrockChatLLM` could not drive non-Anthropic Bedrock models because
  the adapter always injected `modify_params=True`, which Nova / Llama
  / Mistral reject.

## [1.0.5] — 2026-04-18

**Prebuilt agents, multi-agent crews, notifications, and cost tracking.**

### Added

- `shipit_agent.agents` with 40 built-in agent personas across 8 categories.
- `shipit_agent.deep.ship_crew` with DAG-based `ShipCrew`, `ShipAgent`, `ShipTask`, and `ShipCrewResult`.
- `shipit_agent.notifications` with `SlackNotifier`, `DiscordNotifier`, `TelegramNotifier`, and `NotificationManager`.
- `shipit_agent.costs` with `CostTracker`, `Budget`, `BudgetExceededError`, and model pricing tables.
- Four new notebooks:
  - `notebooks/32_prebuilt_agents.ipynb`
  - `notebooks/33_ship_crew_orchestration.ipynb`
  - `notebooks/34_notifications.ipynb`
  - `notebooks/35_cost_tracking_and_budgets.ipynb`

### Changed

- Expanded regression coverage for the new APIs in:
  - `tests/test_prebuilt_agents.py` (39 tests)
  - `tests/test_ship_crew.py` (44 tests)
  - `tests/test_notifications_and_costs.py` (76 tests)

### Fixed

- `NotificationManager.as_hooks()` now emits `run_completed` only for final LLM responses and resets state correctly between runs.
- `ShipTask.to_dict()` now preserves `output_schema`.
- `ShipAgent.from_registry()` now raises `KeyError` for unknown registry ids as documented.

## [1.0.4] — 2026-04-12

**Skills, tools, and runtime power-up.** All 32 tool prompts rewritten with
decision trees and anti-patterns. Full skill-to-tool linking for all 37
packaged skills. Automatic iteration boost for skill-driven workflows.
Expanded bash allowlist (50+ commands). Streaming, chat, and project-building
examples across 3 notebooks. Comprehensive docstrings across every key module.
**32 skill tests. All passing.**

### Skills — Full Tool Linking

- **37 skill tool bundles** (up from 10) — every packaged skill now declares
  the built-in tools it needs. When a skill is selected, the agent auto-
  attaches the right tools without the caller having to wire them manually.
- **Shared tool groups** — `_FILE_CORE`, `_CODE_CORE`, `_WEB_CORE` reduce
  duplication across bundles and make it easy to add new skills.
- **`validate_tool_bundles()`** — new helper that checks every tool name in
  `SKILL_TOOL_BUNDLES` against the real builtin map. Catches typos and stale
  refs at test time.
- **Category-organised bundles** — web/scraping, code/development, devops,
  security, writing, research, lead gen, marketing, productivity, media,
  multi-agent.

### Agent — Iteration Boost & Efficiency

- **`_effective_max_iterations()`** — when skills inject extra tools and
  `max_iterations` is at the default (4), the runtime auto-boosts to 8 so
  skill-driven workflows can complete without cutting off early. An explicit
  override is always respected.
- **Single skill computation** — `run()` and `stream()` now compute
  `_selected_skills()` once and pass the result to `_effective_tools()`,
  `_skill_tool_names()`, and `_effective_max_iterations()`. Previously skills
  were recomputed up to 3 times per call.
- **`_effective_tools(selected_skills=)`** — accepts pre-computed skills to
  avoid redundant registry lookups.

### Tool Prompts — All 32 Upgraded

Every tool's `prompt.py` rewritten with:

- **Decision trees** — "Need to search? → `grep_files`. Need to find a file? → `glob_files`."
- **Anti-patterns** — "Don't use `cat` when `read_file` is available."
- **Workflow guidance** — "glob → read → edit → verify"
- **Cross-tool coordination** — each tool references the others it pairs with.

Upgraded tools: `read_file`, `write_file`, `edit_file`, `grep_files`,
`glob_files`, `bash`, `run_code`, `web_search`, `open_url`,
`playwright_browse`, `memory`, `plan_task`, `verify_output`, `sub_agent`,
`tool_search`, `decompose_problem`, `synthesize_evidence`, `decision_matrix`,
`build_prompt`, `gmail_search`, `google_calendar`, `google_drive`, `slack`,
`linear`, `jira`, `notion`, `confluence`, `custom_api`, `ask_user`,
`human_review`, `workspace_files`, `build_artifact`.

### Documentation

- **Comprehensive docstrings** added to all key modules:
  `agent.py` (module + class + every method), `builtins.py` (tool catalogue
  by category), `skills/loader.py` (execution flow diagram),
  `skills/registry.py` (search scoring weights), `skills/tool_bundles.py`
  (mapping guide), `deep/deep_agent/factory.py` (skill forwarding).
- **6 tool doc pages updated** in both `docs/` and `docs-app/` with enhanced
  prompts: bash, read-file, edit-file, write-file, glob-files, grep-files.
- **Skills guide updated** — new sections on iteration boost and tool bundle
  validation.
- **Notebook 27 rewritten** — 38 cells covering: catalog browse, search, tool
  bundles, validation, Agent streaming, DeepAgent streaming with verify,
  multi-turn chat, chat streaming, full project build, web scraping,
  DeepAgent chat streaming, runtime skill management, coverage check.
- **Notebook 29** (new) — DeepAgent with skills + memory + verification +
  reflection + multi-turn chat + sub-agent delegation + streaming.
- **Notebook 30** (new) — real-world full project build: scaffold FastAPI app,
  add DevOps config, security audit, web research, iterative chat build.
- **Skills guide** expanded with 7 real-world examples (full project build,
  web scraping, portfolio website, security audit, DevOps pipeline, DeepAgent
  streaming, multi-turn iterative building) plus streaming and chat sections
  with event type reference table.

### Bash Allowlist Expansion

- **50+ safe commands** added to `BashTool.allowed_command_prefixes`:
  `mkdir`, `touch`, `cp`, `mv`, `chmod`, `echo`, `grep`, `curl`, `docker`,
  `docker-compose`, `kubectl`, `terraform`, `aws`, `go`, `cargo`, `npx`,
  `tsc`, `eslint`, `black`, `isort`, `tree`, `du`, `awk`, `cut`, `tr`,
  `diff`, `xargs`, `tee`, `printf`, and more.
- Organised into categories: filesystem, text processing, git, Python,
  Node/JS, build/run, containers, network, other languages.

### Tests

- **15 new tests** (17 → 32 total in `test_skills_runtime.py`):
  - `test_agent_boosts_max_iterations_when_skills_are_active`
  - `test_agent_respects_explicit_max_iterations_override`
  - `test_agent_no_boost_without_skills`
  - `test_tool_bundle_names_all_exist_in_builtins`
  - `test_effective_tools_accepts_precomputed_skills`
  - `test_all_packaged_skills_have_tool_bundles`
  - `test_deep_agent_boosts_iterations_via_inner_agent`
  - `test_agent_chat_session_retains_skills`
  - `test_agent_chat_session_multi_turn_history`
  - `test_agent_stream_with_skills_yields_events`
  - `test_agent_stream_metadata_includes_skills`
  - `test_deep_agent_chat_retains_skills`
  - `test_deep_agent_stream_with_skills`
  - `test_chat_stream_yields_events`
  - `test_agent_with_memory_store_and_skills`

---

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

- Planner output is now injected as a `user`-role context message rather than an orphan `role="tool"` message — fixes Bedrock's _"number of toolResult blocks exceeds number of toolUse blocks"_ error
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

- **Full MkDocs Material documentation site** at [docs.shipiit.com](https://docs.shipiit.com/)
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
