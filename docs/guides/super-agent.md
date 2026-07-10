# The super agent — every sector, clean logs, real deliverables

shipit ships everything needed to build a Claude-Code-grade agent for any
role — finance, marketing, engineering, design, research, sales, support —
with five capabilities that compose cleanly. All of them work with **every
supported LLM provider** (Anthropic, OpenAI, Bedrock, Gemini, Vertex, Groq,
Together, Ollama, …).

## 1. Sector specialists in one line — `Agent.for_role`

40+ prebuilt role definitions (prompt, goal, backstory, tool selection,
iteration budget) become runnable agents with one call:

```python
from shipit_agent import Agent

agent = Agent.for_role("finance-analyst", llm=llm)
agent = Agent.for_role("marketing-writer", llm=llm)
agent = Agent.for_role("researcher", llm=llm)
agent = Agent.for_role("generalist-developer", llm=llm)
```

The definition's `tools` list selects matching built-ins automatically —
the finance analyst gets `sql`, `google_sheets`, `pdf`, `render_dashboard`,
`stripe`, and `build_document`; the developer gets file ops, `bash`, and
test runners. Unknown ids raise a `ValueError` with did-you-mean
suggestions. Browse the roster:

```python
from shipit_agent.agents import AgentRegistry

for d in AgentRegistry.default().list_all():
    print(d.id, "—", d.category)
```

Pass extra `tools=[...]`, a custom `prompt=`, or any other `Agent` kwarg to
customize.

## 2. Prebuilt MCP catalog — `connect_mcp`

Connect well-known MCP servers by name instead of hand-writing transport
commands:

```python
from shipit_agent import Agent, connect_mcp

github = connect_mcp("github")                      # needs GITHUB_TOKEN
files  = connect_mcp("filesystem", args=["/my/project"])
db     = connect_mcp("postgres", args=["postgresql://localhost/app"])

agent = Agent.with_builtins(llm=llm, mcps=[github, files, db])
```

The catalog covers `filesystem`, `github`, `gitlab`, `slack`, `postgres`,
`sqlite`, `puppeteer`, `brave-search`, `fetch`, `memory`, `sentry`, and
`google-maps`. Each entry validates required env vars and the launcher
binary (`npx` / `uvx`) **before** starting, so failures are one clear
message instead of a cryptic subprocess error. List everything with
`list_mcp_catalog()`.

MCP tool calls that fail at runtime (server down, timeout) now return a
readable tool result the model can react to — they no longer crash the run.

## 3. Polished documents — the `build_document` tool

Every `with_builtins` / `for_role` / `for_project` agent can produce
finished, shareable files — PDF reports, Excel workbooks, Word documents,
PowerPoint decks, and styled HTML:

```python
result = agent.run(
    "Build the Q2 close: a P&L workbook with a net-income formula, "
    "and a 5-slide summary deck for the board."
)
```

The tool structures content as `title` + `sections` (heading, body,
bullets, tables) or `sheets` for Excel, and the renderers handle the
polish: accent-colored headings, zebra-striped tables, bold frozen header
rows, auto-sized columns. Excel cells starting with `=` are written as
**live formulas**. Renderers use optional dependencies (`reportlab`,
`openpyxl`, `python-docx`, `python-pptx`) and reply with the exact
`pip install` fix when one is missing; HTML output has zero dependencies.

## 4. Clean tool-call logs — `format_activity`

Every event now carries a timestamp, and tool events carry the tool name
and `duration_ms`. Render a run as Claude-Code-style tool cards:

```python
from shipit_agent import format_activity

result = agent.run("Close Q2 and hand me the workbook.")
print(format_activity(result))
```

```
⚙ build_document(kind="xlsx", title="Q2 Close", …) ✓ 228ms
  └ Created XLSX 'Q2 Close' → .shipit_workspace/documents/q2_close.xlsx (5,108 bytes)
✔ run completed · 1 tool call · 2 iterations
```

For live UIs, `format_event_line(event)` renders each streamed event as it
arrives (returns `None` for non-user-facing events):

```python
from shipit_agent import format_event_line

for event in agent.stream("..."):
    line = format_event_line(event)
    if line:
        print(line)
```

## 5. Scheduled jobs — `AgentScheduler`

Cron for agents. Register prompts to run every N seconds, daily at a wall
time, or on a cron expression:

```python
from shipit_agent import Agent, AgentScheduler

agent = Agent.for_role("marketing-writer", llm=llm)
sched = AgentScheduler(agent)

sched.add("Draft today's product-update post from merged PRs.", at="09:00")
sched.add("Summarize new error logs.", every=3600, on_result=notify)
sched.add("Weekly competitor brief.", cron="0 8 * * 1")   # pip install croniter

sched.run_forever()   # blocks, firing jobs as they come due
```

Jobs support `on_result` callbacks, `max_runs` caps, and `session_id` for
persistent-conversation runs. The scheduler is **in-process** — jobs live
as long as your process. For durable scheduling, drive `run_pending()`
from OS cron/systemd. The `clock`/`sleep` hooks are injectable, so
schedules are unit-testable with zero real waiting.

## Putting it together

```python
from shipit_agent import Agent, AgentScheduler, connect_mcp, format_activity

agent = Agent.for_role(
    "finance-analyst",
    llm=llm,
    mcps=[connect_mcp("postgres", args=["postgresql://localhost/finance"])],
)

sched = AgentScheduler(agent)
sched.add(
    "Pull this month's ledger, reconcile it, and build the close package: "
    "P&L workbook + board deck.",
    at="07:00",
    on_result=lambda r: print(format_activity(r.agent_result)),
)
sched.run_forever()
```

One sector specialist, live database access over MCP, polished Excel and
PowerPoint out, readable logs, on a schedule — with any LLM provider.
