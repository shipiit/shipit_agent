from __future__ import annotations

WEB_SEARCH_PROMPT = """

## web_search
Search the public web for up-to-date information using the configured search provider.

**When to use:**
- The answer requires **fresh data** (news, CVE details, recent incidents, patches, release notes)
- Niche technical information likely found on blogs, forums, documentation sites, or Stack Overflow
- When the cost of giving outdated information is high (security advisories, API changes, pricing)
- The user asks about current events, recent changes, or "latest" anything
- You need to verify a claim or find authoritative sources

**Decision tree:**
1. User provides a specific URL? → use `open_url` directly, skip search
2. Need to find information on the web? → `web_search` (this tool)
3. Need full page content from a result? → `web_search` then `open_url` on top results
4. Page needs JavaScript rendering? → `web_search` then `playwright_browse`

**Rules:**
- Use specific, targeted search queries — not vague multi-topic searches
- Prefer searching for the exact error message, function name, or technical term
- After getting results, use `open_url` to read the most promising pages in full
- Do not guess at URLs — search first, then follow the results
""".strip()
