# SHIPIT Agent 1.7.0 — Claude Code / Codex parity

The release that closes the gap to Claude Code and the OpenAI Codex/Agents
SDK. One theme runs through it: **do the powerful thing without burning
tokens or trust** — load the tools a step actually needs, cache what repeats,
recover instead of wedging, and keep long runs correct.

Everything here works over **every provider** through one interface —
Anthropic, OpenAI, AWS Bedrock (incl. Bedrock Mantle / Gemma 4), Vertex,
Gemini, Groq, Together, Ollama, and any OpenAI-compatible endpoint. Verified
live on **Gemma 4 via Bedrock Mantle** and **four MoE models on Hetzner
inference**. 3,500+ tests.

---

## Token efficiency — like Claude Code

- **Deferred tool loading** (`Agent(deferred_tools=True)`): a small core set
  keeps its schema in every request; everything else — including MCP tools —
  is listed by name only until `tool_search` discovers and loads it. Cuts the
  fixed per-step schema cost to the working set. Provider-agnostic.
- **Prompt caching across the conversation prefix** on Anthropic-family models
  (native and Bedrock/Vertex via LiteLLM), so each step extends the previous
  request from cache instead of re-billing the growing history.
- **Read-parallelization from tool contracts**: a group of read-only calls
  (grep, glob, file reads, lookups) fans out concurrently; any write/send
  stays serial and ordered. Claude Code's batched-read speed.

## A loop that never wedges

- **Backoff + jitter** on LLM retries, **per-request timeouts** on every
  adapter, **MCP call timeouts**, **sub-agent timeouts**.
- **Async-loop parity**: compaction and the argument gate now actually run on
  the async path; the sync loop uses the shared stall-nudge decision.
- **Compaction** reuses its checkpoint (no re-summarizing every step) and its
  tokens are counted; **higher default iteration budget** (12, 16 with skills)
  so hard tasks keep going.

## Tools & MCP

- **MCP hardening**: unconditional tool-name sanitization (`deepwiki**ask` →
  `deepwiki_ask`), cross-server collision renaming instead of a startup crash,
  per-request timeouts, respawn re-handshake, and server `instructions` in the
  system prompt.
- **bash**: 600s timeout ceiling, opt-in `unrestricted=True` (redirects,
  heredocs, substitution), and a `bash_job` companion to poll/kill background
  jobs.
- **`multi_edit`**: a batch of edits applied to one file atomically.
- **git worktree** actions for isolated parallel work.
- **Readability `open_url`**: structured markdown instead of tag-stripped soup.
- **Native `bedrock_mantle/` routing** and **weak-model tool-call healing**
  (four real Gemma call formats).
- **Native structured output** (`response_format` on the tool-less final turn).

## Media & multimodal

- **`agent.run(prompt, images=[...], files=[...])`** — images by URL/path/
  base64; text/markdown/code files inlined; PDFs as native document blocks.
- **`read_file` sees images and PDFs** instead of returning UTF-8 garbage.
- **Vision bridge**: tool screenshots (computer_use, MCP image results) reach
  the model as image blocks on the next step.

## Multi-agent, connections, plan mode

- **Sub-agent fixes**: child-facing final-report contract, toolset containment
  (a role can't re-grant tools the parent lacks), and per-subagent timeouts.
  New **`orchestrator`** role.
- **Connection cards** — an unauthenticated connector files a request and
  returns an actionable next step (`/login` parity).
- **Plan mode as a workflow** — a `present_plan` tool captures a structured
  plan and surfaces it for approval.

## Correctness fixes

- **Eviction no longer corrupts persisted sessions** — it's a per-request view
  now; the store keeps the full transcript.
- **Read-before-edit gate reset + file re-grounding at compaction** — the model
  can't edit a file whose contents were summarized away; the most recent files
  are re-read after compaction.
- **`CostRouter`** is usable as a drop-in `llm=`.
- **End-of-run `run_summary`** event: iterations, tool calls, tokens, cost.

---

Full detail in [CHANGELOG.md](../CHANGELOG.md).
