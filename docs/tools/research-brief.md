---
title: research_brief
description: One-call research primitive. Web search + top-page skim + structured brief with numbered citations. Good for the researcher, product-manager, marketing, and sales specialists.
---

# `research_brief`

A single-call research primitive. You hand it a query; it searches
the web, optionally opens each top result, and returns a structured
brief with numbered citations — ready to paste into a deliverable.

> **TL;DR** — `ResearchBriefTool().run(ctx, query="uv vs poetry 2026")`
> returns a `Research brief — …` block with 3–10 sources, titles,
> URLs, and snippets. Add `deep=True` to also fetch each page for a
> richer summary.

---

## Why it exists

Any "get me the gist of X" agent task used to require three tool calls
— search, then open-url repeatedly, then stitch the summary. Each
round-trip burns tokens on remembering the composition.

`research_brief` is one tool with one schema. The model only has to
learn *one* name, and the brief shape stays stable across goals so
prompts referring to `[1]`, `[2]` cite reliably.

---

## Parameters

| Param | Default | Notes |
| --- | --- | --- |
| `query` | — | Required. The research topic. |
| `max_sources` | `5` | 1–10. More sources = more tokens. |
| `deep` | `False` | When `True`, fetches each source page and appends a ~600-char summary. |

---

## Quickstart — shallow brief

```python
from shipit_agent.tools.research_brief import ResearchBriefTool
from shipit_agent.tools.base import ToolContext

research = ResearchBriefTool()
out = research.run(
    ToolContext(prompt="demo"),
    query="uv vs poetry Python package manager 2026",
    max_sources=4,
)
print(out.text)
```

Output:

```
Research brief — uv vs poetry Python package manager 2026

[1] uv: An extremely fast Python package installer (Astral)
    https://astral.sh/blog/uv
    uv is a Rust-based replacement for pip and pip-tools, …

[2] Poetry 1.8 release notes
    https://python-poetry.org/blog/poetry-1.8
    Poetry 1.8 ships an in-process installer that cuts install times…

[3] HN discussion: switching from poetry to uv
    https://news.ycombinator.com/item?id=...
    Long thread on migration; key complaints were lock file stability…

[4] Real Python: uv — should you switch?
    https://realpython.com/uv/
    Walkthrough with benchmarks against pip and poetry.

Citation format: [1], [2], … as used above.
```

---

## Deep mode — fetch the pages too

```python
out = research.run(
    ToolContext(prompt="demo"),
    query="SQLite vs DuckDB for analytics workloads",
    max_sources=3,
    deep=True,
)
```

Each source gets its first ~600 characters of readable text appended,
so the agent can cite specific claims without making a follow-up
`web_fetch` call.

> **Cost note** — deep mode fans out to N+1 HTTP requests (one
> search + one per source). Use sparingly on large batches.

---

## Using it with a specialist

The `researcher` specialist was designed around exactly this tool:

```python
from shipit_agent import Agent
from shipit_agent.agents import AgentRegistry
from shipit_agent.tools.research_brief import ResearchBriefTool

researcher_def = AgentRegistry.default().get("researcher")
researcher = Agent(
    llm=llm,
    prompt=researcher_def.prompt,
    tools=[ResearchBriefTool()],
    max_iterations=15,
    name=researcher_def.name,
)
researcher.run("Brief me on recent Python dependency tools with citations.")
```

Same pattern for `product-manager` when evaluating competitive
landscape, or `marketing-writer` when looking up proof points.

---

## Autopilot — multi-source deliverable

For a long-form brief you'd paste into a report:

```python
from shipit_agent import Goal
from shipit_agent.autopilot import Autopilot, BudgetPolicy

autopilot = Autopilot(
    llm=llm,
    goal=Goal(
        objective="Produce a two-page digest on local LLM tooling in 2026.",
        success_criteria=[
            "Covers ollama, llama.cpp, mlx",
            "Cites at least 3 sources per ecosystem",
            "Ends with a recommendation table",
        ],
    ),
    tools=[ResearchBriefTool()],
    budget=BudgetPolicy(max_iterations=6, max_seconds=600),
    critic=True, artifacts=True,
)
result = autopilot.run(run_id="local-llm-tooling-2026")
```

The critic verifies every criterion before concluding; artifacts
captures the final markdown deliverable.

---

## Under the hood

`research_brief` uses a **tiny DuckDuckGo HTML scraper** — no API key,
no sign-up. Subclass and override `_search(query, limit)` if you want
to swap in a paid SERP API (Brave, SerpAPI, Google CSE):

```python
class BraveResearch(ResearchBriefTool):
    def _search(self, query, limit):
        # ... call Brave Search API, return list[_Source]
        ...
```

Fetches have a 2 MB cap per page, a 20-second timeout, and pretend to
be a modern browser:

```
User-Agent: Mozilla/5.0 (compatible; shipit-agent/1.0; +https://docs.shipiit.com/)
```

Swap via `ResearchBriefTool(user_agent="...")` if your target site is
picky.

---

## Limits to know

- **No API auth** — public web only. Paywalled content won't appear in
  the brief.
- **Rate-limited by the SERP** — DuckDuckGo will throttle large batches.
  For >20 queries, subclass with a paid SERP backend.
- **Skims, doesn't synthesize** — the brief is verifiable raw material;
  the *interpretation* should come from the calling agent.

---

## Notebook

- `notebooks/42_power_tools_computer_use_hubspot_research.ipynb` — full walkthrough.
- `notebooks/40_specialists_developer_debugger_researcher.ipynb` — researcher + research_brief in Autopilot.
