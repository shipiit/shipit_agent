from __future__ import annotations

PLAYWRIGHT_BROWSER_PROMPT = """
Open and inspect a page with a real browser.

Use this when:
- JavaScript-rendered pages matter
- a basic URL fetch is not enough
- browser-like rendering is needed before extracting text

Rules:
- prefer this over plain URL fetching when rendered DOM content matters
- degrade gracefully if Playwright is not installed or browser binaries are missing
""".strip()
