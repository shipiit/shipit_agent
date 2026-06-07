# Changelog

## v1.0.10 — 2026-06-07

**Bug-fix & hardening release.** Fixes a v1.0.9 regression that broke custom LLM adapters, hardens local-execution and connector tools against sandbox-escape / SSRF, and tightens session, cost, and concurrency correctness. No public API removed; no caller needs changes. **1742 tests passing (+180 new). 0 regressions.**

### Fixed — critical

- **`text_delta_callback` regression (v1.0.9)** — the runtime passed the new streaming callback to `LLM.complete()` unconditionally, raising `TypeError` for any adapter on the prior signature. It now detects support via signature inspection and only passes it to adapters that accept it (backward compatible; streaming preserved for opted-in adapters).
- **Multi-turn sessions** no longer stack a duplicate system prompt every turn — the runtime injects exactly one leading system message and strips persisted ones on reload (fixes unbounded growth in the `AgentChatSession` path).

### Fixed — security hardening

- **Bash tool** rejects command substitution (`$(…)`, backticks), process substitution, and file redirection that could bypass the allowlist.
- **`open_url`** is http(s)-only and blocks `file://` plus private / loopback / link-local / cloud-metadata IPs (SSRF); opt out with `allow_private_hosts=True`.
- **SQL tool** read-only guard scans the whole statement and rejects stacked statements (closes an `allow_writes=False` bypass).
- **OAuth** `exchange_code(state=…)` validates and consumes the CSRF state nonce.
- **`edit_file`** refuses non-UTF-8 files instead of corrupting them; **`FileCredentialStore`** warns about plaintext, chmods `0600`, and writes atomically.

### Fixed — reliability & correctness

- MCP transports are closed on error (`try/finally`) and on a failed discovery handshake — no leaked subprocesses.
- Parallel tools run on isolated state and merge deterministically (race fixed).
- The iteration-cap summary turn is now counted in usage/cost; `CostTracker` flags unknown-model pricing instead of silently billing `$0` under a budget.
- `JSONParser` balanced-brace extraction; pipeline `stream()` no longer double-runs steps; autopilot fan-out preserves input order; deep-agent factory forwards `memory`/`history`/`verifier`; vector-store ids are monotonic; file stores write atomically; grep gains a timeout; ShipCrew timeout actually pre-empts.

### Added

- 180+ new tests and six runnable examples (`examples/13`–`18`).

## v1.0.7 — 2026-04-24

**Agents for every role.** 12 new tools and 9 new persona specialists turn shipit-agent into a framework that ships agents for developers, designers, sales reps, PMs, data analysts, finance, customer support, and recruiters — not just code-slinging agents.

### Core Tools — Everyone Benefits

- **`GitHubTool`** — 16 actions covering issues, pull requests, reviews (APPROVE / REQUEST_CHANGES / COMMENT), file contents, and GitHub Actions workflow runs. github.com + GitHub Enterprise. Rate-limit aware with structured `retry_after_epoch` payload.
- **`GitLabTool`** — 16 actions for issues, merge requests, file contents, and CI pipelines. Self-hosted + gitlab.com.
- **`SQLTool`** — SQLAlchemy-backed. Works with PostgreSQL, MySQL, SQLite, BigQuery, Snowflake, Redshift, MSSQL, Oracle. Read-safe by default; mutations gated by `allow_writes=True`. 46 tests.
- **`VisionTool`** — image → text via any vision-capable LLM (Claude, GPT-4o, Gemini, Bedrock Claude, LiteLLM). Accepts filesystem paths, URLs, data-URLs, or raw base64.
- **`PDFTool`** — extract text, per-page content, metadata from PDFs (local or URL). Page-range parsing, char caps, clean error taxonomy.
- **`LangSmithExporter` + `OpenTelemetryExporter`** — ship every agent's trace to LangSmith or any OTLP backend (Datadog, Grafana, Honeycomb).

### Persona SaaS Connectors

- **`FigmaTool`** — files, nodes, rendered images, comments, team projects, component libraries.
- **`SalesforceTool`** — SOQL/SOSL queries, accounts/opportunities/contacts, safe `log_activity` + gated full writes.
- **`StripeTool`** — customers, charges, subscriptions, invoices, products. Read-heavy by default. Test/live mode detection.
- **`GoogleSheetsTool`** — read/write cells, ranges, formulas, sheet structure. A1-notation with proper URL encoding.
- **`ZendeskTool`** — ticket search/create/update/close, `add_comment` always enabled for triage, macro preview.
- **`LinkedInSearchTool`** — **strictly read-only**. Profile + company lookup + search. Four layers of write-free enforcement.

### Nine New Specialist Personas

- **`code-reviewer-bot`**, **`release-engineer`** — GitHub-powered dev ops.
- **`figma-designer`** — design review + handoff via Figma + Vision.
- **`sales-rep`**, **`account-executive`**, **`sales-ops`** — Salesforce + LinkedIn + SQL.
- **`recruiter`** — sourcing + candidate tracking via LinkedIn + Sheets + PDF.
- **`finance-analyst`** — Stripe + PDF + SQL + dashboard rendering.
- **`customer-support-agent`** — Zendesk + Vision + Slack.

Total specialists in `agents.json` now 56.

### Seven Persona Walk-Through Notebooks

- `47_pm_pr_digest` — nightly PR digest across repos
- `48_designer_figma_review` — Figma → design-review dashboard
- `49_sales_lead_enrichment` — Salesforce + LinkedIn → personalised outreach
- `50_manager_sheets_kpis` — Google Sheets → weekly dashboard
- `51_support_zendesk_triage` — ticket triage with screenshot reading
- `52_analyst_sql_to_dashboard` — SQL → dashboard (real SQLite)
- `53_finance_stripe_pdf_cashflow` — Stripe + PDF contracts → cash-flow one-pager

Each runs clean with 0 cell errors using stubbed API responses — no credentials needed to see the flow.

### Tests

286 new tests across 12 new test files. **1190 passing, 8 skipped (gated Bedrock E2E + soak), 0 regressions.**

### Upgrade

```bash
pip install --upgrade shipit-agent==1.0.7
```

No breaking changes. Optional extras for new deps: `pip install 'shipit-agent[pdf,sql,otel]'`.

## v1.0.6 — 2026-04-24

**Bulletproof 24-hour Autopilot, AI-driven dashboard renderer, LiteLLM proxy.** `Autopilot` is hardened for multi-day runs: cumulative budgets across resume, SIGTERM-safe shutdown, end-to-end dollar tracking, corrupt-checkpoint quarantine. New `DashboardRenderTool` lets an agent pick the right section shape (metrics / chart / timeline / cards / phases / verdict) for any one-pager question and emit a self-contained HTML artifact. First-class LiteLLM-proxy support so any company can plug every agent into their own proxy in three fields.

### Autopilot — Bulletproof For 24-Hour Runs

- **Cumulative budgets across resume** — every field of `BudgetUsage` (seconds, tool calls, tokens, dollars, iterations) persists in the checkpoint. A run that crashes at hour 12 and resumes for another 12 trips a 24-hour cap exactly at hour 24, not hour 36.
- **Dollar tracking wired end-to-end** — `usage.dollars` accumulates from LLM response metadata via `shipit_agent.costs.pricing`, with Bedrock / LiteLLM prefix handling plus a coarse fallback for unpriced models. `max_dollars` budgets actually fire.
- **Signal-safe shutdown** — `SIGTERM` / `SIGHUP` are caught alongside `SIGINT`. `systemd stop` / `launchd stop` halt cleanly with one final checkpoint. `autopilot.request_stop(reason)` is a thread-safe external halt for daemons / UIs.
- **Corrupt-checkpoint quarantine** — a JSON parse error during `load()` renames the bad file to `<run_id>.corrupted.<timestamp>.json` instead of silently dropping state. Operators can forensic-inspect later.
- **First-iteration heartbeat + `remaining` payload on every event** — slow first steps never look like hangs; iteration / heartbeat events carry per-axis headroom so UIs can render ETA bars.
- **Pre-iteration budget projection** — `BudgetPolicy.would_exceed_after(...)` + `BudgetPolicy.remaining(usage)` helpers.
- **`CheckpointStore.usage_from_payload()`** — back-compat helper that loads both schema v1 (iterations only) and v2 (full `BudgetUsage`) transparently.

### Dashboard Render Tool — The Agent Picks The Shape

- **`shipit_agent.tools.dashboard_render` package** with `DashboardRenderTool` and a `render_dashboard(spec)` helper.
- The agent composes the dashboard from these section types: `metrics`, `line_chart`, `bar_chart`, `bars`, `timeline`, `cards`, `lifestyle_grid`, `phases`, `callout`, `verdict`.
- **Self-contained HTML output** — inline CSS; Chart.js via CDN only when a chart section is present. Renders in any browser or email client.
- **Security defaults** — all user strings HTML-escaped, colors filtered through a hex allow-list (no CSS injection), path-traversal on `export` neutralised.
- **Zero-glue artifact flow** — tool returns `{'artifact': True, 'kind': 'file', 'name': 'xxx.html', 'content': '...'}`, which `ArtifactCollector.ingest_tool_metadata` picks up. An `Autopilot(..., artifacts=True)` run that calls this tool auto-captures the rendered HTML.

### LiteLLM Proxy — Bring Your Own URL + Key

- **Three fields** (`model`, `api_base`, `api_key`) point every `Agent`, `Autopilot`, and `ShipCrew` at a self-hosted LiteLLM proxy.
- Three equivalent paths to wire it: factory (`build_llm_from_settings`), direct class (`LiteLLMProxyChatLLM`), or purely env vars (`SHIPIT_LITELLM_API_BASE` + `SHIPIT_LITELLM_API_KEY` + `SHIPIT_LITELLM_MODEL`).
- Factory auto-detects proxy mode when `api_base` is set; falls back to direct `LiteLLMChatLLM` when it isn't.
- **`BedrockChatLLM`** now only injects `modify_params=True` for Anthropic on Bedrock; Nova, Titan, Llama, Mistral, and `openai.gpt-oss-120b` on Bedrock work without the prior "extraneous key" rejection.

### Python 3.13 + 3.14 Support

- Added `Programming Language :: Python :: 3.13` and `:: 3.14` classifiers to `pyproject.toml`. `requires-python = ">=3.11"` already let 3.13 / 3.14 installs succeed; the classifiers make the support discoverable on PyPI.
- CI matrix expanded to `['3.11', '3.12', '3.13', '3.14']` on `ubuntu-latest` and `macos-latest` (`.github/workflows/test.yml`).
- `datetime.utcnow()` replaced with `datetime.now(timezone.utc)` in `costs.tracker.CostRecord` and `notifications.base.Notification`. `utcnow()` has been deprecation-warned since 3.12 and will be removed — this is a forward-compatible swap with identical behaviour.

### Notebook 46 — Runnable Walk-Through

- **`notebooks/46_dashboard_render_tool_and_litellm.ipynb`** — pick an LLM (Bedrock / LiteLLM direct / LiteLLM proxy with your URL + key) → `render_dashboard(spec)` → Agent with the tool → Autopilot artifact ingest.
- Executes clean with 0 cell errors; writes `life_vision.html` + `finance-one-pager-fy26.html` under `notebooks/_dashboard_workspace/`.
- Regenerated via `notebooks/_nb46_builder.py`.

### Tests — +41 New, All Passing

- `tests/test_autopilot_hardening.py` — 14 tests for full-usage persistence, v1 back-compat, corruption quarantine, dollar tracking (explicit / pricing / disabled), SIGTERM stop, first-iter heartbeat, `remaining` payload, pre-iteration projection.
- `tests/test_autopilot_long_task.py` — 6 compressed-time simulations (hundreds of iterations, 5-crash resume chain, SIGTERM mid-run, mid-run corruption recovery, 50-child fan-out) + 1 opt-in Bedrock soak gated on `SHIPIT_AUTOPILOT_SOAK=<seconds>`.
- `tests/test_autopilot_bedrock_e2e.py` — 7 real-Bedrock E2E tests (`SHIPIT_BEDROCK_E2E=1`) covering run, stream, resume-cumulative, dollars, artifacts, critic, fan-out.
- `tests/test_dashboard_render.py` — 20 tests across every section type, escaping, color allow-list, chart config, export + traversal guard, `ArtifactCollector` ingest, and a realistic full-spec life-vision dashboard.
- `tests/test_notebook_assets.py` — locks the current notebook-44/45 API usage so the recent fixes can't regress.

### Fixed

- A resumed Autopilot previously reset wall-clock, tokens, tool-calls, and dollars to zero — only iteration count survived the checkpoint.
- `usage.dollars` was never incremented, so `max_dollars` budgets never fired.
- `BedrockChatLLM` could not drive non-Anthropic Bedrock models because the adapter always injected `modify_params=True`.

### Upgrade

```bash
pip install --upgrade shipit-agent==1.0.6
```

No breaking changes. Checkpoints written by 1.0.5 load transparently via the v1-compat path.

## v1.0.5 — 2026-04-18

**Prebuilt agents, multi-agent crews, notifications, and cost tracking.** 40 ready-to-use agent personas. DAG-based ShipCrew orchestration with sequential, parallel, and hierarchical modes. Slack, Discord, and Telegram notification hub. Real-time cost tracking with budget enforcement. 4 new notebooks and expanded regression coverage across the new APIs.

### Prebuilt Agents — 40 Ready-to-Use Personas

- **`shipit_agent.agents` module** — new `AgentDefinition` dataclass and `AgentRegistry` for loading, searching, and composing agent personas.
- **40 agents across 8 categories**: Architecture (5), Code Quality (6), Security (5), DevOps (5), Testing (5), Planning (4), Research (5), Content (5).
- **`AgentRegistry.default()`** — loads the built-in `agents.json` in one line.
- **Search & browse** — `registry.search("security audit")`, `registry.list_by_category("Security")`, `registry.categories()`.
- **`.shipit/agents/` override** — drop JSON agent files in your project directory; `AgentRegistry.from_directory()` loads them, `registry.merge()` combines with built-ins.
- **`AgentDefinition.system_prompt()`** — assembles role, goal, backstory, and prompt into a structured system prompt with `# Role`, `# Goal`, `# Background`, `# Instructions` headers.
- **Serialization** — `to_dict()` (camelCase) and `from_dict()` (accepts both camelCase and snake_case).
- Each agent has 1,200–1,800 char prompts with methodology, quality standards, and output format.

### ShipCrew — Multi-Agent Crew Orchestration

- **`shipit_agent.deep.ship_crew` package** — new `ShipCrew`, `ShipAgent`, `ShipTask`, `ShipCoordinator`, `ShipCrewResult` classes.
- **DAG-based task dependencies** — `ShipTask.depends_on` forms a directed acyclic graph. Kahn's algorithm validates no cycles and resolves topological execution order.
- **Three execution modes**:
  - `sequential` — tasks run one at a time in topological order.
  - `parallel` — independent tasks in the same DAG layer run concurrently via `ThreadPoolExecutor`.
  - `hierarchical` — coordinator LLM dynamically assigns tasks, reviews output, and can request revisions.
- **Template variable resolution** — `{output_key}` in task descriptions auto-resolves from upstream task outputs. `_SafeFormatMap` ensures missing keys don't crash.
- **Context variables** — `crew.run(topic="AI", audience="devs")` injects runtime variables into task descriptions.
- **`ShipAgent.from_registry()`** — build crew agents directly from the prebuilt agent registry.
- **`create_ship_crew()` factory** — accepts plain dicts or objects; useful for JSON-driven configuration.
- **Validation** — `crew.validate()` checks missing agents, unknown dependencies, and cyclic DAGs before execution.
- **Streaming** — `crew.stream()` yields `AgentEvent` for `run_started`, `task_started`, `task_completed`, `task_failed`, `run_completed`.
- **Error types** — `ShipCrewError`, `CyclicDependencyError`, `MissingAgentError`, `TaskTimeoutError`.
- **Task features** — `max_retries`, `timeout_seconds`, `context` dict, `output_schema` for structured output.
- **`ShipCrewResult`** — `output`, `task_results` (per-task outputs by key), `execution_order`, `failed_tasks`, `metadata` (timing).

### Notification Hub — Slack, Discord & Telegram

- **`shipit_agent.notifications` package** — new `NotificationManager`, `Notification`, `SlackNotifier`, `DiscordNotifier`, `TelegramNotifier`.
- **Slack** — Block Kit webhooks with color-coded severity bars, metadata fields, and timestamps. Uses `urllib.request` — zero external dependencies.
- **Discord** — rich embeds with color-coded severity, inline metadata fields, and footer. Handles 204 responses correctly.
- **Telegram** — Bot API with MarkdownV2 formatting, auto-escaped special characters, emoji severity indicators.
- **`NotificationManager`** — dispatch to multiple channels simultaneously. Filter by `min_severity` and/or `events` list.
- **`manager.as_hooks()`** — returns `AgentHooks` that auto-notify on `run_started`, `run_completed`, `tool_failed`. Wire into any agent with `hooks=manager.as_hooks("my-agent")`.
- **Custom templates** — override default message templates per event type. `render_template()` uses safe formatting (missing keys stay as `{key}`).
- **Severity levels** — `info`, `warning`, `error`, `critical` with numeric ordering for filtering.
- **`Notifier` protocol** — build custom notifiers (PagerDuty, Teams, SMS) by implementing `async send(notification) -> bool`.

### Cost Tracking & Budgets

- **`shipit_agent.costs` package** — new `CostTracker`, `Budget`, `BudgetExceededError`, `CostRecord`.
- **`MODEL_PRICING`** — built-in per-million-token pricing for 20+ models: Claude Opus/Sonnet/Haiku 4, GPT-4o/4o-mini/4.1/o3/o4-mini, Gemini 2.5 Pro/Flash, Llama 4 Scout/Maverick, Bedrock model IDs. Includes cache read/write pricing for Anthropic.
- **`MODEL_ALIASES`** — short names: `"opus"` → `"claude-opus-4"`, `"sonnet"` → `"claude-sonnet-4"`, etc.
- **`CostTracker.record_call()`** — records an LLM call, computes USD cost, checks budget, and returns a `CostRecord`.
- **`Budget(max_dollars=5.00, warn_at=0.80)`** — budget enforcement. `BudgetExceededError` raised when exceeded; `on_cost_alert` callback at warning threshold.
- **`tracker.as_hooks()`** — returns `AgentHooks` for automatic per-call cost tracking. Extracts usage from Anthropic, OpenAI, and Bedrock response objects.
- **`tracker.breakdown()`** — per-call cost attribution. `tracker.summary()` — full report with totals, budget status, and per-call details.
- **`tracker.add_model()`** — register custom model pricing at runtime.

### Notebooks

- **Notebook 32** — Prebuilt Agents (27 cells): registry loading, category browsing, search, category statistics, agent inspection, live agent construction, multi-category showcase, serialization, custom definitions, registry merging, `.shipit/agents/` override, ShipCrew integration.
- **Notebook 33** — ShipCrew Orchestration (28 cells): basic crew, diamond DAG, parallel mode, context variables, hierarchical LLM-driven mode, streaming events, from registry, factory, validation/errors, ShipTask advanced features, crew + cost tracking.
- **Notebook 34** — Notifications (27 cells): notification data model, all severity levels, Slack Block Kit, Discord embeds, Telegram MarkdownV2, severity comparison, production event examples, multi-channel dispatch, severity/event filtering, real agent demo, custom templates, cost alert integration.
- **Notebook 35** — Cost Tracking & Budgets (31 cells): pricing table, model comparison, cache savings calculator, per-call tracking, budget enforcement, warning callbacks, breakdown, summary, custom pricing, auto-hooks, streaming + live cost, multi-model tracking.

### Tests

- Expanded regression coverage across the new surfaces:
  - `test_prebuilt_agents.py` (39 tests): AgentDefinition serialization, system prompt assembly, AgentRegistry loading/search/merge/categories, data integrity validation for all 40 agents.
  - `test_ship_crew.py` (44 tests): ShipTask resolution/serialization including `output_schema`, ShipAgent construction/delegation/from_registry, ShipCoordinator DAG building/cycle detection/sequential/parallel/hierarchical execution, ShipCrew validation/run/stream/context variables, create_ship_crew factory, error inheritance.
  - `test_notifications_and_costs.py` (76 tests): Notification model/serialization, severity ordering, template rendering, SlackNotifier Block Kit/send, DiscordNotifier embeds/send, TelegramNotifier MarkdownV2/escaping/send, NotificationManager dispatch/filtering/hooks/custom templates, Budget warn/exceed, BudgetExceededError, CostTracker pricing/recording/breakdown/summary/budget/warnings/hooks/reset, usage/model extraction, MODEL_PRICING completeness, alias resolution.

### New Files

```
shipit_agent/agents/__init__.py
shipit_agent/agents/definition.py
shipit_agent/agents/registry.py
shipit_agent/agents/agents.json              (40 agent definitions)
shipit_agent/deep/ship_crew/__init__.py
shipit_agent/deep/ship_crew/agent.py
shipit_agent/deep/ship_crew/coordinator.py
shipit_agent/deep/ship_crew/crew.py
shipit_agent/deep/ship_crew/errors.py
shipit_agent/deep/ship_crew/result.py
shipit_agent/deep/ship_crew/task.py
shipit_agent/notifications/__init__.py
shipit_agent/notifications/base.py
shipit_agent/notifications/discord.py
shipit_agent/notifications/manager.py
shipit_agent/notifications/slack.py
shipit_agent/notifications/telegram.py
shipit_agent/notifications/templates.py
shipit_agent/costs/__init__.py
shipit_agent/costs/budget.py
shipit_agent/costs/pricing.py
shipit_agent/costs/tracker.py
tests/test_prebuilt_agents.py
tests/test_ship_crew.py
tests/test_notifications_and_costs.py
notebooks/32_prebuilt_agents.ipynb
notebooks/33_ship_crew_orchestration.ipynb
notebooks/34_notifications.ipynb
notebooks/35_cost_tracking_and_budgets.ipynb
```

---

## v1.0.4 — 2026-04-12

**Skills, tools, and runtime power-up.** All 32 tool prompts rewritten with decision trees and anti-patterns. Full skill-to-tool linking for all 37 packaged skills. Automatic iteration boost for skill-driven workflows. Expanded bash allowlist (50+ commands). Streaming, chat, and project-building examples across 3 notebooks. Comprehensive docstrings across every key module. **32 skill tests. All passing.**

### Skills — Full Tool Linking

- **37 skill tool bundles** (up from 10) — every packaged skill now declares the built-in tools it needs. When a skill is selected, the agent auto-attaches the right tools.
- **Shared tool groups** (`_FILE_CORE`, `_CODE_CORE`, `_WEB_CORE`) reduce duplication across bundles.
- **`validate_tool_bundles()`** — new helper that checks every tool name in `SKILL_TOOL_BUNDLES` against the real builtin map.

### Agent — Iteration Boost & Efficiency

- **`_effective_max_iterations()`** — auto-boosts 4 → 8 when skills inject extra tools so skill-driven workflows can complete without cutting off early.
- **Single skill computation** — `run()` and `stream()` now compute skills once and reuse (previously 3x per call).

### Tool Prompts — All 32 Upgraded

Every tool's `prompt.py` rewritten with decision trees, anti-patterns, workflow guidance, and cross-tool coordination.

### Bash Allowlist Expansion

- **50+ safe commands** added: `mkdir`, `touch`, `cp`, `mv`, `echo`, `grep`, `curl`, `docker`, `kubectl`, `terraform`, `aws`, `go`, `cargo`, `npx`, `tsc`, `eslint`, `black`, `isort`, `tree`, `awk`, `cut`, `diff`, and more.

### Documentation

- Comprehensive docstrings on `agent.py`, `builtins.py`, `skills/loader.py`, `skills/registry.py`, `skills/tool_bundles.py`, `deep_agent/factory.py`.
- 6 tool doc pages updated with enhanced prompts.
- Skills guide expanded with 7 real-world examples, streaming sections, chat sessions, and event type reference.
- **Notebook 27** rewritten (38 cells): streaming, chat streaming, project build, web scraping, DeepAgent chat.
- **Notebook 29** (new): DeepAgent + skills + memory + verify + reflect + sub-agents + streaming.
- **Notebook 30** (new): real-world full project build across 6 steps with 5 different skills.

### Tests

- **15 new tests** (17 → 32 total): iteration boost, bundle validation, chat sessions, streaming, chat streaming, memory + skills, DeepAgent chat/stream.

---

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
- Full MkDocs Material documentation site at [docs.shipiit.com](https://docs.shipiit.com/)

### Breaking changes

None — this is the first stable release. Subsequent 1.x releases will maintain backward compatibility within the 1.x line.
