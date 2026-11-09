---
title: deep_research
description: Research a topic from several angles in one call. Multiple searches, deduplicated sources, the top pages fetched, and a digest with citations.
---

# `deep_research`

`web_search` answers one query. `deep_research` covers a topic: it runs several searches from different angles, removes duplicate sources, fetches the top pages and returns one digest with numbered citations.

## Use it

```python
from shipit_agent import Agent, DeepResearchTool
from shipit_agent.llms import build_llm_from_env

research = DeepResearchTool(max_sources=8, fetch_top=4, per_page_chars=3000)
agent = Agent(llm=build_llm_from_env(), tools=[research])
print(agent.run("Compare uv and poetry for a monorepo in 2026. Cite sources.").output)
```

| Argument | Default | What it does |
| --- | --- | --- |
| `max_sources` | `8` | Most distinct sources kept |
| `fetch_top` | `4` | How many of them are opened and read |
| `per_page_chars` | `3000` | How much of each page goes into the digest |
| `user_agent` | `None` | The User-Agent sent when fetching |

The model calls it with a `topic`, and optionally its own `queries` list to replace the default multi-angle sweep.

## See also

- [Web search](web-search.md) for single searches and providers
- [Research brief](research-brief.md) for a shorter cited brief
