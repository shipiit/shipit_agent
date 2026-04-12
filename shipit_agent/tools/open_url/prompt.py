from __future__ import annotations

OPEN_URL_PROMPT = """

## open_url
Fetch and read web page content. Extracts text and optionally captures a screenshot.

**When to use DIRECTLY (no web_search first):**
- User provides a specific URL — use `open_url` immediately, do NOT run `web_search`
- A URL was mentioned in conversation context or found in project files
- Reading API documentation, GitHub repos, or known reference pages

**When to use AFTER web_search:**
- Open the most promising search result pages to get full content
- You can pass multiple URLs at once for efficiency
- Verify claims by reading the actual source page

**Decision tree:**
1. Have a specific URL? → `open_url` (this tool)
2. Need to find the right URL? → `web_search` first, then `open_url`
3. Page needs JavaScript rendering? → use `playwright_browse` instead

**Rules:**
- Do not fabricate URLs — use URLs from search results, user input, or project files
- For JavaScript-heavy pages (SPAs, dynamic apps), prefer `playwright_browse`
- Extract and summarize the relevant content — do not dump the entire raw page
""".strip()
