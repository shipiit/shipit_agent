# Changelog

All notable changes to **shipit-agent** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

Nothing yet.

---

## v3.1.1 — 2026-11-10

### Fixed

- **The vision tool sends the image.** `VisionTool` put the image in message
  metadata that no adapter reads and sent only a shortened text placeholder, so
  the model never saw the picture. The image is now an image block in the
  message content, which every provider receives.
- **Web search reports DuckDuckGo's bot check.** DuckDuckGo's keyless results
  page answers automated requests with a bot check; the provider read that as
  "no results", so searches silently found nothing. It now raises an error that
  names the providers that work with a key (Brave, Serper, Tavily).
- **`workspace_files` lists a workspace reached through a symlink**, such as
  macOS's temp folder, instead of raising `ValueError`.
- **The LiteLLM extras install `mcp`.** LiteLLM 1.106 and later import `mcp`
  on every call that passes tools, but install it only with their own `[mcp]`
  extra, so an agent on `[litellm]`, `[google]`, `[groq]`, `[together]` or
  `[ollama]` failed on its first call with `No module named 'mcp'`. Those extras,
  and `[all]`, now install it.
- **A held tool call is not retried.** After a call that waited for permission,
  was denied, was queued for approval or was missing an argument, the next step
  still told the model it had not called any tool yet. Models obeyed that over
  the tool message saying the call must not be retried, so a gated action such
  as an invite was attempted again every step, one approval card each time. A
  call the model made now counts whether or not it ran.

---

## v3.1.0 — 2026-11-09

### Added

- Local Chrome Workspace companion with a docked, height-aware chat panel,
  compact composer, streamed replies, page snapshots, screenshots and bounded
  image/document uploads. Default model selection includes Gemma 4 31B and
  26B-A4B on Bedrock; model changes preserve backend chat history.
- Optional Google Docs, Sheets and Slides API tool with per-chat change
  proposals, explicit Apply controls, revision checks for Docs/Slides and
  best-effort conflict detection for Sheets. Added the `browser` install extra
  and local setup documentation.
- Browser bridge validation and session-isolation tests, Workspace proposal
  tests, attachment tests, streaming decoder tests and an opt-in five-turn
  real Bedrock HTTP/SSE smoke test.
- **`sandbox`**, the Claude Agent SDK option: bash and `run_code` run under
  Seatbelt on macOS or bubblewrap on Linux, writing only in the project, the
  `add_dirs` folders, temp and `filesystem.allowWrite`, with the network off
  unless `network.allowedDomains` is set. `excludedCommands`,
  `allowUnsandboxedCommands` (`dangerouslyDisableSandbox`, approved like a
  risky command), `autoAllowBashIfSandboxed`, `failIfUnavailable`,
  `filesystem.denyWrite`/`denyRead`, `allowLocalBinding` and Unix sockets are
  enforced. Domains are not filtered one by one. Also usable directly as
  `BashTool(sandbox_policy=...)`.

### Changed

- **Every module is under 300 lines** except the package `__init__`, which
  is only the public import list. 38 modules split by job into sibling
  modules and mixins; public names import from the same paths as before.
  `shipit_agent.apps` is now a package, and `create_deep_agent` lives in
  `deep/deep_agent/create.py` (still importable from `factory`).
- **The license is declared as an SPDX expression** (`license = "MIT"`), as
  setuptools requires from 2027; building now needs setuptools 77 or newer.

### Fixed

- **Relative sandbox paths point at the project.** `filesystem.denyWrite`,
  `denyRead` and `allowWrite` entries such as `".env"` were resolved against
  the Python process's working directory, so `denyWrite: [".env"]` protected
  nothing when the process ran from another folder (a server, a notebook).
  They now resolve against the project root.
- **System messages reach Anthropic models.** `AnthropicChatLLM.complete()`
  dropped system-role messages unless `system_prompt=` was also passed, so
  callers that send their instructions as a system message lost them: the
  verifier's pre-tool and progress checks (vetoes never fired), memory
  summaries and the autopilot critic. They now become the system prompt.
- **The verifier's stats count checks made inside a run.** Tools wrapped by
  `VerifierNetwork` called the checker directly, bypassing the counters, so
  `verifier.stats` read zero however many calls it vetoed.
- **`verify_before_stop` uses the agent's project.** The verify gate looked
  for the test command in the process's working directory unless
  `persist_large_tool_outputs` was on, so it was silently off for agents
  whose `project_root` was elsewhere.
- **Autopilot counts tokens and dollars.** `GoalResult` carried no usage, so
  Autopilot's token and dollar meters read zero and `max_tokens` /
  `max_dollars` could never stop a run. `GoalResult.metadata` now has the
  summed usage, the model and the tool-call count of its steps.
- **A caller's system messages in `history=` are kept.** System context passed
  in the history, such as a `ConversationMemory` summary, was dropped with the
  stored session prompts; it is now added to the turn's system prompt.
- The cost alert log line shows the budget to four decimals, like the spend.
- **Memory search finds facts by their words.** `InMemoryMemoryStore` and
  `FileMemoryStore` matched only facts containing the exact query text, so the
  `memory` tool's natural searches ("deploy region") found nothing. Facts now
  rank by the query words they contain, the exact phrase first.
- **RAG sources are reported again.** `result.rag_sources` and the streamed
  `rag_sources` event were always empty in an agent run: the source tracker
  was thread-local and the agent loop runs on a worker thread. It is now a
  context variable, which the worker inherits; concurrent runs still keep
  their own sources.
- **RAG citation numbers match the sources.** `rag_search` numbered each
  search's results from `[1]`, so after a second search the model's `[1]`
  and `rag_sources[0]` were different chunks. Inside a run, every hit is now
  labelled with its run-wide number, a chunk found again keeps its first
  number, and `rag_fetch_chunk` includes the chunk's `citation`.

- Browser connection failures remain visible inside the settings dialog and
  failed token changes preserve the displayed conversation. Unfinished runs
  are no longer presented as complete; malformed model selections return a
  client error without losing the chat.
- Chat-session streaming forwards images and files and closes its underlying
  stream when the consumer disconnects.
- **A call that needs approval no one can give** now says it was not run and
  what to do instead: finish the task and name what still needs approval.
  Told only "requires human approval", Gemma retried `rm` and then asked for
  confirmation in text until it ran out of turns.
- **Renames across many files**: the bash guidance names one portable
  `perl -pi -e` call, then a `grep_files` check, instead of a read and an edit
  per file, and puts throwaway scripts in a temp folder. Gemma's rename across
  eight modules passed 5 of 5 runs in 7-12 turns (before: 3 of 6, up to 40
  turns and 863k input tokens). All 18 benchmark tasks pass on Gemma 4 and
  Claude Sonnet 5.5; Claude's input tokens fell 11%.
- **The benchmark paired tool results with calls by position**, so one call
  without a result shifted every later one in the trace; it pairs by id.

## v3.0.0 — 2026-11-07

Feature and default parity with the Claude Agent SDK and Claude Code, under
the same API names, on every provider. Several defaults changed: see
docs/guides/upgrading.md, and docs/releases/3.0.0.md for the full notes.

### Added

- `shipit_agent.sdk`: `query()`, `AgentOptions`, typed messages, `AgentClient`
  (multi-turn, interrupt, file rewind), saved sessions (resume, fork),
  in-process MCP tools (`@tool`, `create_sdk_mcp_server`), `AskUserQuestion`.
- `shipit_agent.harness`: Claude Code plugins, settings files (opt-in) and
  shell command hooks.
- Permission rules in the SDK's syntax, checked in its order;
  `allowed_tools`, `disallowed_tools`, `max_turns`, `dontAsk` mode.
- All ten SDK hook events; hooks may defer a call to resume it later.
- User-defined sub-agents; background tasks with notifications and
  `task_stop`; `fallback_model`.
- `clear_tool_results` (off by default) for very long runs.
- MCP servers over SSE (`{"type": "sse"}`), `continue_conversation`,
  `add_dirs`, `env`, `betas` and `max_thinking_tokens` on `AgentOptions`.
- A run's usage, and `ResultMessage.usage`, carries the SDK's shape
  (`input_tokens` uncached, the cache counters, `output_tokens`) for every
  provider.
- `scripts/bench`: 18 real tasks checked by outcome, with traces,
  `--repeat` and run comparison.

### Changed

- No step limit by default (`max_iterations`, `max_budget_usd` are opt-in).
- Read-only tool calls run in parallel by default.
- Claude Code's working set of tools stays resident; skills load on demand.
- The automatic planner is opt-in.
- Bash: full shell under permissions, two-minute default timeout, long
  commands continue in the background.
- The fixed per-turn prompt is about 42% smaller.
- `shipit chat` prints a compact transcript by default.

### Fixed

- Without the `anthropic` package, Anthropic requests raised nothing and
  went to gpt-oss on Bedrock; they now raise with the install command.
- The native Anthropic adapter sent shipit's tools in OpenAI's shape, so the
  API rejected every request that had a tool; they are now converted.
- Streamed text could arrive after `run_completed`, and the transcript then
  showed the answer twice.
- Dropped connections are retried instead of ending the run.
- A background sub-agent's whole work shows in the live display.
- Current Claude models, gpt-oss and Gemma 4 on Bedrock are priced at their
  own rates.
- The docs build (`mkdocs --strict`) failed on a link outside the docs folder.
- The installed package now includes the packaged skills catalog and agents
  (`skills/skills.json`, `agents/agents.json`); the wheel had left them out.

## v2.2.1 — 2026-10-07

### Security

- `bash` (including background jobs read via `bash_job`) and `run_code`
  spawned model-written commands with the full host environment, so any
  secret in the process env (`SECRET_KEY`, DB passwords, API keys loaded by
  dotenv) was readable with `printenv` / `os.environ`. Their child processes
  now get a scrubbed environment: `PATH`, `HOME`, `USER`, `LOGNAME`, `SHELL`,
  `LANG`, `LANGUAGE`, `LC_*`, `TERM`, `TZ`, `TMPDIR`/`TMP`/`TEMP`,
  `PYTHONIOENCODING` and the Windows basics. `SSH_AUTH_SOCK` is not kept.

### Changed

- Behaviour change: commands run by `BashTool` and `CodeExecutionTool` no
  longer see host environment variables outside that list. Opt in with the
  new keyword arguments on both tools: `env_allowlist=["NAME", ...]` passes
  named host variables through, `extra_env={...}` sets explicit values (e.g.
  `{"HOME": workspace}`), and `inherit_env=True` restores the previous
  full-environment behaviour. `run_code` with `sandbox=true` also passes
  `DOCKER_*` to the `docker` CLI. `bash` still runs a login shell (`bash
  -lc`), so profile files can re-export variables; override `HOME` via
  `extra_env` if that matters.
### Fixed

- A text tool call such as `{"path": …, "content": …}` fit several file tools
  (each declares `path`) and was dropped as ambiguous, so the file was never
  written. When several tools accept a nameless object, the one tool that
  declares every key it carries is chosen; a genuine tie is still left alone.

## v2.2.0 — 2026-10-02

### Fixed

- A model that kept calling a tool after the runtime switched to a text-only
  step looped to `max_iterations` (16 model calls, ~70k tokens, seen live with
  a small model). Calls on a text-only step are now ignored and the text is
  the answer; emits `tool_calls_ignored`.
- The "you have not called any tool yet" reminder was sent as its own trailing
  user message, and small models answered it ("I am ready for your request")
  instead of the question, or called a document tool for facts already in the
  chat. It now rides on the request as a labelled note; after a tool result it
  still follows, marked internal.
- Text-call healing promoted any JSON object to a call of a no-argument tool
  (its empty schema skipped the key check). A model's JSON *answer* became a
  phantom `list_documents` call and vanished from the reply, structured-output
  answers were re-run as tool calls, and genuine nameless calls became
  ambiguous and were dropped. A nameless object with keys never matches a tool
  that takes no arguments.
- `on_user_prompt` hooks were documented but never called; both runtimes now
  run them before anything else sees the prompt (rewrite, or deny with
  `prompt_blocked`).

### Added

- Stop hooks: `AgentHooks.on_stop` sees the answer the agent is about to give
  and can send it back to work with a reason (Claude Code-style `Stop`
  hooks), in sync and async runs. Bounded by `MAX_STOP_CONTINUATIONS` (3);
  emits `stop_blocked`, `stop_unresolved` and `stop_hook_error`.
- `StepRouter` (`shipit_agent.routing`): a drop-in LLM that picks the model
  per step of a run. Routine steps (reading successful tool results) and
  summaries run on `fast`; planning a turn, recovering from a failed tool,
  side calls and the final answer run on `strong`. A fast step's text is
  buffered: if it calls tools the narration is released, and if it starts
  answering the step is re-run on `strong`, so the user never reads the small
  model's answer or sees text twice. Works for sync, async and streaming runs.
- `max_session_tokens`: a soft token budget across every run of an agent or
  one chat session, checked between steps; an exhausted session stops before
  spending. `agent.session_token_usage` and `agent.reset_session_usage()`.
- Diagnostics report `discarded_tokens`, `session_token_limit` and
  `session_tokens_used`.

### Changed

- The user's real prompt is tagged `metadata["turn_start"]`, so tools can tell
  it apart from runtime-injected user messages (reminders, retry nudges).
- A routed step's discarded call counts toward usage, cost and budgets but not
  toward context calibration, which is now keyed on the model that ran the step.

### Limitations

- Early abort of a fast step needs an adapter that stops streaming when the
  text callback returns `False` (OpenAI-compatible and LiteLLM do). The native
  Anthropic adapter ignores that return value, so there the fast call runs to
  completion before escalating.
- Savings depend on the price ratio between the two models and on how often
  fast steps escalate; they have not yet been measured against live models.

## v2.1.0 — 2026-09-29

### Added

- Schema-budgeted automatic tool discovery for ordinary `Agent`, streaming and
  async runs. Large catalogs start with a small resident set plus discovery;
  authorized tool schemas load on demand. `DiscoveryPolicy` controls the
  initial count, schema budget and reuse. Discovery does not grant permission.
- Bounded, schema-fingerprinted discovery checkpoints for reuse across turns,
  revalidated against the current authorized catalog. Corpus-weighted lexical
  search supports authored `discovery_terms`, exact names and MCP metadata.
- Opt-in `progressive_skills=True`: advertise enabled skill metadata and load
  instructions on demand with fresh per-run state. Explicit/default skills
  retain their existing behavior; loading a skill grants no new tools.
- Optional `max_task_tokens` soft per-run budget. Budget stops retain completed
  tool evidence and mark work incomplete. Missing/partial input-output usage
  stops budgeted continuation; the iteration-cap summary also respects the
  budget. In-flight calls/retries can overshoot; this is not a spending cap.
- Usage diagnostics separate estimated request content from reported main and
  compaction usage, track prefix changes, and distinguish partial accounting
  and missing cache counters from complete reports. Cache hits are not assumed.
- `ToolOutput.from_records` provides bounded, field-selected model views while
  retaining canonical evidence for the host.
- Reproducible live fixture evaluations, 100–500-tool discovery benchmarks,
  loopback HTTP/SSE MCP failure-isolation tests, and a custom harness guide.

### Fixed

- Preserve native assistant tool calls and matching tool-result IDs when
  accepting wire-style chat history. Preserve provider finish reasons and
  expose incomplete output rather than treating every stop as success.
- Honor separate system prompts in OpenAI/LiteLLM calls, including compaction
  instructions. Improve summary chronology, exclude summaries from user-turn
  counts, and retain the newest user turn under tight compaction budgets.
- Normalize inclusive versus exclusive cache accounting without changing raw
  provider counters, including compaction usage and cost calculations.
- Prevent plugin tool/hook reactivation during chat cloning, isolate hook
  lists, and preserve host-supplied tools when skills contribute capabilities.
- Deduplicate shared tool guidance; bound skill descriptions; validate skill
  reference containment; avoid constructing unused builtin tool catalogs.
- Propagate nested tool failures through code-mode results and preserve
  streaming alongside tools. Extend MCP reconnect/session-affinity coverage.

### Validation and limitations

- Latest full Shipit regression: **4,514 passed, 31 skipped**; one collection
  warning. Targeted DRK integration after the final budget fixes: **87 passed**.
- Real Gemma 31B/Bedrock with controlled MCP data: 40-message session passed
  40/40 evidence checks with three compactions; a fresh 20-message stream passed
  20/20 with 537 text deltas, six completed tool calls and one compaction.
- Budget-enabled live fixture run: 10/10 scenarios, 42,040 input / 391 output
  tokens, including 2,368 reported cached input tokens. No universal cache
  savings, all-provider live coverage or production-connector reliability claim.
- The offline 500-tool benchmark reduced serialized request characters 89.1%
  while adding one request. This is not a billed-token or intelligence score.
- Existing plugin/hook composition is supported; executing Claude Code/Codex
  as a backend is not implemented. Progressive cross-turn skill-body deduplication
  and session-wide budgets remain future work.

See [controls and detailed validation](https://github.com/shipiit/shipit_agent/blob/main/docs/progressive-agent-controls.md),
[efficiency measurements](https://github.com/shipiit/shipit_agent/blob/main/docs/agent-efficiency-validation.md),
[discovery review](https://github.com/shipiit/shipit_agent/blob/main/docs/tool-discovery-review.md) and
[custom harness composition](https://github.com/shipiit/shipit_agent/blob/main/docs/guides/custom-agent-harness.md).

## v1.9.9 — 2026-08-19

Live-trace-driven fixes for Gemma 4 on Bedrock Mantle (and every model): fewer tokens, real cost, tools that actually work.

### Changed

- **`CORE_TOOLS` 25 → 13.** The deferred-tools resident set held twelve synonyms
  of the same capability (`run_code`/`execute_code`/`bash`, four "write
  structure" tools, `ask_user`/`ask_user_async`/`human_review`, …). A model
  choosing between them guesses right about a third of the time. Trimmed to one
  tool per capability; everything dropped stays reachable through `tool_search`.
  The deferred first turn drops from ~7.4k to ~3.7k Gemma tokens. `execute_code`
  and `describe_binding` are kept — code mode depends on them.
- **Gemma 4 real context window** in `get_model_limits`: 256K (31B / 26B-A4B),
  128K (E2B). Previously a low default made compaction fire at a fraction of the
  model's capacity ("it forgets things").

### Added

- **Gemma pricing rows** (26b / 31b / e2b) so a run's cost is not silently
  reported as `$0.00`. An unknown model still resolves to `None`, not a
  zero-rate default — unknown and free are different answers.
- **"Look before you ask"** in `DEFAULT_AGENT_PROMPT`: the agent searches for a
  referenced file/document/error with the tools it has before asking the user to
  provide it.

### Fixed

- **`$ref` / `$defs` inlining on tool schemas** (`llms/schema_prep.py`, wired
  into the LiteLLM adapter). Pydantic / FastMCP MCP servers emit `$defs` +
  `$ref` for nested argument models; OpenAI tolerates it but a strict
  OpenAI-*compatible* validator like Bedrock Mantle often does not — simple
  tools keep working, nested ones fail quietly, and the model reads as stupid
  rather than blocked. Each tool's parameter schema is now inlined and
  dialect-sanitized (cached, never-raising) before it goes on the wire. **Host
  params** (`max_context_tokens`, `file_token_limit`, …) are stripped off the
  wire — forwarding one is a 400 on a field never aimed at the model.

## v1.9.8 — 2026-08-19

Tool calling engages reliably on OpenAI-compatible endpoints that need it spelled out.

### Fixed

- **Send `tool_choice: "auto"` when tools are offered.** The LiteLLM adapter passed
  `tools` but never `tool_choice`. Most providers assume `auto`, but some
  OpenAI-compatible endpoints — notably AWS Bedrock's Gemma (`bedrock-mantle`)
  route, per AWS's own examples — only engage function calling when
  `tool_choice` is sent explicitly; without it the model narrates the call as
  prose and loops instead of emitting a structured call. A caller can still
  override (`"required"`/`"none"`) via `completion_kwargs`. Applies to both the
  streaming and non-streaming paths.

## v1.9.7 — 2026-08-18

Context accounting is real from the first turn, not an estimate.

### Added

- **Real per-model token counting** (`count_tokens`, `count_message_tokens`). Real
  counts via LiteLLM's tokenizer (already a dependency), memoised, with a safe
  fall-back to the `chars/4` estimate — never raises. For models LiteLLM only
  approximates (some Bedrock ids), the `TokenCalibrator` still refines against the
  provider's *actually reported* `prompt_tokens`, the true ground truth.
- **`Agent(fixed_prefix_tokens=…)`** — forwarded through both runtimes to the
  `Compactor`, so a host can pass a real system-prompt + tool-schema prefix count
  and compaction is accurate from turn one; the calibrator seeds and refines the
  rest. The accurate-from-turn-one path is: real count → calibrator refines.

## v1.9.6 — 2026-08-18

One flaky MCP connector no longer taxes the whole agent.

### Added

- **MCP resilience — circuit breaker + bounded retry** (`ResilientMCPTransport`,
  `CircuitBreaker`). An MCP connector is a live dependency; when one goes down,
  gets slow, or starts rate-limiting, it was re-dialled on every step and each
  attempt waited out the full transport timeout. Now a per-server breaker marks a
  server *open* after a few consecutive failures and fails fast (no network wait)
  until an exponentially-growing cooldown elapses; one success resets it. A
  rate-limit (HTTP 429 / JSON-RPC `-32029`) trips it immediately with a long,
  fixed cooldown — never hammer a server that asked us to slow down. The wrapper
  is transparent (`request`/`close` + attribute passthrough) and wired into
  `connectors.registry`, so every hosted (HTTP) and stdio connector is resilient
  by default. Failures still surface as the readable tool result the model
  already handles — this just stops the stall.

## v1.9.5 — 2026-08-18

Compaction fires at the *right* time, so long tool-heavy runs stay lean and stop overflowing the model.

### Added

- **Calibrated, prefix-aware context accounting** (`TokenCalibrator`). The
  compaction trigger ran on two systematic under-counts: it ignored the fixed
  prompt prefix (system prompt + tool schemas, ~16k tokens on a tool-heavy agent)
  because those live outside `messages`, and it estimated tokens as `chars/4`,
  which under-counts dense JSON tool output (~2.5–3 chars/token) — the shape that
  most needs compacting. Together they fired the trigger late enough to overflow
  the provider. Now a per-model EMA learns the gap between the estimate and the
  provider's real `prompt_tokens` (prompt-cache counters included, so a cache hit
  can't drag it down), and the `Compactor` counts the fixed prefix. The trigger
  and the retention target derive from one calibrated estimate; `estimate_tokens`
  stays a pure function. Clamped asymmetrically (floors at 1.0 — it can only ever
  compact *earlier*), model-keyed, warm-up gated. Fed from the exact view sent at
  each main completion, never the summary pass. Backwards compatible: no prefix +
  no calibrator reproduces the old messages-only estimate.

## v1.9.4 — 2026-08-16

### Added

- **Text-to-speech: bring-your-own-key.** `TextToSpeechTool(provider_keys={...})`
  lets a host pass an org's own OpenAI/Gemini/ElevenLabs key **at synthesis time**
  — the backend uses it directly and never reads the shared process env, so a
  multi-tenant server keeps `os.environ` clean per tenant. The tool's
  availability gate now also counts a host-supplied key (so a keyed provider is
  offered even when nothing is in the env), and each backend prefers an explicit
  `api_key` over its env var. Edge stays free with no key.

## v1.9.3 — 2026-08-16

The agent can't declare a coding task done on failing tests.

### Added

- **Verify-on-stop — evidence-gated coding** (opt-in `Agent(verify_before_stop=True)`).
  Wires the shipped verification ledger into the loop so the agent **cannot finish
  a turn that edited code without fresh passing tests**. As tools run, a
  `VerifyGate` records edits (a non-read-only tool that touched a verifiable file
  — a README/LICENSE edit never counts, and a *failed* edit never counts) and
  verify runs (a shell command matching the project's detected test command,
  by real exit code). When the model tries to finish, an edited-but-unverified
  turn is sent back with a "run the tests, read the failure, fix it" nudge
  (bounded, emits `verify_required`); once a matching command exits 0, it
  finishes. If it runs out of steps first, `verify_skipped` is emitted rather
  than a silent unverified "done". Off by default; **sync loop** (which the
  streaming path runs on) — async parity is a follow-up.

## v1.9.2 — 2026-08-16

More deliverables and more voices.

### Added

- **Text-to-speech: a Gemini backend + a pinnable default provider.** The `tts`
  registry now includes **Gemini** (`gemini-2.5-flash-preview-tts`, wraps the
  API's raw PCM into a playable WAV) alongside Edge (free) / OpenAI / ElevenLabs,
  and `TextToSpeechTool` takes a `default_provider` / `default_voice` (or reads
  `SHIPIT_TTS_PROVIDER` / `SHIPIT_TTS_VOICE`). A multi-tenant host can now pin an
  org's chosen voice provider while the model omits it — and with nothing set,
  selection stays free-first (Edge). An explicit per-call `provider=` still wins.
- **`present_file` — hand a finished file to the user as a deliverable.** After
  the agent generates or saves a file (an image, a spoken clip, a rendered PDF, a
  CSV), it *presents* it: the user gets a **downloadable, previewable card** the
  way ChatGPT/Codex surface an artifact, instead of a path buried in prose. Plugs
  into the runtime's existing artifact tracker (it declares the file's `path`),
  previews images inline via the vision bridge, and emits the `MEDIA:<path>` tag a
  send pipeline turns into an inline attachment. Sandbox-guarded (an optional
  `root_dir`); a builtin, so local and hosted agents both get it.

## v1.9.1 — 2026-08-16

Closes the ADK-vs-shipit token gap: the loop no longer restates its plan.

### Fixed

- **Re-announcement damping — the model stops restating the same plan**
  (`runtime_core.py` `step_request`, `prompts/reminders.py`). The last piece of
  the dithering story: a weak model kept announcing *"I will check the evidence
  and classify the urgency…"* across steps instead of acting, each restatement
  another model call (one benchmark: 3× the tokens for the same answer). When a
  step's narration is near-identical to one the model already gave this turn,
  a terse *"you already stated this plan — issue the next tool call or answer,
  don't restate"* line is appended to the end-of-context reminder. Reads only the
  assistant's own narration (no tool payloads), fires **only after** repetition
  is observed (a first honest plan is never discouraged), and never on the last
  step (which already forces the answer). Both loops, via the shared
  `step_request`. With duplicate-call suppression (1.9.0) and blind-call repair
  (1.9.0), this closes the three diagnosed causes of the ADK-vs-shipit token gap.

## v1.9.0 — 2026-08-16

Media generation, a leaner loop, agent rules, and the groundwork for
evidence-gated coding. Nine features, each its own tested change.

### Added

- **Media generation — the agent can make images, speak, and film.** Three new
  tools on one pluggable, availability-gated registry pattern (each backend
  declares a cheap `is_available()`; a tool is hidden unless a backend can run):
  - **`image_generate`** — OpenAI (`gpt-image-1`/`dall-e-3`) + LiteLLM long-tail;
    returned inline through the vision bridge. Extra: `[openai]`/`[litellm]`.
  - **`text_to_speech`** — Edge (free, no key) / OpenAI / ElevenLabs; returns a
    saved path + a `MEDIA:<path>` tag. Extra: `[tts]`.
  - **`video_generate`** — Fal / Replicate; blocks (submit→poll→download) and
    returns an MP4 path + `MEDIA:` tag. Extra: `[video]`.
  - **Model validation** on image + video: a permissive denylist rejects a
    clearly-wrong chat/text model (`gpt-4o`, `claude-*`) before the API call,
    while any plausible generation model (incl. new ones) passes.

- **Advanced file reading** (`shipit_agent/tools/file_extract/`). `read_file`
  now extracts office/web documents to clean Markdown — DOCX, XLSX (one table
  per sheet), PPTX (one section per slide), HTML, CSV/TSV, PDF — instead of
  returning binary soup. Availability-gated per format; `[files]` extra.

- **Agent rules** (`shipit_agent/rules/`). Durable policy at the agent *and*
  tool level — `Agent(rules=[...])`, `.shipit/rules/*.md`, and a tool's own
  `rules` attribute — scoped by path (`paths=["tests/**"]`) or tool
  (`tools=["bash"]`), priority-ordered. The house-style layer that complements
  skills' capability.

- **MCP schema cache + lazy register** (`connect(..., cache=True)`). A warm
  start rebuilds a connector's tools from an on-disk cache **without spawning
  the process**; the subprocess launches only when a tool is first called, so an
  unused connector costs nothing. Config-fingerprinted, atomic writes, TTL, and
  a first-call `ensure_ready` handshake seam.

- **Verification ledger** (`shipit_agent/verify/`) — the groundwork for
  evidence-gated coding. A tiny SQLite ledger where an edit marks the workspace
  dirty and only a matching test/build (exit 0) marks it clean
  (`passed`/`unverified`/`not_applicable`), `detect_verify_commands()` project
  sniffing, and the gate helpers. Ships the standalone library; the verify-on-
  stop loop guard follows as its own PR.

### Fixed

- **The loop stops dithering — duplicate read-only calls are suppressed, not
  re-executed** (`runtime.py`, `async_runtime.py`). A weak model that re-issues
  a read it already ran this turn now gets a terse "reuse the result" note
  instead of a re-run (one benchmark: 10 tool calls where 3 sufficed). Scoped to
  read-only by contract; different arguments always run; both loops.

- **Blind-call repair — a rejected call gets the tool's full signature back**
  (`runtime_core.py`). Under `deferred_tools`, a model that never saw a tool's
  schema and guessed a wrong argument name now gets the compact callable
  signature in the rejection, turning a dead bounce into a self-correcting retry.

## v1.8.1 — 2026-08-16

Human-in-the-loop, made first-class.

### Added

- **`@requires_confirmation` — first-class tool confirmation**
  (`shipit_agent/tools/confirmation.py`). A tool declares for itself that it
  needs a human "yes", with one decorator, wired into the existing permission
  gate and approval queue:

  ```python
  @requires_confirmation("Deletes files permanently.", impact="irreversible")
  class DeleteTool: ...

  @requires_confirmation("Large transfer needs sign-off.",
                         when=lambda a: a["amount"] >= 10_000)
  def wire_transfer(amount, to): ...
  ```

  It goes past a plain yes/no: a **`when(arguments)` predicate** makes it
  conditional (a cheap call runs free, only the dangerous one pauses); **impact
  levels** (`default` / `destructive` / `irreversible`) let a UI colour the
  approval card; it is a **per-tool floor** — `PermissionEngine.check` asks even
  under a bypass/allow mode, and only a hard deny outranks it; and because the
  answer flows through the existing approval machinery, a human can
  **approve-with-edit**. A broken predicate fails safe (asks, never skips).

### Fixed

- **A denied tool is final — the model no longer retries it.** After a human
  declined a tool, the result said only "was NOT run", which the model read as a
  transient failure and retried — re-prompting the human on every loop. The
  denied result now states the decision is final ("do NOT retry, rephrase, or
  pursue the goal another way; silence is not consent"), so the run stops after
  one denial. Applied to both the sync and async runtimes.

---

## v1.8.0 — 2026-08-15

The theme is a first-class, extensible platform: connections, providers,
plugins, and tools each become a clean drop-in directory — one unit per folder —
so adding one is a data edit, not a code change.

### Added

- **Connector catalog — connections as data** (`shipit_agent/connectors/`).
  Every integration is an MCP server described by one declarative
  `catalog/<name>/manifest.yaml`; the registry scans, validates, and
  **skips-invalid-with-a-diagnostic** (a typo never breaks the catalog).
  Ships **28 connectors** across developer, communication, productivity, data,
  business, and automation — GitHub, GitLab, Linear, Jira, Confluence, Sentry,
  Slack, Discord, Intercom, Notion, Asana, ClickUp, Todoist, Google Drive,
  Postgres, SQLite, Brave Search, Fetch, Google Maps, Airtable, Stripe, PayPal,
  Square, Filesystem, Playwright, Puppeteer, Memory, Cloudflare. `connect(name)`
  turns a manifest into a live MCP server, choosing the hosted (HTTP/SSE) or
  stdio transport and wiring the per-user bearer token.
- **Self-refreshing per-user OAuth** (`connectors/oauth_manager.py`).
  `OAuthCredentialManager` resolves the right user's token at call time and
  refreshes it transparently near expiry, recovers from a live 401 with one
  refresh, dedupes concurrent refreshes, and reports
  `connected`/`expired`/`disconnected` per connection for a dashboard.
  **38 provider presets** carry the authorize/token/refresh endpoints, so a
  connector's OAuth is one `register_preset(...)`. `TokenStore` is a small
  pluggable protocol with in-memory and `0600` file-backed implementations.
- **Provider catalog — every model, one profile-per-dir**
  (`shipit_agent/providers/`). Each provider is a `catalog/<name>/profile.yaml`
  (display name, auth env, adapter class, default model, capabilities) plus an
  optional `provider.py` for imperative setup. Ten ship: **openai, anthropic,
  bedrock, gemini, vertex, litellm, groq, together, ollama, shipit/echo**.
  `build_llm_from_settings` now resolves through the catalog first and falls
  back to the inline chain when PyYAML is absent — behaviour is identical, and
  a new provider is a dropped-in directory rather than a code edit. Profiles
  carry `fallback_models` for a coming failover layer.
- **Plugin system — extend the agent without editing it**
  (`shipit_agent/plugins/`). A plugin is a clean `catalog/<name>/` directory: a
  declarative `plugin.yaml` plus a `plugin.py` exporting `register(reg)`, where
  `reg` is a small `PluginRegistrar` the plugin uses to contribute **tools** and
  **lifecycle hooks**. Discovery draws from three sources in increasing
  precedence — **bundled**, a **user directory** (`$SHIPIT_PLUGINS_DIR` or
  `$SHIPIT_HOME/plugins`), and **pip entry points** (`shipit_agent.plugins`,
  opt-in via `SHIPIT_PLUGIN_ENTRY_POINTS=1` since they run installed-package
  code) — user plugins override bundled ones, and each source
  **skips-invalid-with-a-diagnostic**. Hook points map one-to-one onto the
  agent's `AgentHooks` surface, so a plugin hook is a real wired callback.
  `Agent(plugins=[...])` folds each plugin's tools and hooks in at construction.
  Ships two examples: `audit-log` and `word-count`.
- **`check_fn` tool availability gating** (`shipit_agent/tools/availability.py`).
  A tool declaring `requires_command` / `requires_env` / `check_fn` is stripped
  from the advertised set when its dependency is missing — its schema never
  costs tokens and the model never wastes a turn calling it. On by default;
  probes are TTL-cached (30s) with a 60s transient-failure grace.

### Changed

- **MCP servers connect in parallel** at registry build — 20 connectors no
  longer cost 20× the handshake latency. Registration stays ordered (collision
  handling unchanged) and a failing server re-raises exactly as before.

- **`build_llm_from_settings` is catalog-backed** but keeps its exact
  signature, `SUPPORTED_PROVIDERS`, the `bedrock` default, every `SHIPIT_*_MODEL`
  default, and all aliases (`vertex_ai`/`vertexai`, `echo`, `proxy`). Verified
  against a captured baseline: every provider returns the same adapter class and
  default model as before.
- **`s3://` image URLs** are recognised for Bedrock; base64 stays the default
  for every other provider, and images are ordered before text for Gemma.

### Validated live

- End-to-end agent runs (tools + `deferred_tools` + MCP) against **Bedrock
  (gpt-oss-120b), Vertex AI (Gemini 2.5 Flash & Pro), and LiteLLM→Bedrock** —
  reasoning events streaming, prompt caching active, and `deferred_tools`
  cutting turn-1 prompt tokens by **60–70%** with 61 tools held.
- computer_use gains **app control** (`list_apps` / `focus_app`) and a runnable
  Vertex-Gemini notebook example.

---

## v1.7.1 — 2026-08-12

### Added

- **Attachments on `stream()`** — `agent.stream(prompt, images=[...], files=[...])`
  now accepts the same image and file attachments as `agent.run()`, so a
  streaming caller can attach pictures, PDFs, and code/markdown files and
  consume events as they arrive.


---

## v1.7.0 — 2026-08-12

The theme is the working set: schemas for the tools a step can actually use,
cache hits for everything the step repeats, and recovery that waits out the
window instead of burning through it.

### Added

- **`Agent(deferred_tools=...)` — the tool catalogue on demand**
  (`shipit_agent/deferral/`). Tool paging, provider-agnostic:
  core tools keep their full schema in every request; every other tool is
  listed by *name only* in the system prompt until it is loaded. `tool_search`
  now finds **and loads** deferred tools — matches become directly callable
  from the next step, and the search result carries a one-line signature per
  loaded tool so the model can plan the call immediately. Calling a deferred
  tool directly also works (and loads it). `True` defers everything outside
  the core set; a list of names defers exactly those. The selection lives on
  `RuntimeCore`, so the sync and async loops share one behaviour and the
  parity test enrols it automatically. Code mode wins when both are enabled.
- **Backoff between LLM retries** — `RetryPolicy` gains
  `llm_retry_base_delay` / `llm_retry_max_delay` / `llm_retry_jitter`.
  Exponential with up to +25% jitter, in both loops; a 429 retried after half
  a second is a recovery, retried immediately it is two more 429s. The
  `llm_retry` event now reports the chosen delay. Set the base delay to 0 to
  keep the old immediate-retry behaviour.
- **`RetryPolicy(request_timeout=...)`** — per-request LLM timeout, forwarded
  to adapters whose `complete()` accepts a `timeout` kwarg (OpenAI, Anthropic
  and LiteLLM adapters now do; older custom adapters are detected and skipped,
  never broken). Without one, a hung connection hangs the run — `cancel()`
  only takes effect between steps.

### Changed

- **Prompt caching now covers the conversation prefix** on Anthropic-family
  models (native adapter and the LiteLLM path used by Bedrock/Vertex Claude):
  a third `cache_control` breakpoint on the last message means each step's
  request extends the previous one from cache, instead of re-billing the
  growing history as uncached input on every iteration.
- **Failed streaming attempts reset their tool-input parsers** before the
  retry, so a retried completion starts from clean state instead of appending
  fragments onto a dead parse.
- **`decision_llm` narration tokens are now tracked** — narration is a real
  model call; its usage lands in the run totals and `usage_tick` events
  instead of escaping cost accounting.

### Changed (second wave — validated live on Gemma / Bedrock Mantle)

- **Async loop parity, for real**: the async runtime now actually invokes
  compaction and the argument gate (both existed on `RuntimeCore` but were
  never called on the async path — an async run past the window just sent an
  oversized request; an empty structured call just ran). The sync loop's
  nudge-on-stall now uses the shared `RuntimeCore` decision too, retiring a
  stale pre-fix copy.
- **Compaction reuses its checkpoint** instead of writing a brand-new summary
  on every step past the threshold, and the summarizer's own tokens are
  counted in run usage.
- **Narration economy**: `agent_observation` is now always composed from tool
  metadata — free — so narration spends its one completion per step on the
  `agent_decision` line only. (Previously a configured `decision_llm` was
  called twice per iteration.)
- **Two new healed tool-call formats**, both observed live from Gemma 4 on
  Bedrock Mantle: a declared tool name glued to a pseudo-JSON object
  (`tool_search{query: "…"}`, unquoted keys, non-ASCII verb prefixes) and
  Python keyword-call syntax (`weather_lookup(city="Paris")`). Identity is
  the model's own literal tool name; junk-key wreckage still fails the bar.
- **Native `bedrock_mantle/` routing**: `BedrockChatLLM` prefers LiteLLM's
  native Bedrock Mantle provider when a Bedrock API key is present
  (`BEDROCK_MANTLE_API_KEY` — the provider authenticates by Bearer token,
  not SigV4; routing there without a key 401s, verified live). SigV4-only
  environments keep the OpenAI-compatible shim. Accepts
  `bedrock_mantle/<id>`, `bedrock/<id>`, or a bare id.
- **Stream classification**: `final_answer`, `agent_decision`,
  `agent_observation`, `tool_group_*`, `tool_arguments_rejected`,
  `artifact_created` and `skills_selected` are now canonical — a reconnecting
  client no longer silently drops the answer or the record that a call was
  refused. `tool_arguments_rejected` joined the public `EventType`.
- Bedrock-Anthropic pricing entries carry `cache_read`/`cache_write` rates
  (0.1×/1.25× of input), so cached tokens no longer price at $0 there.

### Added (third wave — media, MCP robustness)

- **Attachments**: `agent.run(prompt, images=[...], files=[...])` — images by
  URL/path/base64 (vision models); text/markdown/code files inlined as
  fenced blocks (every provider); PDFs as native document blocks where the
  provider reads PDF. `Agent(media_parser=...)` now actually works (the
  documented example used to raise `TypeError`).
- **`read_file` can see** — PNG/JPG/GIF/WebP return the image itself to the
  model instead of UTF-8 replacement soup; PDFs attach as documents.
- **The vision bridge** — any tool result carrying `image_base64` metadata
  (computer_use screenshots, MCP image results, `read_file`) becomes a
  user-turn image block on the next step, in both loops. Only the newest 3
  images ride each request; older ones become a one-line stub.
- **`Message.content` may be a block list**; `Message.text` extracts prose.
  Eviction, truncation, compaction and context tracking all handle blocks
  (images estimate at a flat ~1,500 tokens).
- **MCP robustness**: exposed tool names are sanitized unconditionally
  (`deepwiki**ask_question` → `deepwiki_ask_question`; the raw name still
  goes on the wire); two servers exposing the same name no longer crash the
  run (the later one is re-exposed as `{server}__{name}`); both subprocess
  transports enforce a per-request timeout (60s default) so a wedged server
  can't hang the run; a crashed-and-respawned server is re-handshaken before
  its next call; the server's `initialize.instructions` now reach the system
  prompt as one `## MCP server:` block, and the boilerplate per-tool MCP
  guidance line is no longer repeated under every tool.

### Added (fourth wave — connections, sub-agents, orchestration)

- **Connection cards** — a connector called with no credential now files a
  connection request and returns an actionable result ("Connect Slack — it
  needs a token"), so the runtime emits its `connection_requested` card and
  the run continues, instead of a dead-end "not connected" string. The
  `/login` parity. All 17 connectors.
- **`orchestrator` role** — a lead agent that plans, delegates independent
  pieces to specialist sub-agents (`sub_agent` + `plan_task` + synthesis
  tools), and combines their reports. `Agent.for_role("orchestrator", ...)`.

### Added (seventh wave — tool depth & plan workflow)

- **bash tool depth** — 600s timeout ceiling (was 120s); an opt-in
  `unrestricted=True` mode that allows redirects, heredocs, pipes-to-file and
  command/process substitution (the safe conservative filter stays the
  default); and a companion `bash_job` tool to poll or kill background jobs
  by id. A rejected command now returns
  an error result instead of raising (a raised tool exception could crash the
  run).
- **`multi_edit`** — a batch of exact-string edits applied to ONE file
  atomically: edits apply in order to an in-memory
  copy and write once; if any fails, nothing is written. Same read-gate,
  mtime staleness, and UTF-8 refusal as `edit_file`.
- **git worktree isolation** — `git_ops` gains `worktree_add` /
  `worktree_remove` / `worktree_list` so an agent can work on an isolated
  branch or worktree, in isolation from the user's working tree.
- **Readability web extraction** — `open_url` now returns structured markdown
  (headings, lists, paragraphs) with nav/header/footer/aside/script dropped,
  instead of flat tag-stripped soup that buried the signal.
- **Compaction re-grounding** — after a fresh compaction the most-recently-read
  files are re-read from disk and injected as current contents, so the model
  works from the code, not a prose summary of it. Restores the read-gate for those files.
- **Plan mode as a workflow** — a `present_plan` tool: in plan mode the agent researches read-only, then submits a
  structured plan (title + ordered steps) that is captured and surfaced for
  approval via the interactive-request channel, instead of plan mode being a
  bare deny-gate.

### Added (sixth wave — long-run trust & polish)

- **Read-before-edit gate is reset at compaction** — fixes a silent
  correctness bug: after a file's contents were summarized out of context,
  `read_files`/`read_file_mtimes` still claimed it was read, so `edit_file`
  allowed a write against contents the model could no longer see. Compaction
  now clears the gate, forcing a cheap re-read before the next edit.
- **Higher default iteration budget** — `Agent.max_iterations` 4 → 12 (16
  with skills). A real multi-step task (read several files, edit, test, fix)
  no longer gets cut to a summary before the context window is the real constraint.
- **Larger `read_file` window** — 250 → 2000 lines, 12K → 80K chars. Less paging, fewer edits against unseen regions.
- **End-of-run summary** — a `run_summary` event (and `run_completed.summary`)
  closes every run with iterations, tool calls, compactions, token usage, and
  an estimated cost. Canonical
  for reconnecting clients. `FunctionTool(read_only=...)` also gained a
  three-state default (`None` = use the name heuristic).

### Added (fifth wave — parallel reads, native structured output)

- **Read-parallelization from tool contracts** — a tool group where every
  call is read-only (grep, glob, file reads, lookups) fans out concurrently;
  any group containing a write/send/mutate stays serial and ordered. This
  both fixes a latent race (two `edit_file`s to one path racing across
  isolated state copies) and delivers fast batched-read execution.
  Shared decision on `RuntimeCore.read_only_calls`, so both loops agree.
  `FunctionTool(read_only=True)` lets a caller declare a pure function
  parallel-safe.
- **Native `response_format` structured output** — when `output_schema` is
  set, the tool-less final/synthesis turn now sends the provider's native
  `response_format` (guarded by `accepts_kwarg`), guaranteeing parseable
  JSON where the provider supports it. Never applied mid-loop (JSON-mode
  would suppress tool calls); the prompt-instruction + validate-with-retry
  path remains the fallback.

### Fixed (sub-agents)

- **The sub-agent's system prompt was the delegator's text.** Every
  general-purpose sub-agent was told *how to delegate* instead of that its
  final message is the whole deliverable. Split into a child-facing
  `SUB_AGENT_SYSTEM_PROMPT` (final-report contract: your final message is all
  the parent sees; don't ask the human; lead with the answer then the
  evidence) and the parent-facing `SUB_AGENT_PROMPT` (now the tool's
  `prompt_instructions`).
- **`agent_type` re-granted tools the parent didn't have.** `for_role`
  re-added the role's full builtin set on top of the inherited subset — a
  read-only child regained `write_file`/`bash`, and 7 roles even regained
  `ask_user_async` (a background child could block on a human nobody was
  watching). The role agent's toolset is now intersected back to the
  inherited set minus the never-inherited human-interaction tools.
- **Sub-agents could hang the parent forever.** `SubAgentTool(timeout=...)`
  bounds every collect; on expiry the future is cancelled and a failed
  result is reported. Added `close()` / `__del__` so the thread pool is
  released (was leaking non-daemon threads that also wedged interpreter
  exit).

### Fixed

- **Eviction no longer corrupts persisted sessions.** With
  `evict_prior_tool_outputs=True` (the default), the evicted stubs were being
  written back to the session store — turn 3 permanently destroyed what turn 1
  retrieved, for replay, audit and every future turn. Eviction is now strictly
  a per-request view: the store always keeps the original transcript. Both
  loops.

---

## v1.6.3 — 2026-08-10

The theme is spending: what a turn is charged for, and what it gets back.

### Added

- **`Agent(reminder=...)` and built-in end-of-context reminders** — a short
  instruction placed after the whole conversation, where a model attends most
  reliably. Three built in, one per phase of a turn, so exactly one applies at
  a time and none of them is boilerplate: before anything has been retrieved
  the risk is invention, once something has it is answering from too little of
  it, and on the last step it is spending that step on a call that cannot run.
  Appended to a per-call copy of the message list, so it is rebuilt each step,
  never stacks, and never enters the saved session.
- **`Agent(evict_prior_tool_outputs=True)`** — earlier turns' tool payloads are
  replaced with a short notice. A message list is cumulative across turns as
  well as within one, so a search that returned fifteen thousand characters in
  turn one was billed again on every request of turn two and three, long after
  the model had written whatever mattered into its answer. The call, its name
  and its arguments stay — those are what stop the model searching for the same
  thing twice, and they are a few tokens against the thousands they replace. No
  message is dropped: a tool result removed while its assistant tool-call
  message remains is a malformed conversation some providers reject outright.
- **`decision_llm` writes the progress narration** — opt-in, and only when the
  primary model produced no prose of its own. A small model spends its whole
  completion on the tool call (14 to 16 tokens, measured on Gemma), so there is
  nothing to prefer and a label built from the tool name is all that was
  honestly available: `agent_decision` read "Asking question
  openai/openai-python." and `agent_observation` read "Asked question
  openai/openai-python." Decision prompts carry the request, the previous
  observation and the pending call — never the conversation, never a tool
  payload. Observations get a 500-character head of each result, because an
  observation that cannot see what came back can only restate the tool's name.
  Roughly 500 tokens for a two-tool turn. Omit `decision_llm` and nothing extra
  is called at all.

### Changed

- **Tool rules moved into the tool section.** The same instruction is followed
  far more reliably next to the tools it governs than a few paragraphs earlier
  under a general heading. The depth rule was the proof: given fifteen search
  hits and a request for detail, the model opened one and answered from it.
  Rules now sit under `# Tools` directly above the listing, with families as
  `##` subheadings, and are emitted only when tools are attached.
- **Tool descriptions are no longer repeated in the prompt.** Every description
  is already in the JSON schema the provider requires, and that copy is the one
  the model selects on. Measured on a 43-tool agent, the second copy was 15,286
  characters — about 3,800 tokens — re-sent on every step of every turn. What
  stays is what the schema has no room for: family, read-only status, origin.
- **The final step is sent without tool schemas.** A tool call emitted there
  has no iteration left to run in, so the run ends with the model having
  announced work instead of doing it. Withholding them forces the answer and
  drops the largest fixed cost in the request from the longest prompt of the
  run. A single-step agent keeps its tools.
- **Both loops share one step-request decision.** The async runtime builds its
  own request and had received none of the above; `RuntimeCore.step_request`
  now returns the messages and schemas for a step and both loops call it. A
  test asserts neither defines its own.

### Fixed

- **A call that asks for everything is not run.** Healing only inspected calls
  written as text; a call arriving through the provider's tool-call field
  skipped it entirely, and a weak model produces wreckage there too — observed
  live as `search_echo({",'query'": ""})`. Keys that clean up to a declared
  parameter are repaired; a call supplying no usable argument to a tool that
  declares it needs one is refused, with a sentence naming what to pass.
  Deliberately not a per-parameter `required` check: a schema's required list
  does not hold for every valid invocation.
- **Tool calls are validated against their own schema.** A name check asks
  "could this be a parameter?"; a schema check asks "is this *the* parameter?"
  — which is what matters when a filter is optional and a missing one means
  "return everything". Nameless argument objects are matched to the tool whose
  schema they satisfy, and list-valued parameters arriving as JSON strings are
  coerced.
- **Invented data is no longer presented as retrieved.** Asked for the latest
  cases, an agent called nothing and returned a table of case IDs, names and
  dates, describing them as retrieved. Every row was invented and both search
  tools were attached. An answer that is merely wrong can be argued with; one
  that claims a retrieval it never performed cannot.
- **A greeting is no longer read as a stall.** "…just let me know" matched the
  "let me" intent marker, so the runtime nudged and the model's apology was
  concatenated into the answer. Fixed structurally rather than by excluding the
  phrase: a stall is a *bare* announcement, so a reply ending in a question or
  saying more than one thing is not one.
- **`FunctionTool` no longer advertises `**kwargs` as a required parameter.**
  It has no default, so it landed in `required` — telling the model to invent a
  value for `**_ignored` and making the declaration useless for validation.
- **The reasoning channel is searched for tool calls** when the model produced
  thinking but no answer and no calls — the shape that means the call was
  written into the thinking, where nothing previously looked.

---

## v1.6.2 — 2026-08-10

### Added

- **`Agent(observability="auto")`** — runs report themselves through
  shipit-watcher with no wiring: traces, the agent graph, scores, datasets
  and the local ledger. Attaching it used to mean building a
  `WatcherExporter`, passing it as `trace_store` and remembering to flush,
  which is the kind of friction that ends with tracing on in one service
  and forgotten in the rest. `"auto"` is safe as the default because
  watcher answers "am I configured?" itself — no credentials means nothing
  is emitted rather than an error, and a missing package falls through. Set
  `True` to force it, `False` to refuse it; an explicit `trace_store` still
  wins.
- **`WatcherExporter`** — the `TraceStore` behind it. Watcher's API is
  context managers and an agent reports events after they finish, so open
  scopes are held per trace and closed on the matching end event. A run
  that dies with a tool still open has its scopes closed anyway.
- **`max_tool_output_group_chars`** (default 48,000) — bounds a whole turn,
  not just one result. The per-result cap let four tools return 100,000
  characters each and pass 64,000 through, every one of them individually
  "under" the limit.

### Changed

- **Progress narration prefers the model's own words.** A model that calls a
  tool usually says why in the same response, and that sentence is better
  than any label composed for it, was already paid for, and improves as the
  model does. Composition is now the fallback for when it says nothing.
- **Observations report what the tool said about itself** — from
  `metadata["summary"]`, and nothing when the tool said nothing. An earlier
  draft read the payload instead, pattern-matching keys like `total` out of
  JSON; only the tool knows whether its total counts results, pages or
  bytes, so that was the runtime inventing a fact and stating it with
  confidence.

### Fixed

- **The narrator no longer conjugates namespaces.** It made a verb of
  whatever came first in a tool name — right for `get_echo`, wrong for
  every `<namespace>_<thing>` an MCP server exposes. `rl_search` narrated
  as "Rling search" and `slack_post_message` as "Slacking post message".
  Leading words are conjugated only when they are verbs; anything else
  reads as "Running rl search", which is honest about not knowing the tool.
- **A repeated tool call is answered once.** Same tool, same arguments,
  byte-identical output — the model is told it already has that result and
  to change the arguments, instead of being handed the same 138,000
  characters a fourth time. The tool still runs and its output is still
  compared, so a changed answer is returned in full.
- **A truncated result says what it dropped.** The extract now reports how
  many characters went and how to ask for them, rather than only that it
  was "shortened".
- The default prompt now says independent tool calls belong in one
  response. Every tool group in a reported run held exactly one call — not
  a runtime limit, the runtime takes a list; the prompt had never mentioned
  it. Turns are what cost, not calls.

---

## v1.6.0 — 2026-08-10

### Changed

- **Progress narration no longer calls a model.** `progress_summaries=True`
  spent one extra LLM call per iteration, and with no `decision_llm`
  configured it spent them on the run's own model — so watching a run
  roughly doubled its model calls and its bill, on the expensive model, to
  produce a paraphrase of data the runtime was already holding. The
  summaries are now composed from the tool calls and their results:
  `Reading guests.csv.` before, `Read guests.csv.` after, and a failure
  named as a failure rather than folded into the sentence. Same events,
  same payloads, no second model, no added latency.
- `decision_llm` is still accepted so existing callers keep working, and is
  no longer used for anything. The dead prompt-building helpers it needed
  (`_call_progress_model`, `_recent_public_context`, `_bounded_text`) are
  gone.

### Fixed

- **`shipit chat` was two model generations behind the rest of the CLI.**
  It kept its own provider→model table, so `--provider anthropic` gave
  `claude-3-5-sonnet-latest` in the REPL and `claude-sonnet-5` everywhere
  else — same CLI, same flag, different model, with nothing on screen to
  say which you had. OpenAI was still on `gpt-4o-mini`. The curated catalog
  is now the single source of truth wherever it has an opinion, and a test
  pins the two together. Providers the catalog does not cover keep their
  own defaults rather than being blanked.
- **`shipit doctor` prints a report instead of a dataclass.** It printed
  `DoctorReport(checks=[DoctorCheck(name=…` — one 2,000-character line you
  had to read like a stack trace, for a command whose entire purpose is to
  be scanned. Failures and warnings now come first and carry their details;
  passing checks are one line. `--json` for the full structure, and a
  failing check is a non-zero exit in both — so `shipit doctor && deploy`
  stops at a broken agent, and a script piping `--json` to `jq` cannot see
  success where the terminal showed a failure.
- **A wrong API key says so.** Any uncaught error from a command printed a
  traceback, so the usual first-run failure — bad or missing credentials —
  arrived as thirty frames of the provider SDK with a 401 at the bottom.
  The message is now summarised, credential failures name
  `shipit doctor --provider <name>` as the way to find the variable, and
  `SHIPIT_DEBUG=1` still prints the traceback in full. Ctrl-C exits 130
  rather than reporting itself as a crash.

---

## v1.5.1 — 2026-08-08

### Added

- **Guides for three features that shipped without them.** Triggers,
  delegation, and agents as tools each had public API and no page
  explaining when to reach for it.
- **`SqliteTriggerQueue`, `InMemoryTriggerQueue`, `fire_all`,
  `DelegationPolicy` and `DelegationAdvice` are exported from the package
  root.** Found by checking that every import in the new guides resolves:
  `TriggerRegistry` was exported without the queue you configure it with,
  so the durable setup — the default anybody running this in production
  wants — could not be written from the top-level import at all. A test
  now pins the surface the documentation uses.

---

## v1.5.0 — 2026-08-08

### Added

- **`AgentTool` — an agent as a tool.** Wrap any agent and hand it to
  another as one focused callable, so a researcher, a reviewer and a
  writer become tools a coordinating agent picks between by description.
  Unlike `sub_agent`, which builds a child from the parent, this delegates
  to an agent you configured yourself — its own model, its own tools, its
  own session if you give it one. Nested events surface through the
  parent's stream, so a delegated run is visible rather than a silence.

### Fixed

- **A failing child no longer ends the parent's turn.** `AgentTool` let a
  child's exception propagate, so one provider being down took the whole
  run with it. Every other tool reports failure as a result the model can
  act on; this one does now too, and the parent can say so, try something
  else, or answer without it.
- **Delegation cannot recurse forever.** An agent holding a tool that
  wraps an agent holding the same tool would recurse until something ran
  out. `sub_agent` already capped this; `AgentTool` is the same hazard by
  another name, so it shares the counter rather than keeping its own — and
  the refusal says to do the task directly, because a cap that does not
  name the alternative just gets retried.
- **A child that returns nothing is no longer reported as success.**

---

## v1.4.0 — 2026-08-08

Scheduled jobs stop sharing one agent, skills come from the project, and
tool output streams while it is produced.

### Added

- **Per-job agent configuration.** Every scheduled job carried the same
  process-wide agent, so "summarise the inbox hourly on a cheap model" and
  "audit the repo nightly on a good one" could not coexist. A job now
  persists its own provider, model, role, project root, runtime mode,
  permission mode, guardrails, MCPs, connections, skills and iteration cap
  — `ScheduledAgentConfig`, resolved per job by `ScheduledAgentFactory`.
  The SQLite store migrates itself: existing databases gain the new
  columns on open, and a job written by an older version still runs.
- **Project skills.** `discover_project_skills` and `load_markdown_skill`
  read skills from the repository the agent is working in, so a team's
  conventions live beside the code they describe rather than in a
  configuration screen.
- **Streaming tool output.** `ToolOutputChunk` and `ToolRunOutput` let a
  long-running tool report as it goes instead of arriving whole at the
  end.
- **Concurrent web search.** `web_search` accepts `queries` as well as
  `query` and runs them in parallel. Either, never both — an empty call
  answers with which of the two to pass.

### Fixed

- **A permanently broken scheduled job now pauses.** Failures were counted
  and nothing acted on the count, so a job whose provider was gone ran
  every interval for as long as the daemon lived, burning quota and
  filling the log with one repeated line. Paused after five consecutive
  failures — paused rather than deleted, because the configuration is
  intact and `jobs resume` is one command. Resuming clears the count, so a
  job somebody fixed is not paused again by the history that paused it.
  `max_consecutive_failures=0` switches the behaviour off.

---

## v1.3.3 — 2026-08-07

### Added

- **Breadth as a structural signal.** "Go through every document attached"
  names no number and no filename, so counting lists, targets and quantities
  missed it — and 1.3.2's corroboration floor would then have declined it.
  A distributive determiner over a noun ("every document", "each of our
  repos", "all the open PRs") now counts. It is grammar rather than
  vocabulary, so it holds for wording nobody anticipated, and it reports no
  count: breadth says "more than one", not how many, and inventing a number
  would feed a fake quantity to the `min_items` filter. An adverbial "all"
  — "is it all good", "tell me all about it" — is not breadth.

---

## v1.3.2 — 2026-08-07

### Fixed

- **A model may no longer invent a decomposition.** Asked "Can you look for
  the latest AI news?", Gemma 4 answered `decompose: true, items: 3, "news
  can be split by topic or source"` — three sub-agents for one web search,
  and not one of those topics appears in the request. The assessor was
  asking "could this be split?", and almost anything could. It now counts
  only the pieces the task itself names, is told plainly that a single
  search or a single read is one call, and a model's yes must be
  corroborated by something actually in the text. The structural floor
  already raised a model that undercounted; it now also declines one that
  overcounted. The count it saw is still reported — overruled, not erased.

---

## v1.3.1 — 2026-08-07

### Fixed

- **`delegation=` no longer attaches `sub_agent` on every turn.** Asked
  "look for the latest AI news", an agent with automatic delegation on
  spawned three research sub-agents instead of running one web search. The
  tool was attached unconditionally on the reasoning that a model deciding
  mid-run to delegate must find it there; measured against a smaller model,
  that reasoning fails — a tool on the table gets used, and given a choice
  between a search and a research crew it takes the crew. The policy already
  judges each task for the directive, and the toolbox now follows the same
  judgement. An explicitly passed `SubAgentTool` is untouched.
- **`sub_agent` refuses a task with no substance in it.** Observed:
  `sub_agent(task=",")`, which the tool accepted, spending a model call to
  return an error. A child sees nothing of the parent's conversation, so the
  task is its entire brief. The refusal names the alternative, because one
  that does not just gets retried.
- **Background delegation says there is no "later".** The tool and the
  directive now state that anything started with `background=true` must be
  collected in the same turn — a run ends with its answer, and an
  uncollected task is discarded. Without this, models announced background
  work and promised to report back on results that were never coming.
- A dashboard blueprint f-string that only parsed on Python 3.12+.

---

## v1.3.0 — 2026-08-06

An agent you have to ask is a tool. An agent that reacts is a colleague.
This release is the second half: **triggers** — something happens, and the
agent runs.

### Added

- **`shipit_agent.triggers`** — a trigger registry, a durable queue, and a
  worker loop.
  - `registry.on("gmail")` decorates a function that turns an event into a
    prompt. A trigger builds a *prompt*, not an agent: the run stays on the
    agent you already configured, with your credentials, permissions and
    budget, rather than a second agent nobody is watching.
  - `registry.fire(source, data)` **records and returns**. It runs nothing.
    A webhook must answer in milliseconds and an agent takes seconds; a
    sender that times out delivers the same email again.
  - `registry.drain(agent)` runs what is queued and reports each run.
  - `registry.run_forever(agent, stop=…)` is the worker, stoppable.
- **`SqliteTriggerQueue`** — the default, and durable on purpose. An event
  that arrives while nothing is running must still be there afterwards, or
  "runs on every email" is a claim that fails quietly at 3am. Claiming takes
  the row, so two workers can drain one queue; an abandoned claim expires
  rather than stranding the event.
- **Poison-event handling** — an event that fails `max_attempts` times stops,
  instead of hiding everything queued behind it.
- **`fire_all()`** for batches, and `registry.summary()` for "what is wired,
  what is waiting" — the data behind a Live badge.

### Notes

A handler returning `None` is how a trigger filters: only RSVPs, only
failures. That is a skip, not an error, and it still consumes the event.

`InMemoryTriggerQueue` is named the way it is to be hard to reach for by
accident — it is for tests.

---

## v1.2.0 — 2026-08-06

One question, asked of every surface: **can you see what the agent did?**
A run now reports itself well enough to draw a product from — and, where the
agent used to answer and forget, it can leave something behind.

### Added

#### Watching a run

- **The tree view** — the *shape* of a run instead of its prose: every call
  named with its status, the opening intent labelled "Understanding request",
  each later paragraph a "Decision", the last one the "Final answer". On a
  terminal it redraws in place while the run proceeds, keeping the trunk open
  (`├─ working…`) until it ends, then erases the draft and writes one clean
  tree. `agent.run_live(style="tree")`, `render_tree(events, detail=True)`.
- **The live panel** — an HTML chat card that redraws in a Jupyter cell as the
  agent works: tokens land with a caret, tool rows appear in flight and
  settle, real output folds away behind each call, cards interrupt the flow,
  and the footer counts tokens. `watch(agent, prompt)`, `shape="tree"` for the
  tree, `render_chat_html(events)` for a finished run. Every selector is
  scoped so the styles cannot leak into the page around it, and redraws are
  throttled — a full re-render per token is O(n²) DOM churn that stutters
  exactly when the answer gets long.
- **The UI timeline** — the runtime's events translated into what a frontend
  draws: `reasoning_summary`, `tool_group_started`, `tool_call_started`,
  `tool_call_completed`, `agent_decision`, `artifact_created`,
  `final_response`. Plain JSON, and causal — a group's settled title arrives
  in its `completed` step, so a client never has to undraw a row.
  `stream_timeline(agent, prompt)`; `render_markdown(events)` prints the same
  run as a report.
- **Progress narration** — `Agent(progress_summaries=True, decision_llm=…)`.
  A second, cheap model says what the agent is doing while it does it. It
  never reads the system prompt or `reasoning_content` and is called with
  `tools=[]`, so what it reports is what an observer could have watched
  happen; a failure emits `progress_summary_failed` and the run continues.
  Off by default: it adds a real LLM call per step.
- **Tool groups** — one per iteration, carried on `tool_called` /
  `tool_completed` as `group_id`, so a UI can draw one expandable box per turn
  (`2 tools · 13.0ms`) however much narration lands between the calls.
- **`final_answer`** — the answer as its own event, just before
  `run_completed`, so a client does not have to infer which event carries it.

#### Leaving something behind

- **Apps** — `list_blueprints`, `create_app`, `set_app_binding`, `use_app`,
  shipped as builtins under `<project>/.shipit/apps`. The agent writes a
  program into the workspace, wires resources into it, and runs it — today,
  and next week, with no model in the loop. An app is a directory with
  `app.py` exporting `run(input, env)`; it runs in a subprocess with no
  credentials, and its `env` crosses the same capability bridge code mode
  uses, so every resource call is gated exactly as the equivalent tool call
  would be. An app sees only the bindings its manifest names.
- **Six blueprints** — `report`, `csv_summary`, `page`, and three that produce
  something worth looking at: `dashboard` (headline cards and a bar chart),
  `sheet` (column letters, row numbers, flagged cells) and `workflow` (a
  pipeline as boxes and connectors). All self-contained — no CDN, no fonts, no
  script tags — because an artifact that needs the network is not one you can
  send anyone.
- **Artifact cards** — a file a run produced is a card, not a path in a log:
  `Q2 Kickoff Brief · Doc · Click to open`, in the panel, the tree and the
  timeline. Any tool that declares a path in its result metadata gets one.

#### Reaching further

- **Automatic delegation** — `Agent(delegation=True)`. The `sub_agent` tool is
  guaranteed to exist, built from the agent's own LLM and its read-only tools;
  the task is sized by a model (`ModelAssessor`, one cheap cached call) with a
  structural count as the fallback and the floor; and the directive is
  appended to the *task*, not the system prompt — measured against Gemma 4,
  that difference is 0 delegations versus 6. It never delegates behind the
  model's back.
- **Connection requests** — the registry knew what was connected; nothing
  turned "I need Slack" into something a user could answer. The agent's
  request now emits `connection_requested` from both loops, the panel draws a
  card with the reason, and `registry.resolve(id, accepted=…, credential=…)`
  closes the loop — on accept the credential is stored, so the next state
  check reads CONNECTED rather than asking again.

### Fixed

- The async runtime's `tool_completed` was missing `tool` and `call_id`, so
  its transcript could only guess which outcome belonged to which call.
- `read_file` produced artifact cards for files it merely read.
- An artifact card split the tool group that made it.
- `run_live()` raises on an unknown `style` instead of silently rendering the
  default view.
- `write_transcript()` accepted `title` and `model` but dropped `prompt`.
- `use_app` wrote a file and never declared it, so the run produced a page and
  the transcript showed a JSON blob.
- Apps ran in their own install directory, so an app given
  `path="guests.csv"` found nothing. `AppStore.run()` runs them where the
  agent works.
- `deny=["*"]` denying allow-listed tools is now documented where you meet it,
  with the correct pattern (`allow=[…], default_decision=DENY`) beside it.

### Notes

- `progress_summaries` and `delegation` are both **off by default**. Each adds
  real LLM calls, and a runtime that doubles your bill on upgrade is not one
  you can trust.
- Two live notebooks ship with their outputs committed, run against
  `bedrock-mantle/google.gemma-4-26b-a4b`:
  `74_live_streaming_gemma.ipynb`, `75_live_ui_and_subagents.ipynb` and
  `76_apps_and_analysis.ipynb`.
- Still open, and named rather than hidden: the async runtime has no progress
  narration and no tool groups, and `Agent.decision_llm` sits second in the
  field order, so `Agent(llm, "prompt")` positionally assigns the prompt to
  it. Both are tracked in `docs/design/cloudflare-os-gap.md`.

---

## v1.1.0 — 2026-08-06

A single release focused on one question: what does an agent *look like* while
it works, and what should it be allowed to do while you are not watching?
Studied against Cloudflare OS (open source) and adapted rather than copied —
the design notes, including what was deliberately not ported and why, are in
`docs/design/modern-agent-upgrade.md`.

### Added

- **The Narrator** — a transcript instead of a log. Every tool call renders as
  a human verb and target (`Read app.py`, `Ran code const risk = scoreAcc…`),
  consecutive calls with no prose between them collapse into one row, and the
  run closes with tokens and cost. Present tense in flight, past tense once it
  lands; in-place on a TTY, byte-stable when piped. `agent.run_live(style=
  "modern")`, `shipit code --style`, `/style` in the REPL. The 50-tool verb
  table is a set of defaults — `register_verb()` overrides any of it, and
  unknown MCP tools narrate through real English morphology rather than
  crashing on an exhaustive match.
- **Tool contracts** — every one of the 51 built-ins now declares what it *is*
  (`read_only`, `action_kind`, `implements_revert`, `await_decision`,
  `auto_approvable`, `destructive`) instead of being guessed from its name.
  Before this, exactly one tool declared `read_only`.
- **Deferred approvals** — a side-effecting call the policy marks `ask` is
  queued rather than blocked on, so the agent finishes and you review the
  batch. Auto-approval rules key on a stable `action_kind` tag, applied in
  order, never past a manual gate, and requiring both the contract's verdict
  and your enabled rule. `shipit code --defer-approvals`.
- **Lockdown** — once a tool reports it returned sensitive data, the run may
  only make observations; every action is denied for the rest of it. Closes a
  real hole: nothing previously stopped an agent reading your customer list
  and posting it to Slack in the same turn.
- **Code mode** — `Agent(code_mode=True)` collapses connectors into an `env`
  of bindings reachable from one `execute_code` call, with `describe_binding`
  for on-demand discovery. Measured on the real catalogue: 25,932 → 11,174
  tokens per model call, **57% smaller**. `env` reaches the parent over a
  capability bridge — the code runs in a subprocess holding a socket, not
  credentials, and every binding call is gated exactly as the direct tool call
  would be.
- **Connections** — `connections` lists what is connected, what needs
  authenticating and what is missing, with per-auth-kind guidance, and lets
  the agent *request* one with a reason instead of failing mid-task.
- **Streaming, three ways** — `agent.stream()` (raw events),
  `agent.narrate()` (settled transcript rows, so a custom UI need not
  reimplement the collapsing), and `agent.stream_sse()` (wire-ready). Frames
  are labelled canonical or provisional and carry a per-process
  `stream_generation`, so a browser that reconnects knows what to keep and
  what to discard. New `POST /v1/stream` on the server; `/health` reports the
  generation.
- **Checkpoint compaction** — per-model token budgets, cuts at a turn (or
  step) boundary rather than a fixed message count, a six-heading handoff
  summary, and an explicit instruction not to follow instructions inside the
  transcript being summarized. Canonical history is preserved; only the replay
  window moves.
- **`give_up`** — a real tool with a required reason, surfaced as
  `result.metadata["gave_up"]`, replacing inference from prose.
- **Streaming tool arguments** — a file or command appears as the model writes
  it. Supported on all 13 shipped adapters (Anthropic, OpenAI, Bedrock,
  Gemini, Vertex, Groq, Together, Ollama, LiteLLM and its proxy); adapters
  without it degrade to arguments arriving whole.
- **Revert** — `queue.revert(id)` for filesystem writes, snapshot-based.
- **Shareable transcripts** — `--share run.html` writes one self-contained
  file: no network requests, no build step, light and dark.

### Changed

- **`sub_agent` is now an actual sub-agent.** It previously called
  `llm.complete()` once with `messages=[]` and `tools=[]` — no loop, no tools.
  It now runs a real `Agent` with an inherited toolset, supports
  `agent_type` from the built-in role registry, runs in parallel via
  `background`/`collect`, and streams its work into the parent's transcript.
  A sub-agent can never do more than its parent: permissions, approvals and
  guardrails are inherited verbatim, and delegation is depth-capped.
- **One runtime core.** `runtime.py` and `async_runtime.py` had drifted to the
  point that ten capabilities existed only in the sync loop. The shared
  decisions now live in `runtime_core.py` and both inherit them; a parity
  suite asserts neither may override or reimplement one.
- A missing tool argument is now a result the model can act on rather than a
  `KeyError` — it names the argument and lists what the tool requires.

### Fixed

- `tool_denied` carried neither `tool` nor `call_id`, in **both** runtimes, so
  a blocked call was invisible to any renderer.
- `sub_agent`'s `context` parameter was silently dropped: `ToolRunner` strips
  `context` and `self` as reserved names, so supporting context never arrived.
  Renamed to `details`.
- `EventType` had drifted — `tool_denied` and `text_delta` were emitted but
  undeclared.
- `get_model_limits` split on `.` to strip vendor prefixes, turning
  `gemini-2.5-pro` into `5-pro`.
- An explicit `context_window_tokens` had an output reservation subtracted
  from it, so a value of 100 produced a budget of 1.
- 18 contracts promised `implements_revert` with zero implementations behind
  it. Now 7 promise it, all backed by a reverter, enforced by a test.

---

## v1.0.18 — 2026-07-31

### Added

- **The `shipit` CLI, rebuilt as a modern package** — `shipit code` (coding
  agent rooted in your repo: playbook prompt, --plan/--yes modes, y/n/always
  prompts), `shipit serve` (AgentServer: the agent as an OpenAI-compatible
  API with SSE streaming + Bearer auth), `shipit run --role/--guardrails`,
  and catalogs (`roles | models | mcp | tools`) with a curated latest-model
  list (claude-opus-5/sonnet-5, gpt-5.6/5.5, Gemma 4, gpt-oss). Stdlib UI
  kit: named palette, NO_COLOR/FORCE_COLOR, encoding-safe banners.
- **Guardrails engine** — four gates (prompt-injection input blocking,
  secret/PII output redaction, tool-argument deny rules, indirect-injection
  sanitization of tool outputs) + max_tool_calls ceiling, strict()/
  standard() presets, optional fail-open LLM judge; guardrail_triggered
  events; Agent(guardrails=...).
- **Self-healing tool calls** — text-emitted calls (<tool_call> tags, fenced
  JSON, bare call-shaped JSON) promoted to structured executions:
  declared-tools-only, span-exact removal, response-side only; plus
  nudge-on-stall (one capped re-prompt on intent-without-action).
- **New builtin tools** — `git_ops` (structured git, fixed argv, push/reset
  gated off), `notebook_edit` (structural .ipynb editing), `deep_research`
  (multi-angle sweep → deduped sources → citation-ready digest).
- **RAG chunk-overlap budgeting** — carried overlap is capped by the room
  remaining under the chunk target so near-full chunks never overflow the
  embedder window.
- Notebooks 72 (guardrails + deep research, live Bedrock) and 73 (CLI +
  power tools), docs guide `guides/shipit-cli.md`, README CLI section.
- **Human-in-the-loop everywhere** — `console_permission_prompt()`: one
  reusable [y]/[n]/[a]lways approval callback for any agent; powers
  `shipit chat` and `shipit code`; shareable always-allowed set,
  injectable I/O, EOF→deny.
- **Bottom-pinned chat TUI** — `BottomInputTerminal` (VT100 scroll
  regions, stdlib): chat scrolls, input never moves; auto-on for real
  TTYs in `shipit chat`, transparent plain fallback elsewhere.
- **`shipit browse`** — computer use from the CLI: vision loop streamed
  as live cards, `--show` visible window, consent persistence.
- **`--mcp` flag + official Playwright MCP** — attach catalog servers to
  `run`/`code`/`serve`/`doctor` from the command line; the new
  `playwright` entry gives any tool-calling model accessibility-tree
  browser control.
- **RAG + Agent example** (24) — RRF-fused hybrid retrieval with
  [document-id] citations, fully offline.

---

## v1.0.17 — 2026-07-17

**Observability + live browsing.** Langfuse support for BOTH server
generations, a downloadable-files tool, a fully observable and watchable
computer-use loop, and a security hardening pass.
**2006 tests passing (+37 new). 0 regressions.**

### Added

- **`LangfuseExporter`** (`shipit_agent.tracing_exporters`) — ship whole agent
  runs to Langfuse as a root trace + one child span per tool call (real
  durations, inputs/outputs, error status). Speaks **both** server
  generations with zero SDK dependency: v3 via native OTLP
  (`/api/public/otel/v1/traces`), v2 via the classic batch API
  (`/api/public/ingestion`); `api_version="auto"` probes
  `/api/public/health` and picks the wire format. Works with every adapter —
  including Gemma-4-on-mantle calls that bypass litellm callbacks. Transport
  failures never break the run. (For LLM-call analytics via litellm: use
  `litellm.callbacks=["langfuse_otel"]` against v3 servers — the classic
  `"langfuse"` callback is v2-SDK-shaped and 500s on v3.)
- **`download_file` builtin** — binary-safe URL downloads (zip/csv/image/pdf):
  64KB streaming with a hard size cap (partials removed on abort), reuses
  open_url's SSRF/scheme guard, Content-Disposition filenames, no silent
  overwrites, absolute path returned in metadata.
- **`ComputerUseAgent.stream()`** — the screenshot→reason→act loop is now
  observable: standard events (`tool_called`/`tool_completed`/`tool_failed`
  as `browser.<action>` with `call_id` + `duration_ms`) render as live tool
  cards via `StreamRenderer`; `run()` unchanged.
- **Watchable, reliable live browsing** — `slow_mo=` (see the mouse move),
  `settle_ms=500` (screenshots taken AFTER the page reacts, not
  mid-animation), `device_scale_factor=1` (exact coordinate mapping on
  Retina), typed keystrokes with `delay=40`; `storage_state=` /
  `save_storage_state()` persist accepted consent across runs.
- **Obstacle-autonomous computer use** — system prompt now instructs the
  model to dismiss cookie/consent walls ("Accept all"), close popups, skip
  sign-ins, route around CAPTCHAs, and verify field focus before typing.

### Fixed

- **Quoted action args** — models emitting `ACTION: navigate "https://…"`
  produced literal quote characters that Playwright rejects ("Cannot
  navigate to invalid URL"); quotes (and a `url=` prefix) are now stripped
  in both the text and Anthropic tool_use parsers.
- **Security** — `research_brief` now enforces http/https before fetching
  (URLs come from model-influenced search results; `file:///` blocked);
  `AdaptiveAgent.create_tool` now honors `can_create_tools=False`
  (previously ignored) and documents its trusted-developer-code-only
  contract. GitHub CodeQL/Dependabot: 0 open; pip-audit clean on all
  shipit-relevant packages.

---

## v1.0.16 — 2026-07-10

**The live experience — streaming, cancellation, and professional-grade
ergonomics.** Real token streaming everywhere, one-call live runs with rich
tool cards, safe stops, stale-proof edits, model-written compaction, and a
sharper CLI. Works with **any** LLM provider. **1969 tests passing (+13 new).
0 regressions.**

### Token streaming, everywhere

- **`OpenAIChatLLM` streams for real** (was a silent TODO): tokens hit the
  callback as generated, tool-call fragments stitched by index, usage captured
  from the final chunk; gateways that ignore `stream=True` degrade gracefully.
  Lights up **Gemma 4 on Bedrock mantle**, Groq, and every OpenAI-compatible
  endpoint.
- **`AnthropicChatLLM` streams** via the SDK's `messages.stream` helper — all
  existing parsing (thinking blocks, tool use, server tools, citations)
  unchanged.

### The live experience

- **`Agent.run_live(prompt)`** — tokens print as generated, tool calls render
  as cards with args/status/duration, a `✔ done` footer closes the run;
  returns the final answer text.
- **`StreamRenderer`** — the underlying renderer for custom loops;
  `style="rich"` (automatic on TTYs) draws rich **⏺/⎿ cards with
  ANSI colors**; prints the answer at the end for non-streaming adapters.
- **`agent.cancel()`** — thread-safe ESC: stops at the next checkpoint, emits
  `run_cancelled`, returns normally with `metadata["cancelled"]`; skipped
  batch tools get synthetic results so message pairing stays valid.

### Reliability

- **Edit hardening** — `edit_file` blocks when the file changed on disk after
  the last `read_file` (external modification → re-read hint) and returns a
  compact **unified diff** with every patch (`metadata["diff"]`).
- **LLM-powered compaction** — near the context window, old turns are
  **summarized by the model** (decisions, facts, paths, open threads; ~300
  words) with a mechanical fallback; the `context_compacted` event now fires
  reliably.

### CLI

- Live `StreamRenderer` turns (real tokens + cards; spinner retired), inline
  **[y]es / [n]o / [a]lways** prompts for `ask`-gated tools (session-persistent
  always-allows), and `--continue` to resume the most recent session
  (`~/.shipit/sessions`). Fixed a `--session-dir` crash.

### Examples & notebooks

- `examples/23_bedrock_model_switching.py` — Gemma 4 26B ↔ gpt-oss-120B, one
  function, live-verified.
- `notebooks/71_full_test_drive.ipynb` — 13 in-depth sections exercising every
  capability, executed end-to-end (live Bedrock cells + offline).

---

## v1.0.15 — 2026-07-10

**The Super Agent — every sector, clean logs, real deliverables.** One release
that makes a shipit agent useful to a finance analyst, a marketer, an engineer,
a designer, a researcher, and a sales rep alike — and makes every run readable.
All of it works with **any** LLM provider.

### Sector specialists — `Agent.for_role`

- **One line to a specialist** — `Agent.for_role("finance-analyst", llm=llm)`
  turns any of the 40+ prebuilt role definitions (finance, marketing,
  engineering, design, research, sales, support, HR, …) into a runnable agent:
  the role's prompt, its matching builtin tools, and its iteration budget.
- **Did-you-mean errors** — unknown ids raise a `ValueError` listing the
  closest matching roles.
- **Deliverable-ready roles** — 14 specialists (finance-analyst,
  marketing-writer, researcher, data-analyst, sales roles, …) now carry the new
  `build_document` tool.

### Prebuilt MCP catalog — `connect_mcp`

- **12 well-known servers by name** — `connect_mcp("github")`,
  `connect_mcp("filesystem", args=["/repo"])`, `connect_mcp("postgres",
  args=[url])`, plus slack, sqlite, puppeteer, brave-search, fetch, memory,
  sentry, gitlab, and google-maps — each on a persistent stdio transport.
- **Fail-fast validation** — required env vars and the launcher binary
  (`npx`/`uvx`) are checked before anything starts; misconfiguration is one
  clear message.
- **Resilient MCP calls** — a failing MCP tool call (server down, timeout) now
  returns a readable tool result the model can react to instead of crashing
  the run. `MCPStdioTransport` / `PersistentMCPSession` aliases are exported.

### Polished documents — `build_document`

- **Five formats** — PDF reports, Excel workbooks, Word documents, PowerPoint
  decks, and styled HTML from one structured payload (`title` + `sections`,
  or `sheets` for Excel).
- **Finished, not generated** — accent-colored headings, zebra-striped tables,
  bold frozen header rows, auto-sized columns; Excel cells starting with `=`
  become live formulas.
- **Optional dependencies** — renderers use `reportlab` / `openpyxl` /
  `python-docx` / `python-pptx` and reply with the exact `pip install` fix
  when one is missing; HTML needs nothing.

### Clean tool-call logs — `format_activity`

- **rich tool cards** — `format_activity(result)` renders each
  call as `⚙ name(args) ✓ 228ms` with a compact output preview and a run
  summary footer; `format_event_line(event)` does the same live for streams.
- **Timing built in** — every `AgentEvent` now carries a `timestamp`;
  `tool_completed` / `tool_failed` carry the tool name and `duration_ms`.

### Scheduled jobs — `AgentScheduler`

- **Cron for agents** — `sched.add(prompt, every=3600)`, `at="09:00"` daily,
  or `cron="0 8 * * 1"` (optional `croniter`); `run_forever()` fires jobs as
  they come due.
- **Durable jobs** — pass `store=SQLiteJobStore()` and due times + run counts
  persist across restarts; a re-added job resumes its slot instead of
  resetting.
- **Production niceties** — `on_result` callbacks, `max_runs` caps,
  session-backed runs, and injectable `clock`/`sleep` so schedules are
  unit-testable with zero real waiting.

### MCP, deeper — resources, prompts, streamable HTTP

- **Resources & prompts** — `server.list_resources()` / `read_resource(uri)`
  and `list_prompts()` / `get_prompt(name, args)`; `server.resource_tool()`
  gives the *model* a tool to browse/read a server's resources. Servers that
  don't implement them return empty lists, not errors.
- **Streamable HTTP transport** — `MCPStreamableHTTPTransport` speaks the
  2025 spec revision: JSON *and* SSE responses, `Mcp-Session-Id` affinity,
  and `bearer_token=` on both HTTP transports for OAuth-protected servers.

### Run metrics & live-updatable events

- **`result.summary()`** — wall-clock duration, iterations, token usage, and
  a per-tool breakdown (calls / failures / total ms) in one dict.
- **Correlation ids** — `tool_called` / `tool_completed` / `tool_failed` /
  `tool_retry` share a `call_id`, so live UIs can update one tool card in
  place (running → ✓/✗) instead of appending lines.

### Background subagents & context compaction

- **Parallel delegation** — `sub_agent` accepts `background=true` (returns a
  task id immediately, runs on a thread pool) and `collect="task-N"` to fetch
  the result — background task fan-out.
- **Observable compaction** — when a run approaches the context window, older
  turns are summarized (user/assistant content included, not dropped) and a
  `context_compacted` event reports before/after message counts.

See the [Super agent guide](agent/index.md) for the full tour.

---

## v1.0.14 — 2026-06-13

**The SHIPIT Workspace.** Point an agent at a repo and it just works. All opt-in, backward compatible. **1884 tests passing (+30 new). 0 regressions.**

### Added

- **Project memory** — agents auto-load `SHIPIT.md` / `AGENTS.md` / `.shipit/SHIPIT.md` (+ user-global `~/.shipit/SHIPIT.md`) into the system prompt, with `@path` imports. Opt out via `auto_project_memory=False`. API: `load_project_memory()`.
- **Slash commands** — `.shipit/commands/<name>.md` invoked with `agent.run("/<name> args")`; `$ARGUMENTS` / `$1` substitution + frontmatter stripping. API: `discover_commands()`, `expand_command()`.
- **Declarative config** — `.shipit/settings.json` (permissions + env + model) merged under `~/.shipit/settings.json`; wires into the permission engine. API: `load_settings()`, `WorkspaceSettings`. **`Agent.for_project(llm=…, project_root=…)`** loads settings + builtins + memory + commands in one call.
- **`TodoTool`** — live task tracking (the model maintains a `pending → in_progress → completed` checklist; in `Agent.with_builtins()`).
- Notebooks `67`/`68` + docs pages.

## v1.0.13 — 2026-06-07

**Computer-use + adapter fixes.** Two bugs that blocked the computer-use agent on every provider, both backward compatible. **1854 tests passing (+10 new). 0 regressions.**

### Fixed

- **Computer-use works in Jupyter / asyncio.** `PlaywrightBrowserSession` used the sync Playwright API, which can't run inside a notebook's running asyncio loop. It now runs all Playwright calls on a dedicated loop-free worker thread (same synchronous API).
- **All LLM adapters accept dict messages** — fixes `'dict' object has no attribute 'role'`. `ComputerUseAgent` passes raw `{"role","content"}` dicts (sometimes multimodal); the LiteLLM family (Bedrock/Gemini/Vertex/Groq/Together/Ollama) + OpenAI now serialize dicts and translate the Anthropic image block to a portable `image_url`; Anthropic + ShipitLLM coerce dicts via a shared `coerce_message()` helper.

## v1.0.12 — 2026-06-07

**Claude API power + cross-provider caching.** Server-side tools, citations, the Batch API, interleaved thinking & context editing — plus **prompt caching that works across providers, not just Anthropic**. All opt-in, backward compatible. **1844 tests passing. 0 regressions.**

### Added — cross-provider prompt caching

- Caching is no longer Anthropic-only. The **OpenAI** adapter now surfaces `usage["cache_read_input_tokens"]` from OpenAI's *automatic* prompt caching (`prompt_tokens_details.cached_tokens`) — the same key `CostTracker` uses for Anthropic/Bedrock/Vertex `cache_control`. LiteLLM forwards both shapes. Cache-read cost accounting now spans Anthropic, Bedrock, Vertex, and OpenAI/-compatible providers.

### Added — Anthropic server-side tools

- **`shipit_agent.llms.server_tools`**: `web_search()`, `code_execution()`, `computer_use()`, `bash()`, `text_editor()` declarations that run in Anthropic's sandbox (zero local infra); beta headers auto-attached; `server_tool_use`/results surface in `LLMResponse.metadata`. _Other providers: use shipit's client-side tools, which work with any LLM._

### Added — citations & Batch API

- Citation document helpers (`text_document`/`pdf_document`/`url_pdf_document`) → `metadata["citations"]`; **`BatchRuntime`** (`shipit_agent.batch`) for ~50%-cheaper bulk runs via the Anthropic Batches API.

### Added — interleaved thinking & context editing

- `AnthropicChatLLM(interleaved_thinking=True)` (beta) + `context_management=` server-side context editing.

### Added — examples & docs

- Notebooks `64`–`66` and docs pages, each with honest per-feature provider-support notes.

## v1.0.11 — 2026-06-07

**The control plane.** A production-grade safety + performance layer: a rule-based **permission engine** with modes (incl. read-only **plan mode**), **hooks that can block or rewrite** tool calls, **prompt caching** for ~10× cheaper repeated calls, and a model-driven **memory tool**. All opt-in and backward compatible. **1795 tests passing (+50 new). 0 regressions.**

### Added — permissions & plan mode

- **`PermissionEngine`** — rule-based gate over every tool call (no LLM): `allow`/`deny`/`ask` globs + modes `default` / `acceptEdits` / `plan` (read-only) / `bypass`. Precedence: deny > mode > allow > ask > callback > default.
- **`Agent(permission_mode=…, permissions=…, permission_callback=…)`** and **`Agent.plan(prompt)`** (read-only planning). Denied calls emit a `tool_denied` event. New exports: `PermissionEngine`, `PermissionResult`, `PermissionDecision`.

### Added — blocking / modifying hooks

- `before_tool` hooks can return a decision to **deny** or **rewrite arguments** (`PermissionResult(..., updated_arguments=…)` / `{"decision":"deny"}`); new **`on_user_prompt`** hook redacts/rewrites prompts. `None` = observe-only (backward compatible).

### Added — prompt caching

- **`AnthropicChatLLM(prompt_caching=True)`** / **`LiteLLMChatLLM(prompt_caching=True)`** (default on for Claude) place `cache_control` on tools + system prompt; `usage["cache_read_input_tokens"]`/`["cache_creation_input_tokens"]` flow into `CostTracker` (reads ~10% of input). Bedrock inherits via LiteLLM.

### Added — memory tool

- **`ClaudeMemoryTool`** (`memory_20250818` shape): `view`/`create`/`str_replace`/`insert`/`delete`/`rename`, sandboxed to `.shipit_workspace/memories`.

### Added — examples & docs

- Notebooks `61`–`63` and docs pages for permissions/plan mode, prompt caching, and the memory tool.

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
