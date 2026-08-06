# shipit-agent 1.2.0 — Watch it work

*6 August 2026*

One question, asked of every surface: **can you see what the agent did?**

1.1.0 gave a run a readable transcript. 1.2.0 makes a run report itself well
enough to draw a product from — and, where an agent used to answer and forget,
it can now leave something behind.

```bash
pip install --upgrade shipit-agent
```

Nothing in this release changes what an existing agent does. Every new
behaviour is a flag you turn on.

---

## Watch it work

### The live panel

```python
from shipit_agent.narrate import watch

answer = watch(agent, "Which accounts are at risk this quarter?")
```

An HTML card that **redraws in place** while the run happens — in a notebook,
or anywhere you can render HTML. Tokens land with a caret, tool rows appear in
flight and settle, each call folds away with the bytes it really returned, and
cards interrupt the flow when there is something for you to answer.

`render_chat_html(events)` gives you the same card for a finished run, as a
fragment you can drop into a page.

### The tree

```python
agent.run_live("Process the latest RSVP", style="tree")
```

```text
Agent started
│
├─ Understanding request
│  Read the inbox, check the guest list, then save.
│
├─ Tool group: Read 2 files
│  ├─ read_file                                     completed   4ms
│  └─ read_file                                     completed   6ms
│
├─ Decision
│  Guest was not found. Create a new RSVP record.
│
└─ Final answer
   RSVP successfully recorded.
```

On a terminal it redraws in place, keeping the trunk open — `├─ working…` —
until the run ends, because drawing the final corner early would claim the
agent had finished. `render_tree(events, detail=True)` opens every call up:
what it was given, and what came back.

### The timeline

```python
for step in stream_timeline(agent, prompt):
    await websocket.send_json(step)
```

The runtime's vocabulary is too fine for a UI. `timeline()` translates it into
the four things a UI actually draws, as plain JSON dicts — and does it
*causally*: a group's settled title arrives in its `completed` step, so a
client never has to undraw a row it already painted.

### Progress narration

```python
Agent(llm=opus, decision_llm=haiku, progress_summaries=True)
```

```text
▸ Reading guests.csv to collect the confirmed guests and their plus-ones.
← Dana Kim is confirmed with no plus-ones and Luis Marin is confirmed with one.
▸ Now reading venue.txt for the capacity to compare that headcount against.
← The venue seats 3.
```

A second, cheap model beside the run. It never reads the system prompt or
`reasoning_content`, and it is called with `tools=[]` — what it reports is
what an observer could have watched happen. A failure emits
`progress_summary_failed` and the run carries on.

**It adds one LLM call per step**, which is why it is off by default and why
`decision_llm` exists.

---

## Leave something behind

### Apps

```python
agent.run(
    "Create an app named revenue_by_region that totals `amount` per `region` "
    "from a CSV, then use it on bookings.csv."
)
```

Four new builtins — `list_blueprints`, `create_app`, `set_app_binding`,
`use_app` — that let the agent write a program into the workspace, wire
resources into it, and run it. Next quarter it is one call away:

```python
store.run("revenue_by_region", {"path": "q3.csv"})   # no model, no tokens
```

An app is a directory with `app.py` exporting `run(input, env)`. Two
properties are load-bearing, and both are tested:

- **Never more privileged than the agent that wrote it.** Subprocess, no
  credentials, and `env` crosses the same capability bridge code mode uses —
  so every resource call is gated by the permission engine, the contracts and
  the approval queue.
- **It sees only what it was wired.** An unwired binding is not refused; it is
  not in `env` at all.

Six blueprints ship, three of which produce something worth looking at:
`dashboard` (headline cards and a bar chart), `sheet` (column letters, row
numbers, flagged cells) and `workflow` (a pipeline as boxes and connectors).
All are self-contained — no CDN, no fonts, no script tags — because an
artifact that needs the network is not one you can send anyone.

### Artifact cards

A file a run produced is a card now, not a path in a log:

```text
├─ Artifact: Revenue by region · Q2 FY2025
│  Page · /project/revenue.html
```

Any tool that declares a path in its result metadata gets one, in the panel,
the tree and the timeline.

---

## Reach further

### Automatic delegation

```python
Agent(llm=llm, tools=[read_file, glob_files], delegation=True)
```

`sub_agent` is not in that list, and the prompt below never says *delegate*:

```python
agent.run("Summarize each of the twelve incident reports in reports/.")
```

Three parts, each measured rather than assumed: the tool is **guaranteed to
exist**, built from the agent's own LLM and its read-only tools; the task is
**sized by a model** with a structural count as the floor; and the directive
lands on the **task**, not the system prompt.

That last one is the whole feature. Against Gemma 4 with three reports to
summarize: in the system prompt, **0** delegations; the same words on the
task, **6**.

It never delegates behind the model's back — the runtime cannot know which
parts of a task are independent, and guessing would spawn children working on
halves of one problem.

### Connections you can answer

The registry knew what was connected. Nothing turned "I need Slack" into
something a user could act on. Now the agent's request emits
`connection_requested`, the panel draws a card with the **reason** — a person
deciding whether to hand over an account is answering *why*, not *what* — and:

```python
registry.resolve("slack", accepted=True, credential=token, by="you")
```

closes the loop. The credential is stored, so the next state check reads
CONNECTED rather than asking again for something you just gave it.

---

## Fixed

- The async runtime's `tool_completed` was missing `tool` and `call_id`, so
  its transcript could only guess which outcome belonged to which call.
- `read_file` produced artifact cards for files it merely read.
- An artifact card split the tool group that made it.
- `run_live()` raises on an unknown `style` rather than silently rendering the
  default view.
- `write_transcript()` accepted `title` and `model` but dropped `prompt`.
- `use_app` wrote a file and never declared it.
- Apps ran in their own install directory, so `path="guests.csv"` found
  nothing.
- `deny=["*"]` denying allow-listed tools is documented where you meet it.

---

## Upgrading

Nothing to change. Both new behaviours are opt-in:

```python
Agent(progress_summaries=True, decision_llm=cheap_llm)   # narration
Agent(delegation=True)                                    # sub-agents
```

The app tools ship as builtins, so `Agent.with_builtins(...)` gains
`create_app` / `use_app` / `set_app_binding` / `list_blueprints`. They are
gated by the same permission engine as everything else; if you allow-list
tools explicitly, they are simply absent until you name them.

---

## Known limits

Stated rather than hidden:

- **The async runtime has no progress narration and no tool groups.** The sync
  loop got them; `AsyncAgentRuntime` did not. The two loops are supposed not
  to drift, and here they do.
- **`Agent.decision_llm` sits second in the field order**, so
  `Agent(llm, "my prompt")` positionally assigns the prompt to it. Everything
  in-repo uses keywords; a positional caller would be surprised.
- **Resource-triggered runs** — the one real gap against the reference design.
  An agent you can ask, but not yet one that reacts to an inbox. See
  `docs/design/cloudflare-os-gap.md`.

---

## Verifying it yourself

```bash
pytest tests/ -q          # 3,082 passing
ruff check shipit_agent/
jupyter lab notebooks/76_apps_and_analysis.ipynb
```

Notebooks 74, 75 and 76 ship with their outputs committed, run against
`bedrock-mantle/google.gemma-4-26b-a4b` — so what you read is what actually
ran, including the parts where the model got it wrong first.
