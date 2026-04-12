from __future__ import annotations

PLAYWRIGHT_BROWSER_PROMPT = """

## playwright_browse
Open and inspect a web page with a real headless browser. Renders JavaScript and returns the full DOM.

**When to use:**
- The page requires JavaScript rendering (SPAs, dynamic content, client-side routing)
- A basic URL fetch (`open_url`) returns incomplete or empty content
- You need to interact with or inspect browser-rendered DOM elements
- Scraping content from modern web apps that load data asynchronously

**Decision tree:**
1. Static page or API endpoint? → use `open_url` (faster, lighter)
2. JavaScript-heavy page or SPA? → `playwright_browse` (this tool)
3. Need to search the web first? → `web_search` then `playwright_browse` on results

**Rules:**
- Prefer `open_url` for simple, static pages — this tool is heavier
- Degrade gracefully if Playwright is not installed or browser binaries are missing
- Extract the text and data you need from the rendered page — do not return raw HTML dumps
- Combine with `write_file` to save scraped data locally
""".strip()
