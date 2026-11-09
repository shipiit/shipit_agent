---
title: render_dashboard
description: Render a structured life / finance / research one-pager as a single self-contained HTML document — metrics, growth chart, timeline, comparison cards, phase stack, verdict.
---

# `render_dashboard`

Produce polished life / finance dashboards an LLM
would otherwise hand-write — cards, timeline, bars, chart, verdict —
from a structured JSON spec. The tool returns a single self-contained
HTML document (inline CSS; Chart.js via CDN only when a chart section
is present) and registers it as an artifact so `Autopilot` picks it up
without glue code.

> **TL;DR** — hand the tool a `title`, a `subtitle`, and a list of
> typed `sections`. Each section renders to a different visual block
> (metric tile grid, line chart, horizontal bars, event timeline,
> trait cards, lifestyle grid, phase stack, callout, verdict).

## When to use

- The user asks for a **"dashboard"**, **"one-pager"**, **"life
  vision"**, **"finance summary"**, **"future timeline"**.
- Your answer naturally splits into distinct visual treatments —
  KPI tiles + a growth chart + a phase stack reads far better than
  eight paragraphs of prose.
- You want the output to be shareable: a self-contained HTML file
  renders in any browser or email client, no backend required.

## Quick example

```python
from shipit_agent.tools.dashboard_render import render_dashboard

html = render_dashboard({
    "title": "Rahul — Complete Life Vision 2026–2035",
    "subtitle": "Kundli + Hast Rekha · April 2026",
    "lang": "hi",
    "sections": [
        {"type": "metrics", "title": "Life Snapshot", "columns": 4, "items": [
            {"label": "Age", "value": "30", "sub": "Best phase ahead"},
            {"label": "Dasha", "value": "शुक्र", "sub": "until 2043"},
            {"label": "Ventures", "value": "4", "sub": "ShipIt primary"},
            {"label": "Sadhesati", "value": "Peak", "sub": "ends June 2027",
             "color": "#ba7517"},
        ]},
        {"type": "line_chart", "title": "Income growth 2026–2035",
         "labels": [str(y) for y in range(2026, 2036)],
         "values": [20, 35, 55, 70, 85, 95, 110, 140, 165, 190],
         "color": "#185fa5"},
        {"type": "bars", "title": "Income sources", "items": [
            {"label": "Enterprise licensing", "pct": 88, "color": "#185fa5"},
            {"label": "SaaS subscriptions",   "pct": 75, "color": "#1d9e75"},
        ]},
        {"type": "verdict", "title": "Final verdict",
         "text": "You are on a **self-made extraordinary journey**. "
                 "June–August 2026 is the turning point."},
    ],
})

open("life_vision.html", "w").write(html)
```

## As a tool handed to an agent

```python
from shipit_agent import Agent
from shipit_agent.llms import build_llm_from_settings
from shipit_agent.tools.dashboard_render import DashboardRenderTool

agent = Agent(
    llm=build_llm_from_settings(provider="bedrock"),
    prompt=(
        "You are a life-planning assistant. When the user asks for a "
        "visual dashboard, call render_dashboard with a well-structured spec."
    ),
    tools=[DashboardRenderTool()],
)

result = agent.run(
    "Give me a visual dashboard of my finance + love life + career "
    "for 2026 through 2035. Use timeline, cards, and a chart."
)
```

The tool call returns a `ToolOutput` whose `metadata` is shaped as an
artifact envelope — `{"artifact": True, "kind": "file", "name": ...,
"content": html, "media_type": "text/html"}` — so a wrapping
`Autopilot(..., artifacts=True)` auto-captures it:

```python
from shipit_agent import Goal
from shipit_agent.autopilot import Autopilot, BudgetPolicy

autopilot = Autopilot(
    llm=llm,
    goal=Goal(
        objective="Produce a life-vision dashboard for the user",
        success_criteria=["HTML dashboard produced with at least 6 sections"],
    ),
    tools=[DashboardRenderTool()],
    budget=BudgetPolicy(max_iterations=3, max_dollars=0.5),
    artifacts=True,
)
result = autopilot.run(run_id="life-vision")
for a in result.artifacts:
    print(a["kind"], a["name"])    # file life-vision.html
```

## Section types

| `type` | What it renders |
| --- | --- |
| `metrics` | 2 / 3 / 4-column tile grid — KPIs with label, value, sub-line |
| `line_chart` / `bar_chart` | Chart.js line or bar graph from `labels` + `values` |
| `bars` | Ranked horizontal percentage bars |
| `timeline` | Dated events with dot, period, head, desc, optional badge tags |
| `cards` | 2 or 3-column trait cards (each row has a dot, strong label, text) |
| `lifestyle_grid` | 3-column icon tiles (emoji icon + title + one-liner) |
| `phases` | Vertical phase stack with colored left border |
| `callout` | Single highlight box with heading + body |
| `verdict` | Green summary box, supports inline `**bold**` markdown |

Unknown section types are silently skipped so you can add experimental
sections without breaking older renderers.

## Color and XSS

All user-provided strings are HTML-escaped. Colors must be hex
(`#1d9e75`) — anything else falls back to the default gray so an
attacker who controlled the spec can't inject CSS into the inline
`style=` attribute. Badge color variants are a fixed allow-list:
`blue` · `green` · `amber` · `purple` · `gray` · `red`.

## Notebook

See [`notebooks/46_dashboard_render_tool_and_litellm.ipynb`](https://github.com/shipiit/shipit_agent/blob/main/notebooks/46_dashboard_render_tool_and_litellm.ipynb)
for a runnable end-to-end example including LiteLLM / Bedrock / proxy
wiring and Autopilot artifact surfacing.

## Related

- [Artifacts](../autopilot/artifacts.md) — how `ArtifactCollector` picks up tool outputs.
- [LiteLLM proxy](../guides/litellm-proxy.md) — bring your own LiteLLM URL + key.
- [Tool catalog](index.md) — every built-in tool.
