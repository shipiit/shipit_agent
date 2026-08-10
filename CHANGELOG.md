# Changelog

All notable changes to **shipit-agent** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Nothing yet.

---

## [1.6.0] — 2026-08-10

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

## [1.5.1] — 2026-08-08

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

## [1.5.0] — 2026-08-08

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

## [1.4.0] — 2026-08-08

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

## [1.3.3] — 2026-08-07

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

## [1.3.2] — 2026-08-07

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

## [1.3.1] — 2026-08-07

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

## [1.3.0] — 2026-08-06

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

## [1.2.0] — 2026-08-06

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

## [1.1.0] — 2026-08-06

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

## [1.0.18] — 2026-07-31

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

## [1.0.17] — 2026-07-17

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

## [1.0.16] — 2026-07-10

### Added

- **Token-by-token streaming in the native adapters** — `OpenAIChatLLM`
  (and everything built on it: Gemma 4 on Bedrock mantle, Groq, any
  OpenAI-compatible endpoint) and `AnthropicChatLLM` now implement
  `text_delta_callback` for real: tokens stream as they're generated,
  tool-call fragments are stitched by index, usage is captured from the
  final chunk, and gateways that ignore `stream=True` degrade gracefully.
  (The LiteLLM adapter already streamed; now all three do.)
- **`Agent.run_live(prompt)`** — the one-call live experience:
  tokens print as they arrive, tool calls render as ⚙ cards with args /
  status / duration, and a `✔ done · N tool calls` footer closes the run.
  Returns the final answer text. Pass `file=` to capture output.
- **`StreamRenderer`** — the underlying live renderer for custom loops:
  `renderer.feed(event)` per streamed event handles token/card interleaving
  and newline management; prints the final answer itself when an adapter
  doesn't stream, so it works with every LLM.
- **Rich rendering** — `StreamRenderer(style="rich")` / `run_live(style=...)`
  draws rich ⏺/⎿ tool cards with ANSI colors (tool name cyan, ✓
  green, ✗ red, durations dim); `"auto"` picks rich on TTYs, plain elsewhere.
- **Cancellation** — `agent.cancel()` (thread-safe) stops the in-flight
  `run()`/`stream()` at the next checkpoint (before the next LLM call or
  tool), emits `run_cancelled`, and returns normally with
  `metadata["cancelled"]`; mid-batch tool calls get synthetic
  "[cancelled before execution]" results so message pairing stays valid.
- **Edit-tool hardening** — `edit_file` now detects **external
  modification** (file mtime moved since the last `read_file`) and blocks
  with a re-read hint; successful edits return a compact **unified diff**
  (also in `metadata["diff"]`), and sequential edits keep the guard fresh.
  Read-before-edit and unique-match validation already existed.
- **LLM-powered context compaction** — when a run approaches the context
  window, older turns are now **summarized by the model** (decisions, facts,
  file paths, open threads preserved; ~300 words) instead of truncated;
  any summarizer failure falls back to the mechanical condensation, and the
  `context_compacted` event now fires reliably (explicit did-compact flag).
- **CLI upgrades** — `shipit-chat` renders turns with the live
  `StreamRenderer` (real tokens + ⏺/⎿ cards instead of a spinner), prompts
  **[y]es / [n]o / [a]lways** inline when a tool hits an `ask` permission
  rule (always-allows persist for the session), and adds `--continue` to
  resume the most recent session (default store `~/.shipit/sessions`).
  Fixed a latent crash: `--session-dir` passed a wrong kwarg to
  `FileSessionStore`.

---

## [1.0.15] — 2026-07-10

**The Super Agent.** One release that makes a shipit agent useful to every
sector — finance, marketing, engineering, design, research, sales, support —
and makes every run readable. Works with **any** LLM provider.
**1948 tests passing (+51 new). 0 regressions.**

### Added

- **`Agent.for_role(id, llm=...)`** — one line to any of the 40+ prebuilt sector
  specialists: the role's prompt, its matching builtin tools, and its iteration
  budget. Unknown ids raise `ValueError` with did-you-mean suggestions.
- **Prebuilt MCP catalog** — `connect_mcp("github")` and 11 more well-known
  servers (slack, postgres, filesystem, puppeteer, brave-search, fetch, memory,
  sentry, gitlab, sqlite, google-maps) on a persistent stdio transport, with
  fail-fast env-var and launcher validation. `list_mcp_catalog()` to browse.
- **MCP resources & prompts** — `RemoteMCPServer.list_resources()` /
  `read_resource()`, `list_prompts()` / `get_prompt()` (graceful empty when
  unsupported), and `resource_tool()` — a model-facing tool to browse/read a
  server's resources. New `MCPResource` / `MCPPrompt` types.
- **`MCPStreamableHTTPTransport`** — the 2025 streamable-HTTP spec: JSON and
  SSE responses, `Mcp-Session-Id` affinity; `bearer_token=` on both HTTP
  transports for OAuth-protected hosted servers.
- **`build_document` tool** — polished PDF reports, Excel workbooks (styled
  frozen headers, auto-sized columns, live `=` formulas), Word docs, PowerPoint
  decks, and styled HTML from one structured payload. Optional-dependency
  renderers reply with the exact `pip install` fix; wired into the builtin
  catalogue and 14 deliverable-producing specialists.
- **`format_activity(result)` / `format_event_line(event)`** — rich
  tool cards (name, args, ✓/✗, duration, output preview) for finished runs and
  live streams. `AgentEvent` gains a `timestamp`; tool events carry `tool`,
  `call_id` (live-updatable card correlation), and `duration_ms`.
- **`AgentResult.summary()`** — wall-clock duration, iterations, token usage,
  and per-tool calls/failures/total-ms in one dict.
- **`AgentScheduler`** — cron for agents: `every=` seconds, `at="HH:MM"` daily,
  or `cron="..."` (optional `croniter`), with `on_result` callbacks, `max_runs`,
  session-backed runs, and injectable `clock`/`sleep` for zero-wait tests.
  **`SQLiteJobStore`** makes jobs durable across restarts.
- **Background subagents** — `sub_agent` accepts `background=true` (returns a
  task id immediately, thread pool) and `collect="task-N"` to fetch the result.
- **Gemma on Bedrock** — `BedrockChatLLM` transparently routes Gemma 4 ids to
  the OpenAI-compatible `bedrock-mantle` endpoint (native function calling);
  Gemma 3 via Converse. New `BedrockGemmaChatLLM` under the hood.
- **`clip_text`** head+tail truncation for bash/grep/code-execution output;
  full output preserved in tool metadata.
- New examples 19–22, notebooks 69 (rebuilt with real streaming) and 70, and a
  `docs/guides/super-agent.md` tour.

### Changed

- MCP tool-call failures (server down, timeout) now return a readable tool
  result the model can react to instead of crashing the run.
- Context compaction now summarizes old user/assistant turns (previously only
  tool results; other content was dropped) and emits a `context_compacted`
  event with before/after counts.
- Default agent prompt gains a "Response style" section (lead with the answer,
  concise, clean Markdown).
- `MCPStdioTransport` / `PersistentMCPSession` aliases exported (the docs
  referenced them; the MCP guide's transport examples were corrected).

## [1.0.14] — 2026-06-13

**The SHIPIT Workspace.** Point an agent at a repo and it just works — project
instructions, slash commands, a declarative policy file, and live task tracking.
All opt-in and backward compatible. **1884 tests passing (+30 new). 0 regressions.**

### Added — project memory (`SHIPIT.md` / `AGENTS.md`)

- Agents auto-load instructions from `SHIPIT.md`, `AGENTS.md`, or
  `.shipit/SHIPIT.md` at `project_root` (plus a user-global
  `~/.shipit/SHIPIT.md`) into the system prompt — the SHIPIT answer to a project
  instructions file. Files can pull in others with `@path` imports. Opt out with
  `Agent(..., auto_project_memory=False)`. Public API: `load_project_memory()`.

### Added — slash commands (`.shipit/commands/`)

- Drop a markdown file at `.shipit/commands/<name>.md` and invoke it with
  `agent.run("/<name> args")` — the body becomes the prompt, with `$ARGUMENTS`
  and `$1`, `$2`, … substituted and YAML frontmatter stripped. Unknown `/cmd`
  passes through unchanged. Public API: `discover_commands()`, `expand_command()`.

### Added — declarative config (`.shipit/settings.json`)

- Check a policy into the repo: `permissions` (mode + allow/deny/ask), `env`,
  and a default `model`, merged under `~/.shipit/settings.json`. Wires straight
  into the permission engine. Public API: `load_settings()`, `WorkspaceSettings`.
- **`Agent.for_project(llm=…, project_root=…)`** — one call that loads settings →
  a permission engine, the full builtin tools, project memory, and slash
  commands. Provider-agnostic.

### Added — live task tracking (`TodoTool`)

- **`TodoTool`** (name `todo`, in `Agent.with_builtins()`) — the model maintains
  a checklist as it works (`pending → in_progress → completed`, replace
  semantics), stored on `context.state["todos"]` with a rendered checklist and a
  progress summary. Makes long agentic runs observable and smooth.

### Added — examples & docs

- Notebooks `67` (the SHIPIT Workspace) and `68` (TodoTool), plus docs pages.

## [1.0.13] — 2026-06-07

**Computer-use + adapter fixes.** Two bugs that blocked the computer-use
agent on every provider are fixed; both are backward compatible.
**1854 tests passing (+10 new). 0 regressions.**

### Fixed

- **Computer-use now works in Jupyter / asyncio.** `PlaywrightBrowserSession`
  used Playwright's *sync* API, which refuses to run inside an already-running
  asyncio event loop (e.g. a notebook cell) — raising
  *"It looks like you are using Playwright Sync API inside the asyncio loop."*
  It now runs every Playwright call on a dedicated, loop-free worker thread, so
  the same synchronous API works in scripts, notebooks, and async web
  frameworks. No API change.
- **All LLM adapters accept dict messages** — fixes
  `'dict' object has no attribute 'role'`. `ComputerUseAgent` (and any caller)
  builds plain `{"role", "content"}` dict messages, sometimes with multimodal
  list content, but adapters accessed `message.role` and crashed. Fixed at the
  adapter layer so it's universal:
  - **LiteLLM family** (Bedrock, Gemini, Vertex, Groq, Together, Ollama) and
    **OpenAI** — `_serialize_message` accepts dicts and translates the
    Anthropic-shape base64 image block to a portable `image_url` block.
  - **Anthropic** and **ShipitLLM** — coerce dicts via a new shared
    `coerce_message()` / `coerce_messages()` helper in `shipit_agent.llms.base`.

## [1.0.12] — 2026-06-07

**Claude API power features + cross-provider caching.** Adds Anthropic
server-side tools, citations, the Batch API, interleaved thinking & server-side
context editing — and makes prompt caching work across providers (not just
Anthropic). All opt-in and backward compatible. **1844 tests passing (+49 new).
0 regressions.**

### Added — cross-provider prompt caching

- **Prompt caching is no longer Anthropic-only.** OpenAI does *automatic*
  prompt caching — the OpenAI adapter now surfaces
  `usage["cache_read_input_tokens"]` from `prompt_tokens_details.cached_tokens`
  (and `reasoning_tokens` for reasoning models), the same keys `CostTracker`
  uses for the Anthropic `cache_control` path. LiteLLM forwards both shapes.
  Net: cache-read cost accounting works for Anthropic, Bedrock, Vertex **and**
  OpenAI / OpenAI-compatible providers.

### Added — server-side tools (Anthropic)

- **`shipit_agent.llms.server_tools`** — `web_search()`, `code_execution()`,
  `computer_use()`, `bash()`, `text_editor()` helpers that declare Anthropic
  **server-side** tools (executed in Anthropic's sandbox — zero local infra).
  The adapter forwards them verbatim, attaches the required beta headers
  automatically, and routes `server_tool_use` / result blocks into
  `LLMResponse.metadata` (never into the client tool loop). _Note: these are
  Anthropic API shapes; other providers use shipit's client-side tools
  (`WebSearchTool`, `CodeExecutionTool`, …) which work with any LLM._

### Added — citations & Batch API

- **Citations** — `text_document()` / `pdf_document()` / `url_pdf_document()`
  document helpers with `citations.enabled`; response citations are parsed into
  `LLMResponse.metadata["citations"]` for verifiable, grounded answers.
- **`BatchRuntime`** (`shipit_agent.batch`) — submit many requests to the
  Anthropic Messages Batches API for ~50%-cheaper bulk/offline runs;
  `BatchRequest` / `BatchResult`, `run(...)` polls to completion with an
  injectable clock/sleep.

### Added — interleaved thinking & context editing

- **`AnthropicChatLLM(interleaved_thinking=True)`** — adds the
  `interleaved-thinking-2025-05-14` beta and surfaces `thinking` blocks in
  metadata; **`context_management=`** forwards Anthropic's server-side
  context-editing (auto-clear old tool results).

### Added — examples & docs

- Notebooks `64`–`66` (server-side tools, citations + batch, interleaved
  thinking) and docs pages for each, all with honest per-feature **provider
  support** notes.

## [1.0.11] — 2026-06-07

**The control plane.** A production-grade safety + performance layer: a
rule-based **permission engine** with modes (incl. read-only **plan mode**),
**hooks that can block or rewrite** tool calls, **prompt caching** for ~10×
cheaper repeated calls, and a model-driven **memory tool** for cross-session
learning. All opt-in and backward compatible — existing agents are unchanged.
**1795 tests passing (+50 new). 0 regressions.**

### Added — permission engine & plan mode

- **`PermissionEngine`** — a fast, rule-based gate over every tool call (no LLM
  needed). Declarative `allow` / `deny` / `ask` rules (fnmatch globs on tool
  name) and **modes**: `default`, `acceptEdits` (auto-approve file edits),
  `plan` (read-only — mutating tools denied so the agent proposes a plan), and
  `bypass`. Precedence: deny > mode > allow > ask > callback > default.
- **`Agent(permission_mode=…, permissions=…, permission_callback=…)`** —
  configure via a mode string, a full `PermissionEngine`/kwargs dict, and/or a
  `canUseTool`-style callback `(name, args) -> PermissionResult | None` for
  programmatic human-in-the-loop approval.
- **`Agent.plan(prompt)`** — run read-only and get back a proposed plan.
- Denied calls emit a `tool_denied` event and return a "was NOT run" tool
  message so the model re-plans. New exports: `PermissionEngine`,
  `PermissionResult`, `PermissionDecision`.

### Added — blocking / modifying hooks

- `AgentHooks` **`before_tool`** hooks can now **return a decision** to deny a
  call or **rewrite its arguments** (`PermissionResult(..., updated_arguments=…)`
  or `{"decision": "deny", "reason": …}`), in the standard pre-tool-hook shape.
- New **`on_user_prompt`** hook can redact or rewrite the incoming prompt.
- Returning `None` preserves the old observe-only behaviour (backward compatible).

### Added — prompt caching

- **`AnthropicChatLLM(prompt_caching=True)`** / **`LiteLLMChatLLM(prompt_caching=
  True)`** (default on for Claude-family models) place `cache_control`
  breakpoints on the tool definitions and system prompt — the stable prefix the
  runtime rebuilds every iteration. Bedrock inherits via LiteLLM.
- Responses surface `usage["cache_read_input_tokens"]` /
  `["cache_creation_input_tokens"]`, which flow into `CostTracker` so cache
  reads bill at the discounted rate. Degrades safely on non-Anthropic models.

### Added — memory tool

- **`ClaudeMemoryTool`** — the Anthropic `memory_20250818`-style tool the model
  calls with a `command` (`view` / `create` / `str_replace` / `insert` /
  `delete` / `rename`), sandboxed to `.shipit_workspace/memories` (path-escape
  rejected) for true cross-session learning.

### Added — examples & docs

- Three new notebooks (`notebooks/61`–`63`) and docs pages for permissions/plan
  mode, prompt caching, and the memory tool.

## [1.0.10] — 2026-06-07

**Bug-fix & hardening release.** Fixes a v1.0.9 regression that broke custom
LLM adapters, hardens the local-execution and connector tools against
sandbox-escape / SSRF, and tightens session, cost, and concurrency
correctness. No public API was removed and no caller needs code changes.
**1742 tests passing (+180 new). 0 regressions.**

### Fixed — critical

- **`text_delta_callback` regression (v1.0.9).** The runtime passed the new
  `text_delta_callback` kwarg to `LLM.complete()` *unconditionally*, raising
  `TypeError` for any adapter on the prior protocol signature (every custom
  adapter, and all test mocks). The runtime now detects support via signature
  inspection and only passes the callback to adapters that accept it —
  backward compatible, with streaming preserved for opted-in adapters.
- **Multi-turn sessions stacked duplicate system prompts.** Re-running with a
  persistent `session_store` + reused `session_id` (the `AgentChatSession`
  path) re-appended a fresh system message every turn — unbounded growth and a
  malformed mid-conversation system block. The runtime now injects exactly one
  leading system message and strips persisted ones on reload.

### Fixed — security hardening (tools)

- **Bash tool** — `_validate_command` rejects command substitution (`$(…)`,
  backticks), process substitution, and file redirection that could smuggle
  past the allowlist.
- **`open_url` / browser fetch** — http(s)-only; blocks `file://` and private,
  loopback, link-local, and cloud-metadata IPs (SSRF). Opt out with
  `allow_private_hosts=True`.
- **SQL tool** — the read-only guard scans the *entire* statement (not the
  first 500 chars) and rejects stacked statements, closing an
  `allow_writes=False` bypass on multi-statement drivers.
- **OAuth** — `OAuthHelper.exchange_code(state=…)` validates and consumes the
  CSRF state nonce.
- **`edit_file`** — refuses to edit non-UTF-8 files instead of silently
  corrupting them.
- **`FileCredentialStore`** — warns that secrets are stored in plaintext,
  chmods the file `0600`, and writes atomically.

### Fixed — reliability & correctness

- MCP transports are closed even when a run raises (`try/finally`), and
  `RemoteMCPServer.discover_tools` closes its transport on a failed handshake —
  no more leaked subprocesses.
- Parallel tool execution gives each tool an isolated copy of shared state and
  merges results deterministically, fixing a read-modify-write race.
- The iteration-cap summary turn now counts its tokens and fires the after-LLM
  hook (previously escaped all cost/usage accounting).
- `CostTracker` no longer silently bills unknown models at `$0` while a budget
  is active — it flags `has_unknown_pricing` and warns (raises only under
  `on_unknown_model="error"`), so budgets can't be silently bypassed.
- `JSONParser` extracts the *balanced* JSON object via a depth scan and prefers
  a ```json fence, instead of grabbing the last brace / first fenced block.
- Pipeline `stream()` no longer executes agent steps twice.
- Autopilot fan-out preserves input order (was sorted lexicographically by
  run id).
- `create_deep_agent(goal=…/reflect=…)` forwards `memory`, `history`, and
  `verifier` to the inner agent.
- `InMemoryVectorStore` uses monotonic ids (no reuse/collision after a delete).
- `FileSessionStore` / `FileMemoryStore` write atomically (+ a lock on memory
  `add`) so concurrent readers never see truncated JSON.
- `grep` tool gains a configurable subprocess timeout and a global match cap;
  ShipCrew task `timeout_seconds` now actually pre-empts; `code_execution`
  removes its temp script; `diff_traces` stops counting matches after a
  reconverging divergence; RAG `total_found` reports the true match count.

### Added

- 180+ new tests covering every fix above (suite now 1742 passing, 8 skipped).
- Six new runnable examples — `examples/13_parallel_tools.py` through
  `examples/18_verifier_guard.py` (parallel tools, cost budgets, multi-turn
  memory, async runtime, secure tools, verifier guard).

## [1.0.9] — 2026-05-14

**Inline text streaming.** The agent can now stream LLM tokens token-by-token
as they arrive, matching the feel of a modern chat-coding assistant. Existing
non-streaming behaviour is preserved byte-for-byte for callers that don't
opt in — streaming is enabled per-call via the new `text_delta_callback`
parameter.

### Added

- **`LLM.complete(text_delta_callback=…)`** — every adapter now accepts a
  callback parameter (Protocol-level addition). When provided, the adapter
  streams the completion and calls the callback synchronously for each text
  chunk as it arrives, then returns the same `LLMResponse` as a non-streaming
  call. Currently implemented end-to-end for `LiteLLMChatLLM`; other
  adapters accept the parameter as a no-op for Protocol compliance.
- **`AgentRuntime` emits `text_delta` events** — when the configured LLM
  adapter supports streaming, the runtime wires a callback that calls
  `self.emit(state, "text_delta", "", chunk=…)` for each token. Downstream
  SSE / WebSocket consumers can forward these inline alongside `tool_called`
  and `tool_completed` events.

### Internal

- `LiteLLMChatLLM` internal `_stream_completion` helper accumulates text
  chunks, tool-call argument fragments (multi-chunk JSON), reasoning content,
  and usage metadata. Tool calls streamed across multiple deltas are correctly
  re-assembled into single `ToolCall` objects.
- Five new tests in `tests/test_litellm_streaming.py` cover the non-streaming
  path, callback streaming, tool-call delta accumulation, end-to-end runtime
  `text_delta` emission, and resilience to misbehaving subscriber callbacks.

### Notes

- Image / vision support is unchanged in this release — `VisionTool`,
  `ComputerUseAgent`, and `BrowserAgentTool` continue to provide multi-modal
  capability for agents that need it.
- No public API was removed. No callers need code changes; opt in by passing
  `text_delta_callback` when calling `LLM.complete()`.

## [1.0.8] — 2026-05-09

**Five flagship features that beat the competition.** Structured output
with same-conversation auto-retry. Verifier network for process
supervision. Episodic memory consolidation with forgetting curve.
Time-travel replay. ComputerUseAgent + BrowserAgentTool.

All five reachable from `from shipit_agent import …`. Both `Agent` AND
`DeepAgent` get them. **1527 unit tests (+337 new). 0 regressions.**

### Added — power features

- **`StructuredOutput`** — wraps any LLM with same-conversation
  validation retry, streaming partial JSON, and Pydantic / JSON Schema
  parsing. Wired into `Agent.run(output_schema=, max_validation_retries=2)`
  and through to `DeepAgent`.
- **`VerifierNetwork`** — pre-tool veto + per-iteration progress check,
  both backed by a (typically cheap) verifier LLM. Wraps every tool the
  agent sees; vetoed calls become synthetic error tool-results so the
  agent re-plans. Confidence-gated, hard-capped, fails open.
- **`MemoryConsolidator`** — distill conversations into 3-8 durable
  facts; exponential decay with prune threshold; core-memory ranking by
  `strength + 0.1·log1p(retrievals)`; `record_retrieval()` for the
  feedback loop.
- **`TraceReplayer`** — load any saved `TraceRecord`, inspect events,
  fork at any event with optional prompt edit, resume on a fresh agent.
  `diff_traces()` for side-by-side comparison.
- **`ComputerUseAgent`** — screenshot → reason → act loop driving a
  `BrowserSession`. `MockBrowserSession` for tests;
  `PlaywrightBrowserSession.launch()` for production. Anthropic native
  computer-use + plain-text fallback for any vision LLM.
- **`BrowserAgentTool`** — adapter that exposes `ComputerUseAgent` as a
  regular `Tool` so the main `Agent` can call `browser_use(goal=...)`
  alongside `web_search`, `pdf_extract`, etc.

### Added — tests + docs + notebooks

- **+337 unit tests** (1190 → 1527), zero regressions, ≥10 tests per
  public method.
- **6 new notebooks**: `54_structured_output_with_retry`,
  `55_verifier_network`, `56_episodic_memory_consolidation`,
  `57_time_travel_replay`, `58_computer_use_agent`,
  `59_browser_agent_tool`.
- **5 new docs pages** under `agent/`: structured-output, verifier,
  memory-consolidation, time-travel-replay, computer-use.
- **`banner.svg`** at repo root. README updated with v1.0.8 highlights.
- **`RELEASE_NOTES_1.0.8.md`** with the full release narrative.

### Compatibility

- All v1.0.7 APIs continue to work unchanged.
- New constructor kwarg on `Agent`: `verifier=` (default `None`).
- New `Agent.run` kwarg: `max_validation_retries=` (default 2).
- `DeepAgent` accepts `verifier=`; propagates through to inner Agent.
- Optional dependency: `pip install playwright` for
  `PlaywrightBrowserSession` (imported lazily).

---

## [1.0.7] — 2026-04-24

**Agents for every role.** 12 new tools and 9 new persona specialists
turn shipit-agent into a framework that ships agents for developers,
designers, sales reps, PMs, data analysts, finance, customer support,
and recruiters — not just code-slinging agents. **1190 unit tests.
286 new in this release. All passing.**

### Added — Core tools (everyone benefits)

- **`GitHubTool`** — first-class GitHub connector: search / get / create
  issues, pull requests, reviews (APPROVE / REQUEST_CHANGES / COMMENT),
  file contents, GitHub Actions workflow runs. Supports github.com and
  GitHub Enterprise (set `base_url` on the credential record).
  Rate-limit aware (403 + `X-RateLimit-Remaining: 0` → structured
  `error="rate_limited"` with `retry_after_epoch`).
- **`GitLabTool`** — GitLab v4 REST: issues, merge requests, file
  contents, CI pipelines (list / retry / cancel). Supports gitlab.com
  and self-hosted GitLab. Handles URL-encoded project paths.
- **`SQLTool`** — SQLAlchemy-backed multi-dialect tool covering
  PostgreSQL, MySQL, SQLite, BigQuery, Snowflake, Redshift, MSSQL,
  Oracle, and anything else SQLAlchemy supports. Read-only by default;
  writes gated behind `allow_writes=True`. `query`, `execute`,
  `list_tables`, `describe_table`, `schema_summary`. Write guard uses a
  case-insensitive keyword denylist over the first 500 non-whitespace
  chars. Row cap + JSON-safe serialization of dates / decimals / bytes.
- **`VisionTool`** — image → text via any vision-capable LLM (Claude,
  GPT-4o, Gemini, Bedrock Claude, LiteLLM). Accepts filesystem paths,
  URLs, data-URLs, or raw base64; auto-resolves each shape. Pairs
  naturally with `ComputerUseTool` (screenshot → analyse).
- **`PDFTool`** — extract text, per-page content, and metadata from
  local files or URLs. Page-range parsing (`"1-3,5,7-9"`), char caps
  with truncation markers, clean error taxonomy (`pypdf_missing`,
  `file_not_found`, `url_fetch_failed`, `pdf_parse_error`).
- **Observability exporters** — new
  `shipit_agent.tracing_exporters` package:
  - `LangSmithExporter` — batches spans and POSTs to the LangSmith
    runs API. Stdlib-only transport; silent on network failures.
  - `OpenTelemetryExporter` — converts `AgentEvent` to OTel spans via
    the standard OTel Python SDK, so users can route to any OTLP
    backend (Datadog, Grafana, Honeycomb, …).

### Added — Persona SaaS connectors

- **`FigmaTool`** — read files, nodes, rendered images, comments, team
  projects, and components. `X-Figma-Token` auth header (not Bearer).
  Post / resolve comments. Designer workflows.
- **`SalesforceTool`** — SOQL / SOSL queries, read
  accounts / opportunities / contacts, create / update records,
  `log_activity` (always enabled) vs full record writes (gated behind
  `allow_writes=True`). 401 maps to `error="auth_expired"` so token
  refresh is explicit.
- **`StripeTool`** — list / get customers, charges, subscriptions,
  invoices, prices, products. Read-heavy by default; `create_customer`
  and `cancel_subscription` gated by `allow_writes`. Basic-auth header
  (Stripe's `key:` pattern). Form-urlencoded bodies for POST/DELETE.
  Test-vs-live mode surfaced in `metadata`.
- **`GoogleSheetsTool`** — `get_values`, `update_values`,
  `append_values`, `clear_values`, `batch_get`, `get_metadata`,
  `create_spreadsheet`, `add_sheet`. A1-notation ranges URL-encoded;
  suffixes (`:append`, `:clear`, `:batchUpdate`) applied after
  encoding. Dual rate-limit detection (429 + 403+quota-reason).
- **`ZendeskTool`** — search / get / list tickets; create / update /
  close (gated); `add_comment` (always enabled for triage);
  `list_macros` + `apply_macro` preview; user search. Basic-auth with
  the email+token pattern.
- **`LinkedInSearchTool`** — intentionally **read-only**. Profile /
  company lookup, people / company search, company-employee
  enumeration. Three auth modes (Bearer, custom-header for RapidAPI,
  query-param). Four layers of write-free enforcement (fixed enum
  tuple + keyword denylist + runtime defensive check + GET-only
  methods). No DMs, no connection requests, no automation.

### Added — Specialist personas (`agents.json`)

Nine new entries — total roster now 56:

- **`code-reviewer-bot`** — autonomous PR reviewer (github + read_file + grep_files + vision).
- **`release-engineer`** — cut releases on a repeatable cadence (github + bash + slack).
- **`figma-designer`** — design review + handoff (figma + vision + render_dashboard).
- **`sales-rep`** — lead enrichment + outreach drafting (salesforce + linkedin_search + gmail).
- **`account-executive`** — pipeline reviews + account health (salesforce + linkedin_search + sql).
- **`sales-ops`** — funnel instrumentation + data-quality audits (salesforce + sql + google_sheets).
- **`recruiter`** — sourcing + candidate tracking (linkedin_search + google_sheets + pdf).
- **`finance-analyst`** — month-end close + cash-flow one-pagers (stripe + pdf + sql + render_dashboard).
- **`customer-support-agent`** — ticket triage + incident detection (zendesk + vision + slack).

### Added — Notebooks (persona walk-throughs)

- `47_pm_pr_digest.ipynb` — nightly PR digest across multiple repos.
- `48_designer_figma_review.ipynb` — Figma file → design review dashboard.
- `49_sales_lead_enrichment.ipynb` — Salesforce lead + LinkedIn enrichment + outreach draft.
- `50_manager_sheets_kpis.ipynb` — Google Sheets KPIs → weekly dashboard.
- `51_support_zendesk_triage.ipynb` — ticket triage with screenshot reading.
- `52_analyst_sql_to_dashboard.ipynb` — SQL question → chart dashboard (real SQLite).
- `53_finance_stripe_pdf_cashflow.ipynb` — Stripe + PDF contracts → cash-flow one-pager.

Each notebook ships with its `_nb<N>_builder.py` and executes clean
with zero cell errors using stubbed API calls so CI / first-time users
don't need credentials to see the flow.

### Added — Optional dependency extras

New `[project.optional-dependencies]` groups in `pyproject.toml`:

- `pdf = ["pypdf>=4.0"]`
- `sql = ["sqlalchemy>=2.0"]` (install drivers separately — `psycopg2-binary`, `pymysql`, `snowflake-sqlalchemy`, `sqlalchemy-bigquery`, …)
- `langsmith = []` (stdlib-only — no extra deps)
- `otel = ["opentelemetry-api>=1.25", "opentelemetry-sdk>=1.25"]`

### Changed

- `CapabilitiesGrid` / `AutopilotShowcase` landing-page components
  bumped to v1.0.7 with the new specialist count and the "Agents for
  every role" framing. New `AgentsForEveryRoleSection` +
  `ToolMatrix107` landing sections visualise the persona roster and
  the 12 new tools.
- Docs — six new reference pages under
  `docs-app/content/source/tools/` (github, gitlab, vision, sql, pdf)
  and a new guide `docs-app/content/source/guides/connecting-saas.md`
  that documents the full credential-setup flow for all 15 connectors
  (Gmail / Drive / Calendar / Sheets · Slack · Linear · Jira ·
  Confluence · Notion · HubSpot · GitHub · GitLab · Figma · Salesforce
  · Stripe · Zendesk · LinkedIn). Plus
  `docs-app/content/source/guides/observability-exports.md`. Mkdocs
  nav updated.

### Tests

- `tests/test_github_tool.py` (29), `test_gitlab_tool.py` (26),
  `test_vision_tool.py` (21), `test_sql_tool.py` (46),
  `test_pdf_tool.py` (23), `test_tracing_exporters.py` (15),
  `test_figma_tool.py` (17), `test_salesforce_tool.py` (22),
  `test_stripe_tool.py` (24), `test_google_sheets_tool.py` (21),
  `test_zendesk_tool.py` (23), `test_linkedin_tool.py` (19).
- 286 new tests total. **1190 passing, 8 skipped (gated Bedrock + soak), 0 regressions.**

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

[Unreleased]: https://github.com/shipiit/shipit_agent/compare/v1.0.18...HEAD
[1.0.18]: https://github.com/shipiit/shipit_agent/compare/v1.0.17...v1.0.18
[1.0.17]: https://github.com/shipiit/shipit_agent/compare/v1.0.16...v1.0.17
[1.0.16]: https://github.com/shipiit/shipit_agent/compare/v1.0.15...v1.0.16
[1.0.15]: https://github.com/shipiit/shipit_agent/compare/v1.0.14...v1.0.15
[1.0.14]: https://github.com/shipiit/shipit_agent/compare/v1.0.13...v1.0.14
[1.0.13]: https://github.com/shipiit/shipit_agent/compare/v1.0.12...v1.0.13
[1.0.12]: https://github.com/shipiit/shipit_agent/compare/v1.0.11...v1.0.12
[1.0.11]: https://github.com/shipiit/shipit_agent/compare/v1.0.10...v1.0.11
[1.0.10]: https://github.com/shipiit/shipit_agent/compare/v1.0.9...v1.0.10
[1.0.1]: https://github.com/shipiit/shipit_agent/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/shipiit/shipit_agent/releases/tag/v1.0.0
