---
title: Apps — build once, use again
description: The agent writes a small program into the workspace, wires resources into it, and runs it — today and next week. Blueprints, bindings, artifacts and the authority model.
---

# Apps — build once, use again

An agent that answers a question leaves you with an answer. An agent that
builds an **app** leaves you with something you can run again tomorrow, with
different input, without a model in the loop.

```python
agent.run(
    "Create an app named revenue_by_region that totals `amount` per `region` "
    "from a CSV, then use it on bookings.csv."
)
```

```text
├─ Tool group: Listed blueprints, built the app revenue_by_region, used the app
│  ├─ list_blueprints                               completed
│  ├─ create_app                                    completed
│  └─ use_app                                       completed   62ms
│
├─ Artifact: Revenue by region
│  Page · /project/.shipit/apps/revenue_page/revenue.html
│
└─ Final answer
   EMEA 204,000 · AMER 494,000 · APAC 109,000.
```

<style>
.sad{--sad-line:rgba(128,120,112,.28);--sad-accent:#e8590c;--sad-ok:#2f9e44;
--sad-mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
border:1px solid var(--sad-line);border-radius:14px;overflow:hidden;
margin:28px 0;font-size:14.5px;line-height:1.6}
.sad-head{display:flex;align-items:center;gap:10px;padding:12px 16px;
border-bottom:1px solid var(--sad-line);font-weight:600;font-size:14px}
.sad-badge{display:inline-flex;align-items:center;gap:6px;border-radius:999px;
padding:4px 9px;font:11px/1 var(--sad-mono);color:var(--sad-ok);
background:rgba(47,158,68,.12)}
.sad-badge i{width:6px;height:6px;border-radius:50%;background:currentColor;
display:block;animation:sad-pulse 1.4s ease-in-out infinite}
.sad-body{padding:14px 16px}
.sad-body>*{opacity:0;animation:sad-in .45s ease-out forwards}
.sad-body>*:nth-child(1){animation-delay:.15s}
.sad-body>*:nth-child(2){animation-delay:.75s}
.sad-body>*:nth-child(3){animation-delay:1.35s}
.sad-body>*:nth-child(4){animation-delay:1.95s}
.sad-body>*:nth-child(5){animation-delay:2.55s}
.sad-body>*:nth-child(6){animation-delay:3.15s}
.sad-body>*:nth-child(7){animation-delay:3.75s}
.sad-body>*:nth-child(8){animation-delay:4.35s}
.sad-ask{margin:0 0 16px auto;width:fit-content;max-width:76%;
border-radius:14px;padding:9px 14px;background:rgba(128,120,112,.14)}
.sad-step{border-left:2px solid var(--sad-accent);padding:2px 0 2px 12px;
margin:12px 0;opacity:.9}
.sad-step b{display:block;font:10px/1.6 var(--sad-mono);letter-spacing:.08em;
text-transform:uppercase;color:var(--sad-accent);font-weight:500}
.sad-row{display:flex;gap:10px;margin:12px 0;align-items:flex-start}
.sad-row .sad-g{font:13px/1.5 var(--sad-mono);opacity:.55;width:16px;
flex:0 0 16px;text-align:center}
.sad-row .sad-l{flex:1;min-width:0}
.sad-row .sad-l small{display:block;font:12.5px/1.6 var(--sad-mono);opacity:.55}
.sad-row .sad-n{font:12px/1.6 var(--sad-mono);opacity:.5;white-space:nowrap}
.sad-card{display:flex;align-items:center;gap:12px;border:1px solid var(--sad-line);
border-radius:12px;padding:11px 14px;margin:14px 0}
.sad-card .sad-i{width:34px;height:34px;border-radius:9px;flex:0 0 34px;
background:rgba(128,120,112,.14);display:flex;align-items:center;
justify-content:center}
.sad-card b{display:block}
.sad-card small{opacity:.6;font-size:12.5px}
.sad-choices{display:flex;gap:16px;justify-content:flex-end;margin-top:10px;
font-size:13px;opacity:.75}
.sad-choices b{font-weight:600;opacity:1}
.sad-pre{font:12.5px/1.7 var(--sad-mono);white-space:pre;overflow-x:auto;
margin:0;padding:2px 0}
.sad-foot{border-top:1px solid var(--sad-line);padding:10px 16px;text-align:right;
font:12px/1.5 var(--sad-mono);opacity:.55}
@keyframes sad-in{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
@keyframes sad-pulse{0%,100%{opacity:1}50%{opacity:.25}}
@media (prefers-reduced-motion:reduce){
.sad-body>*{opacity:1;animation:none}.sad-badge i{animation:none}}
</style>
## What it looks like

<div class="sad">
  <div class="sad-head">Revenue analysis <span class="sad-badge"><i></i>Live</span></div>
  <div class="sad-body">
    <div class="sad-ask">Where did revenue land by region? Build me something I can send.</div>
    <div class="sad-row"><span class="sad-g">▣</span><span class="sad-l"><b>Listed blueprints, built the app revenue_dash</b> ›<small>✓ create_app · 2.0ms</small></span><span class="sad-n">2 tools · 4.1ms</span></div>
    <div class="sad-row"><span class="sad-g">▣</span><span class="sad-l"><b>Used the app revenue_dash</b> ›<small>✓ use_app · 61.4ms — {"totals": {"AMER": 494000, …}}</small></span><span class="sad-n">1 tool · 61.4ms</span></div>
    <div class="sad-card"><span class="sad-i">◍</span><span class="sad-l"><b>Revenue by region · Q2 FY2025</b><small>Page · Click to open</small></span><span style="opacity:.5">↗</span></div>
    <div>AMER leads at $494K, EMEA $204K, APAC $109K. The dashboard is yours to send.</div>
  </div>
  <div class="sad-foot">24,613 tokens · claude-opus-5</div>
</div>

Next quarter, that dashboard is one `store.run("revenue_dash", …)` away — no
model, no tokens, same numbers.

---

## The four tools

They ship as builtins, storing under `<project>/.shipit/apps`.

| Tool | What it does |
| --- | --- |
| `list_blueprints` | What can I start from, and what already exists? |
| `create_app` | Write one into the workspace — from a blueprint, from code, or both |
| `set_app_binding` | Wire a resource into it |
| `use_app` | Run it with input, and get its return value back |

The split is deliberate. Creating writes files; running executes code the
model wrote; wiring changes what an app is *allowed to reach*. Those are
different acts with different risks, and each gets its own row in the
transcript.

---

## What an app is

A directory with a manifest and an `app.py` exporting one function:

```python
# .shipit/apps/revenue_by_region/app.py
"""Total `amount` per `region`. Expects: path (str) — the CSV to read."""

import csv
from pathlib import Path


def run(input, env):
    with Path(input["path"]).open() as handle:
        rows = list(csv.DictReader(handle))

    totals = {}
    for row in rows:
        totals[row["region"]] = totals.get(row["region"], 0) + float(row["amount"])
    return {"totals": totals, "grand_total": sum(totals.values())}
```

Its module docstring is not decoration: when a run fails, `use_app` returns
it to the agent, so a `KeyError` becomes a correction rather than a guess.

---

## Blueprints

Starting points, copied into the new app:

| Blueprint | Produces |
| --- | --- |
| `report` | A Markdown table from records |
| `csv_summary` | Row counts from a CSV, optionally grouped by a column |
| `page` | A self-contained HTML page |
| `dashboard` | Headline cards and a bar chart, with a share-of-total table |
| `sheet` | A spreadsheet view — column letters, row numbers, flagged cells |
| `workflow` | A pipeline as boxes and connectors, with a live log |

```python
from shipit_agent.apps import AppStore

store = AppStore(".shipit/apps", workdir=".")
store.create("revenue_dash", title="Revenue by region", blueprint="dashboard")

store.run("revenue_dash", {
    "rows": rows,
    "title": "Revenue by region · Q2 FY2025",
    "subtitle": "warehouse · fy25_bookings",
    "output": "revenue.html",
})
```

Every blueprint is **self-contained**: no CDN, no web fonts, no `<script>`,
no `@import`. An artifact that needs the network is not one you can email
someone, and a test asserts it. Data is escaped, so a `<script>` in a cell
stays text.

`dashboard` guesses its own label and value fields, so a model that passes
only `rows` still gets a chart. `sheet` takes
`highlight={"Status": {"At risk": 1}}` to tint the cells someone needs to
look at.

---

## Running an app

```python
result = store.run("revenue_by_region", {"path": "bookings.csv"})

result.ok          # True
result.value       # {"totals": {...}, "grand_total": 807000.0}
result.stdout      # anything it printed
result.error       # traceback, if it raised
result.env_calls   # how many resource calls it made
```

`store.run()` rather than `run_app()`: the store knows **where** apps run —
the project the agent works in, not the app's own install directory. An app
given `path="bookings.csv"` means the file the agent has been working with.

---

## Artifacts

An app that writes a file declares it, and the run emits an event:

```json
{"type": "artifact_created", "path": "/project/revenue.html",
 "title": "Revenue by region", "kind": "Page", "tool": "use_app"}
```

Which every surface draws as a card — `Revenue by region · Page · Click to
open`. Kinds come from the extension: `Doc`, `Sheet`, `Page`, `Data`,
`Image`, `Deck`, `Code`, `PDF`, `Archive`, `File`.

Two rules keep the cards honest:

- **Only declared paths.** Scraping them out of tool text would invent an
  artifact from any string with a slash.
- **Only side-effecting tools.** `read_file` reports the path it read;
  treating that as an artifact would draw a card for a file you already had.

Any tool of your own gets cards for free by putting `path` (or `paths`) in
its result metadata.

---

## Authority

An app is **never more privileged than the agent that wrote it**.

- It runs in a **subprocess** with a scrubbed environment — no credentials.
- Its `env` reaches the parent over the same capability bridge
  [code mode](../tools/index.md) uses, so every resource call is
  gated by the permission engine, the contracts and the approval queue
  exactly as the equivalent tool call would be.
- It sees **only what it was wired**:

```python
store.bind("revenue_by_region", source="WAREHOUSE", as_name="DB")
```

```python
def run(input, env):
    rows = env.DB.call(query="SELECT region, amount FROM bookings")
```

An unwired binding is not merely refused — it is not in `env` at all. A test
asserts the app cannot even name it.

Children of an app get read-only tools by default, because a sub-agent that
can write is a side effect nobody reviewed.

---

## Running one without an agent

That is the point of building one:

```python
from shipit_agent.apps import AppStore

store = AppStore(".shipit/apps", workdir=".")
for month in ("q2.csv", "q3.csv"):
    print(month, store.run("revenue_by_region", {"path": month}).value)
```

No LLM call, no tokens, no drift.

---

## Contracts

| Tool | Read-only | Auto-approvable | Blocks the agent |
| --- | --- | --- | --- |
| `list_blueprints` | yes | — | — |
| `create_app` | no | yes (`fs.write`) | yes |
| `set_app_binding` | no | yes (`fs.write`) | yes |
| `use_app` | no | **never** | yes |

`use_app` runs code the model wrote, so the tag says nothing about what a
particular call does — it can never be auto-approved, and the agent always
waits for the result.

---

## See also

- [Automatic delegation](delegation.md)
- [The live UI panel](live-ui.md) — where artifact cards are drawn
- [Connections](connections.md) — what an app can be wired to
