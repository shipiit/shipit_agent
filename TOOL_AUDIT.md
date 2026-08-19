# Tool audit

Your `shipit_agent/tools/` has ~70 tool packages. That is not 70 capabilities —
it is roughly 12 capabilities with duplicates, plus 25 SaaS connectors that
should not be built-in tools at all.

The cost is not disk space. **Every bound tool costs its full JSON Schema on
every turn, forever.** Past a dozen or so, a second cost appears: two tools that
overlap make every relevant call a coin flip, and the model picks wrong roughly
half the time. A smaller, sharper set is more capable, not less.

---

## The seven that stay bound

`toolkit/core.py` — one job each, no overlap, contracts enforced.

| Tool | Replaces | Contract added |
|---|---|---|
| `bash` | `bash`, `code_execution`, `execute_code` | Timeout is a result; exit status always reported; output bounded |
| `read_file` | `file_read`, `file_extract`, `workspace_files` | Records the read, so `edit_file` can check freshness |
| `write_file` | `file_write` | **Refuses to clobber** an existing file |
| `edit_file` | `edit_file`, `notebook_edit` | Exact, unique match or refuse; read-before-write enforced |
| `glob` | `glob_search` | Skips `node_modules`/`.git`/`dist`; newest first |
| `grep` | `grep_search` | Grouped by file, line-numbered, bounded, glob-restrictable |
| `todo` | `todo`, `planner`, `thought_decomposition`, `decision_matrix` | Flags split focus; lives in the volatile tail, not the prefix |

```python
from shipit_agent import Agent, core_tools
agent = Agent(llm=llm, model="google.gemma-4-31b", tools=core_tools("."))
```

---

## Merge — same capability, several implementations

Each of these is one tool wearing several names. Every duplicate is a schema the
model pays for and a decision it can get wrong.

| Keep | Fold in | Why they are the same thing |
|---|---|---|
| `bash` | `code_execution`, `execute_code` | All three run code in a subprocess. Language selection is an argument, not a tool. |
| `read_file` | `file_extract`, `workspace_files` | Format handling belongs inside the reader, keyed on extension. |
| `edit_file` | `notebook_edit` | A notebook is a JSON file; cell addressing is an argument. |
| `ask_user` | `ask_user_async`, `human_review`, `confirmation` | One pause-for-a-human tool. Sync vs async is a runtime concern, not a model-visible one. |
| `sub_agent` | `deep_research`, `research_brief`, `evidence_synthesis` | All three are "delegate an investigation, get a summary". A prompt argument covers the differences. |
| `todo` | `planner`, `thought_decomposition`, `decision_matrix` | All four ask the model to write structure it then follows. |
| `web_search` | `open_url`, `download_file` | Search returns URLs; fetching one is a mode, not a separate capability. |
| `document_builder` | `artifact_builder`, `present_file`, `dashboard_render` | One "produce a file" tool with a format argument. |

**Net effect: 24 tools → 8.**

---

## Move to MCP — the whole SaaS surface

`confluence`, `figma`, `github`, `gitlab`, `gmail`, `google_calendar`,
`google_drive`, `google_sheets`, `hubspot`, `jira`, `linear`, `linkedin`,
`notion`, `salesforce`, `slack`, `sql`, `stripe`, `zendesk`, `custom_api`,
`connections`, `apps`, `webhook_payload` — **22 packages.**

Every one of these is an HTTP client with auth, and every one costs schema
tokens on every turn of every run, whether or not the task touches it. An agent
with Jira, Slack and Salesforce bound is paying for all three to answer a
question about a Python file.

Now that `mcp_bridge.py` exists, they belong behind it:

```python
agent = Agent(
    llm=llm,
    model="google.gemma-4-31b",
    tools=core_tools("."),
    mcp_servers=[jira, slack, github, salesforce, ...],
    mcp_connect=connect,
)
```

What changes:

- **Described, not connected.** Attachment reads cached descriptors. Nothing
  spawns or dials until a tool is actually called.
- **Deferred past a budget.** Servers beyond `max_eager_tools` sit behind
  `tool_search`. Twenty connectors at ten tools each is two hundred schemas; the
  bridge shows the cheap ones and holds the rest for a search that costs one
  round-trip and is paid once.
- **A broken connector degrades itself.** An expired token or a dead service
  contributes zero tools and says so, and the run continues.
- **Server instructions reach the model** — the MCP field your code reads at
  `mcp.py:646` and never uses.

You also stop maintaining 22 API clients. When Jira changes its API, that is the
MCP server's problem.

**Net effect: 22 built-in tools → 0 bound, all still reachable.**

---

## Remove

| Tool | Why |
|---|---|
| `give_up` | The model can say it cannot proceed in prose. A tool for it teaches the model that quitting is a supported action, and it takes that suggestion. |
| `describe_binding` | Introspection for the developer, not the model. `Agent.describe_tools()` covers it off the hot path. |
| `prompt` | A tool that returns a prompt is a prompt. It belongs in the system prompt or a skill. |
| `availability` | Internal gating logic, not a capability. Already handled by `gate_unavailable_tools`. |
| `computer_use` / `playwright_browser` / `_playwright` | Keep **one** browser path. Two is a coin flip on every browser task, and each carries a heavy dependency. Recommend keeping `playwright_browser` and dropping `computer_use` unless screen control is a product requirement. |

**Net effect: −5, plus one browser implementation retired.**

---

## Keep as specialist tools, bound only when relevant

Not core, but genuine capabilities with no overlap. Bind them per-agent, or defer
them:

`pdf`, `vision`, `image_generate`, `video_generate`, `text_to_speech`,
`git_ops`, `memory`, `verifier`, `deep_research` (as the delegating variant),
`tool_search` (now provided by `discovery.py`), `load_skill` (now provided by
`skills/catalog.py`).

```python
agent = Agent(..., tools=core_tools(".") + [pdf, vision], deferred_tools=["vision"])
```

---

## The arithmetic

| | Before | After |
|---|---|---|
| Tool packages | ~70 | ~20 |
| **Bound by default** | ~70 | **7–9** |
| Schema tokens per turn | ~25,000 | ~3,000 |
| Reachable capability | 70 | 70 (rest via MCP + `tool_search`) |

Roughly **22,000 tokens saved on every single turn**, with nothing lost — and on
a model with implicit prompt caching, a smaller stable prefix is also a prefix
far more likely to stay cached.

---

## Migration order

1. **Adopt `core_tools()`** — replaces 12 packages, adds the contracts. Nothing
   else depends on it.
2. **Move SaaS behind MCP.** Biggest token win. Do the three most-used
   connectors first and measure the prefix before and after.
3. **Merge the duplicates.** Mechanical, and each merge is independently
   testable.
4. **Delete the five.** Last, so nothing is removed while something still calls
   it.

Run `Agent.preflight()` before and after each step — it reports prefix tokens as
a share of the input budget and warns when the fixed prefix is eating the
context before the conversation has started.

---

## On the skills question

I did not copy `/mnt/skills/` into this repo. Those are Anthropic-authored works
— the `docx` skill alone bundles the ISO/IEC 29500 OOXML schemas — and shipping
them under your library's license would be redistributing someone else's
content. That is a real problem for something you intend to publish.

What transfers is the architecture, and that is already built in
`skills/authoring.py`:

- **A skill is a folder** with `SKILL.md` at its root: YAML front-matter plus a
  markdown body.
- **The description is what the model sees; the body is what it gets.**
  Descriptions sit in the prompt for every skill, always, so they are one line.
  Bodies load on demand.
- **`references/` files go one level further out.** A body that inlines every
  edge case is paid in full on every load; one that says "for VAT edge cases,
  read `references/vat-rules.md`" is paid only when that case appears.
- **`scripts/` are run, not read.** Deterministic work belongs in code, not in
  tokens the model has to re-derive.

Three original skills ship in `skills/`: `code-review`, `release-notes`,
`incident-report`. Measured, they cost 459 characters of catalog against 4,985
characters of body — and that ratio only improves as the library grows.

Writing more is the cheapest capability you can add: a skill is a markdown file,
it needs no code, and `discover_skills()` picks it up from any directory you
point at.
