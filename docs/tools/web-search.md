---
title: web_search
description: Search the web from an agent. DuckDuckGo works with no key; Brave, Serper and Tavily take an API key; Playwright drives a real browser; or plug in your own provider.
---

# `web_search`

`web_search` gives an agent current information from the web: titles, URLs and snippets for a query. It can run several independent queries at once, and pairs with `open_url` to read the pages it finds.

`Agent.with_builtins()` includes it, searching DuckDuckGo, which needs no API key.

## Choose a provider

| Provider | Name | Needs | Notes |
| --- | --- | --- | --- |
| DuckDuckGo | `duckduckgo` (or `ddg`) | nothing | The default. Reads DuckDuckGo's HTML results. |
| Brave | `brave` | an API key | Brave Search API. |
| Serper | `serper` | an API key | Google results through serper.dev. |
| Tavily | `tavily` | an API key | Search built for agents. |
| Playwright | `playwright` | `playwright` installed | Searches in a real headless browser. |

Pick one for the built-in tools:

```python
import os

from shipit_agent import Agent
from shipit_agent.llms import build_llm_from_env

agent = Agent.with_builtins(
    llm=build_llm_from_env(),
    web_search_provider="tavily",
    web_search_api_key=os.environ["TAVILY_API_KEY"],
)
print(agent.run("What changed in Python 3.13? Cite your sources.").output)
```

`web_search_config` passes provider settings: `timeout` (seconds) for DuckDuckGo, Brave, Serper and Tavily, `user_agent` for DuckDuckGo, and `timeout_ms` for Playwright.

```python
from shipit_agent import Agent
from shipit_agent.llms import build_llm_from_env

agent = Agent.with_builtins(
    llm=build_llm_from_env(),
    web_search_provider="duckduckgo",
    web_search_config={"timeout": 8.0, "user_agent": "my-research-bot/1.0"},
)
```

A paid provider without a key fails when the agent is built, with a clear message, not halfway through a run:

```text
ValueError: Tavily search requires `api_key`.
```

## Use the tool on its own

`WebSearchTool` is an ordinary tool, so you can give it to an `Agent` with other tools, or call it directly:

```python
from shipit_agent import Agent, WebSearchTool
from shipit_agent.llms import build_llm_from_env

search = WebSearchTool(provider="duckduckgo", max_queries=4)
agent = Agent(llm=build_llm_from_env(), tools=[search])
```

| Argument | Default | What it does |
| --- | --- | --- |
| `provider` | `"duckduckgo"` | A provider name, or a provider object. |
| `api_key` | `None` | The key for Brave, Serper or Tavily. |
| `provider_config` | `None` | Provider settings, as above. |
| `max_queries` | `4` | Most queries the model may run in one call. |
| `max_workers` | `4` | How many of those run at the same time. |
| `name` | `"web_search"` | The tool's name, if you want two search tools. |

The model calls it with one `query`, or a `queries` list of independent searches that run concurrently, and an optional `max_results` (default 5). Each result has a `title`, `url` and `snippet`.

## Search providers directly

`build_search_provider()` returns the same provider objects the tool uses, which is handy for scripts and tests:

```python
from shipit_agent import build_search_provider

provider = build_search_provider("duckduckgo")
for hit in provider.search("shipit agent python", max_results=3):
    print(hit["title"], "→", hit["url"])
```

The classes are exported too: `DuckDuckGoSearchProvider`, `BraveSearchProvider`, `SerperSearchProvider`, `TavilySearchProvider` and `PlaywrightSearchProvider`.

## Your own provider

A provider is any object with a `name` and a `search(query, max_results=5)` method that returns a list of dicts with `title`, `url` and `snippet`. Pass it where a provider name goes:

```python
from shipit_agent import Agent, WebSearchTool
from shipit_agent.llms import build_llm_from_env


class InternalWikiSearch:
    name = "wiki"

    def search(self, query: str, max_results: int = 5) -> list[dict]:
        hits = wiki_client.search(query, limit=max_results)
        return [{"title": h.title, "url": h.url, "snippet": h.summary} for h in hits]


agent = Agent(llm=build_llm_from_env(), tools=[WebSearchTool(provider=InternalWikiSearch())])
```

## See also

- [Research brief](research-brief.md): search, skim the top pages and return a cited brief in one call
- [Tools](../agent/with-tools.md): every built-in tool and how to choose them
