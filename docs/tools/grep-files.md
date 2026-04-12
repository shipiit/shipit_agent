---
title: grep_files
description: Prompt and reference for the built-in grep_files tool.
---

# `grep_files`

**Class:** `GrepSearchTool`  
**Module:** `shipit_agent.tools.grep_search`  
**Tool ID:** `grep_files`

Searches repository contents under the configured `project_root`, using ripgrep when available and a Python fallback otherwise.

## Default prompt

```text
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
```

## Example

```python
result = agent.run(
    "Search /tmp for occurrences of DATABASE_URL and then open the matching config file."
)
```
