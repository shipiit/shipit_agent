# The shipit CLI

One command surfaces the whole runtime: a coding agent for your repo, a
live one-shot runner, an interactive REPL, an OpenAI-compatible server, and
catalogs for every role, model, MCP server, and tool.

```
shipit code "fix the failing test"     🛠 coding agent in your repo
shipit browse "cheapest SFO→JFK?"      🌐 computer use: drive a real browser
shipit run "prompt"                    one-shot with live ⏺/⎿ tool cards
shipit chat                            interactive REPL (bottom-pinned input)
shipit serve                           your agent as an OpenAI-compatible API
shipit roles | models | mcp | tools    catalogs
shipit doctor | version                health / version
```

Install gives you the `shipit` entry point: `pip install shipit-agent`.

## Providers & models

Pick a provider with `--provider` or `$SHIPIT_LLM_PROVIDER`, a model with
`--model` or `$SHIPIT_MODEL`. `shipit models` lists the curated latest
catalog with defaults marked:

| Provider | Default | Also in catalog |
|---|---|---|
| `anthropic` | `claude-sonnet-5` | `claude-opus-5` (best agentic), `claude-haiku-4-5` |
| `openai` | `gpt-5.5` | `gpt-5.6`, pinned snapshots |
| `bedrock` | `google.gemma-4-31b` | `gemma-4-26b-a4b`, `gpt-oss-120b`, Anthropic models on Bedrock |
| `ollama` | `ollama/llama3.1` | any local model |

## `shipit code` — the coding agent

Roots `Agent.for_project()` in your current directory: project memory
(`SHIPIT.md`/`AGENTS.md`), `.shipit/commands/` slash commands, the
checked-in permission policy, and the full 50-tool builtin roster — driven
by a senior-engineer playbook (read first → smallest patch → verify with
tests → report `path:line`).

```bash
shipit code "add input validation to the signup endpoint"
shipit code --plan "how would you introduce rate limiting?"   # read-only
shipit code --yes "rename UserSvc to UserService"             # auto-accept edits
shipit code --guardrails strict --max-tool-calls 30 "..."     # hardened
```

Modes: default asks **[y]es / [n]o / [a]lways** before `ask`-gated tools;
`--plan` is read-only research; `--yes` is `acceptEdits`. The toolbox
includes `git_ops` (structured git — status/diff/log/blame/commit; push and
reset disabled by default), `notebook_edit` (structural `.ipynb` cells),
hardened `edit_file` (unified diffs + external-change detection), `bash`,
`glob_files`/`grep_files`, `run_code`, `deep_research`, `download_file`,
`build_document`, background `sub_agent`, and more.

Two runtime layers keep small open-weight models productive:
**self-healing tool calls** (calls emitted as text — `<tool_call>` tags,
fenced JSON — are promoted to real executions, declared-tools-only,
span-exact) and **nudge-on-stall** (one capped re-prompt when the model
narrates intent without acting).

## `shipit serve` — your agent as an API

```bash
shipit serve --provider bedrock --role finance-analyst --api-key secret
```

Exposes `POST /v1/chat/completions` (with SSE streaming fed by the agent's
live events), `GET /v1/models`, and `GET /health`. Any OpenAI SDK works:

```python
from openai import OpenAI
client = OpenAI(base_url="http://127.0.0.1:8399/v1", api_key="secret")
reply = client.chat.completions.create(
    model="shipit", messages=[{"role": "user", "content": "Close Q2."}])
```

Requests are validated before any agent work runs; auth is optional Bearer
(open on loopback by default); stream errors arrive as in-band SSE frames.

## `shipit browse` — computer use

```bash
shipit browse --show "find the cheapest direct SFO→JFK flight on May 20"
```

Drives a real browser with the vision loop: screenshots → reasoning →
clicks/typing, streamed as live cards. `--show` opens a visible Chrome
window slowed enough to watch; consent walls and popups are handled by the
agent itself, and accepted consent persists across runs via
`--storage-state`. Prefer a vision-capable model.

## Attach MCP servers — `--mcp`

Every agent command accepts comma-separated catalog servers:

```bash
shipit code  --mcp playwright "verify the signup flow on staging"
shipit run   --mcp playwright,filesystem "check example.com's title"
shipit serve --mcp playwright --api-key secret
```

The catalog now includes the **official Playwright MCP**
(`@playwright/mcp` — accessibility-tree navigation/click/type/screenshot,
no API key), so any tool-calling model gets browser control without
vision. Missing env vars or launchers fail fast with one clear message.

## Human-in-the-loop

`ask`-gated tools pause for a real decision — in `shipit chat` and
`shipit code` automatically, and in any library agent via:

```python
from shipit_agent import Agent, console_permission_prompt
from shipit_agent.permissions import PermissionEngine

agent = Agent.with_builtins(
    llm=llm,
    permissions=PermissionEngine(ask=["bash", "write_file", "git_ops"]),
    permission_callback=console_permission_prompt(),
)
# ⏸ allow bash(command='rm dist')? [y]es / [n]o / [a]lways:
```

**[a]lways** persists for the session (the allowed-set is shareable across
agents); EOF/Ctrl-C denies safely; denials reach the model as readable
reasons it can react to.

## The UI layer

Every command shares one terminal kit: a named 256-color palette,
`NO_COLOR`/`FORCE_COLOR` respected before TTY detection, encoding-safe
printing that can't crash a launch, and audience-bucketed banners. Live
runs render compact ⏺/⎿ tool cards with durations.

`shipit chat` adds a full-screen layout on real TTYs: chat scrolls
in a VT100 scroll region while the input stays pinned to the bottom row
(stdlib-only; `SHIPIT_NO_TUI=1` opts out, pipes/CI fall back to plain
text automatically). Slash commands autocomplete via Tab.

## Related

- [The super agent](../agent/index.md) — the capabilities behind the CLI
- [Observability](observability-exports.md) — Langfuse/LangSmith/OTel
- [Streaming](../agent/streaming.md) — the event model the cards are built on
