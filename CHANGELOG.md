# Changelog

All notable changes to **shipit-agent** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Nothing yet.

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
