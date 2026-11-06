"""What the model is told about the web search tool: when to use it and how."""

from __future__ import annotations

WEB_SEARCH_PROMPT = """
Search the web for current information: recent releases, advisories, errors,
prices, news.
- Search for the exact error, function or term, one topic per query.
- Open the most promising results with `open_url` to read them in full.
- Do not guess URLs; when the user gives one, open it directly.
""".strip()
