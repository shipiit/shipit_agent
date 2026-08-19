# CHANGES — the complete manifest

**8,398 module lines · 2,808 test lines · 280 tests passing · no new runtime dependencies.**

Generated from the tree, not from memory. Three things I said earlier are now
wrong, and they are corrected first because they matter more than the additions.

---

## Corrections to my earlier summary

| I said | Actually |
|---|---|
| `agent.py` — Agent, the entry point | **Removed.** Your `agent.py` has 57 fields and 20 methods (`clone`, `as_tool`, `with_builtins`, `for_project`, `for_role`, `plan`, `narrate`, `doctor`, `chat_session`, `reason`, and `run` with `images`/`files`/`output_schema`). Mine had 20 fields and 4 methods. Shipping it would have been a large regression wearing the same filename. Replaced by `bridge.py`. |
| `toolkit/core.py` — the seven core tools | **Split.** One tool per directory, matching your `tools/<name>/<name>_tool.py` + `prompt.py` convention. Twelve packages. |
| `skills/authoring.py` — SKILL.md format | **Renamed to `skills/markdown.py`.** Your `skills/authoring.py` already exists (`SkillCatalog`, `create_skill`). Mine would have clobbered it. |

The pattern in all three: I was about to overwrite something of yours that was
already better, or already there. Worth checking the same way for anything else
you merge.

---

## What is new

### The run loop and its data

| Module | Lines | What it is |
|---|---|---|
| `models.py` | 402 | `ToolCall.id`, `ToolResult.tool_call_id`, `Message.tool_calls` as **fields**, plus `pair_calls_and_results()`. This is what lets you drop `modify_params=True` — no more LiteLLM rewriting your history to repair pairing the type system could not express. Legacy `metadata` shape still loads for one release. |
| `graph.py` | 644 | The loop as a generator. Text deltas, streamed tool arguments, live tool output, skill loads, tool discovery, sub-agent activity, compaction — one `AgentEvent` channel. `AgentResult` is built from the same state, so streaming and non-streaming cannot drift. |
| `bridge.py` | 247 | Reads your existing `Agent` and produces a `RunSpec`. Every field keeps its name. `unmapped()` names the 25 features the new loop does not yet reproduce, so migration is a checklist rather than a discovery. |
| `subagents.py` | 270 | Delegation with narrowed tools, isolated context, depth bound, and usage attributed to the parent ledger — `delegation.py` tracks zero usage today. |

### Providers

| Module | Lines | What it is |
|---|---|---|
| `llms/capabilities.py` | 416 | Superset of yours, same public API. Gemma now blocks what Mantle actually rejects; context windows carried as data; reasoning-history policy; schema dialect; service-tier support. |
| `llms/schema_prep.py` | 415 | `$ref`/`$defs` inlining — **you had none anywhere** — then normalise, then dialect sanitize. Cycle-safe, cached, never raises. Still my best guess at the live Gemma bug. |
| `llms/schema_rules.py` | 165 | Per-dialect keyword rules. Unknown dialect strips nothing. |
| `llms/parameters.py` | 285 | Canonicalise → coerce → **route wire vs host** → adapt. `max_context_tokens` and `fileTokenLimit` are host params; forwarding them is a 400 on a field you never aimed at the provider. |
| `llms/wire.py` | 243 | Image sources (Mantle takes base64 and `s3://`, not `https://`), block order, reasoning replay vs strip — DeepSeek and Gemma have opposite contracts. |
| `llms/mantle.py` | 221 | Region preflight, `RefreshingBearerToken` (your derived key dies at 12h; `scheduler_daemon` outlives it), IAM hint naming the managed policy. |
| `llms/throttle.py` | 207 | 429, 503, 401 and 400 as four different actions, not one retry loop. |

### Context, cost, resume

| Module | Lines | What it is |
|---|---|---|
| `prefix.py` | 198 | Byte-stable prompt assembly. Sorting tool definitions is a one-line change that recovers every cache hit gating and MCP discovery order were destroying. |
| `prefix_rules.py` | 88 | Renders **your** `rules/` into the prefix — scoped by active tools, ordered deterministically, deduplicated. Nothing was doing this. |
| `usage.py` | 273 | Purpose-tagged accounting and service-tier routing. Cost is `None` when any call is unpriced, because a partial sum reads as authoritative. |
| `checkpoint.py` | 247 | Resume that restores primed skills and discovered tools, not just messages. |
| `live.py` | 225 | Typed packets with `tool_call_id`, so parallel tools render separately. Terminal packet emitted last. |
| `config.py` | 262 | Layered YAML. Deleting it changes nothing — asserted by a test. |

### Tools and MCP

| Module | Lines | What it is |
|---|---|---|
| `mcp_bridge.py` | 353 | Describe → disclose → connect. Attaching twenty servers costs twenty cache reads, not twenty subprocesses. Injects server `instructions` — the field your `mcp.py:646` reads and never uses. |
| `discovery.py` | 282 | Deferred tools behind `tool_search`. Search scores name, description and server, and returns the signature so no second round-trip is needed. |
| `connections/mcp.py` | 361 | MCP connectors as records. Sits **alongside** your `models.py`/`registry.py` — yours answers "has the user connected Jira?", this answers "how do I start Jira's server?". |
| `toolkit/contracts.py` | 299 | Read-before-write, unique-match edits, visible truncation, errors-as-results, argument shapes in logs. |
| `skills/catalog.py` | 383 | Catalog in the prefix, bodies via `load_skill` at any iteration. |
| `skills/markdown.py` | 300 | The SKILL.md folder format: parse, discover, write. |

### The twelve tools, one directory each

```
tools/bash/            bash_tool.py + prompt.py     run a command
tools/read_file/       read_file_tool.py + prompt   records the read
tools/write_file/      write_file_tool.py + prompt  refuses to clobber
tools/edit_file/       edit_file_tool.py + prompt   exact unique match
tools/glob/            glob_tool.py + prompt        newest first, skips noise
tools/grep/            grep_tool.py + prompt        grouped, bounded
tools/todo/            todo_tool.py + prompt        flags split focus
tools/fetch_url/       fetch_url_tool.py + prompt   no dependency
tools/web_search/      web_search_tool.py + prompt  injected backend
tools/ask_user/        ask_user_tool.py + prompt    one tool, not four
tools/memory/          memory_tool.py + store.py    bounded, persisted
tools/report_progress/ report_progress_tool.py      doubles as a resume point
tools/computer_use/    AUDIT.md                     recommendation: drop it
```

Prompt text lives next to the tool it describes, so the wording that decides
whether a tool is used correctly is edited alongside the behaviour.

### The seven skills

| Skill | Body | References |
|---|---|---|
| `api-design` | 3,046c | `versioning.md` |
| `data-cleaning` | 3,141c | — |
| `debugging` | 2,880c | `common-causes.md` |
| `technical-writing` | 2,823c | — |
| `code-review` | 1,821c | — |
| `incident-report` | 1,729c | — |
| `release-notes` | 1,435c | — |

**1,063 characters of catalog against 16,875 characters of body.** That ratio is
the whole argument for progressive disclosure, and it only improves as the
library grows.

---

## The tests

| File | Tests | Covers |
|---|---|---|
| `test_agent_core.py` | 47 | prefix stability, skills, usage, checkpoints, packets, config |
| `test_graph.py` | 45 | run loop, tool contracts, pairing, delegation |
| `test_providers.py` | 33 | capabilities, wire format, Mantle auth, throttle |
| `test_mcp_and_skills.py` | 32 | MCP attachment, deferred discovery, SKILL.md |
| `test_tools_and_connections.py` | 30 | per-directory tools, rules block, connectors |
| `test_parameters.py` | 26 | canonicalisation, coercion, wire/host routing |
| `test_bridge.py` | 23 | your Agent's fields driving the new loop |
| `test_schema_prep.py` | 14 | refs, normalisation, dialect sanitization |

**Three real bugs were caught by tests during the build:**

1. The final answer was emitted as an event but never appended to history, so
   `result()` and any resumed run saw an empty answer.
2. The terminal packet was not last in the stream, so a consumer whose loop ended
   on it never saw the usage summary.
3. `max_context_tokens` was being forwarded to the provider as a wire parameter.

---

## What is still left

`bridge.unmapped()` returns this for a configured agent. Twenty-five features of
yours the new loop does not yet reproduce:

**Would change behaviour if lost** — wire these before switching the loop over:
`hooks`, `plugins`, `guardrails`, `lockdown`, `verifier`, `verify_before_stop`,
`rag`, `permissions` (policy evaluation, not just the callback),
`parallel_tool_execution`, `heal_tool_calls`.

**Quality of life** — port when convenient: `decision_llm`, `progress_summaries`,
`reminder`, `evict_prior_tool_outputs`, `media_parser`, `replan_interval`,
`router_policy`, `code_mode`, `persist_large_tool_outputs`,
`max_tool_output_group_chars`, `gate_unavailable_tools`.

**Superseded but not yet swapped**: `retry_policy` → `llms/throttle.py`,
`memory_store` → `tools/memory/`, `observability`/`trace_store` → tracing.

The honest position: the new loop is better on providers, schemas, prefix
stability, skills, MCP and accounting. It is behind yours on the ten features in
the first group. `spec_from_agent()` lets you run both and compare on real work
before deciding anything.

---

## Merge order

1. **`models.py`** — everything depends on it. Superset of yours; grep for
   `metadata["tool_call_id"]` reads and switch them to the fields.
2. **`llms/schema_prep.py`** — three lines in each adapter. Highest chance of
   being the live Gemma bug.
3. **`llms/parameters.py`** — the wire/host split.
4. **`prefix.py` + `prefix_rules.py`** — write the fingerprint test first, watch
   it fail, then fix the four things that move the prefix.
5. **`bridge.py`** — run your Agent's config through the new loop, compare.
6. Everything else, in whatever order the work demands.
