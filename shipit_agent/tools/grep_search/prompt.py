from __future__ import annotations

GREP_SEARCH_PROMPT = """

## grep_files
Search file contents in the local project, using ripgrep when available.

**When to use:**
- Find symbols, error strings, config keys, routes, SQL snippets, and text patterns
- Map where behavior is implemented before reading or editing files
- Search broadly across the repo without falling back to shell `grep`

**Rules:**
- Prefer this tool over ad-hoc shell search for repository content lookup
- Use `glob` to narrow the search scope when file types are known
- Returned paths are relative to the configured project root
""".strip()
