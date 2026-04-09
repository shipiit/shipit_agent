from __future__ import annotations

OPEN_URL_PROMPT = """

## open_url
Fetch and read web page content (renders JavaScript, extracts text + screenshot).

**When to use DIRECTLY (no web_search first):**
- User provides a specific URL — use open_url immediately, do NOT run web_search
- A URL was mentioned in conversation context

**When to use AFTER web_search:**
- Open the most promising result pages to get full content
- You can pass multiple URLs at once for efficiency
""".strip()
