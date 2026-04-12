---
title: Grep Files
description: Prompt and reference for the built-in grep_files tool.
---

# Grep Files

**Class:** `GrepSearchTool`  
**Module:** `shipit_agent.tools.grep_search`  
**Tool ID:** `grep_files`

Searches repository contents under the configured `project_root`, using ripgrep when available and a Python fallback otherwise.

## Default prompt

```text
## grep_files
Search file contents in the local project using ripgrep (with Python fallback). Supports regex, glob filters, case control, and match limits.

**When to use:**
- Find function definitions, class names, error strings, config keys, routes, SQL snippets, imports, and text patterns
- Map where behavior is implemented across the codebase before reading or editing
- Locate all usages of a symbol, API endpoint, or environment variable
- Verify a string exists (or does not exist) in the project
- Search broadly across the repo without falling back to shell `grep`

**Decision tree:**
1. Know the filename but not the contents? → `glob_files` then `read_file`
2. Know the text pattern but not which file? → `grep_files` (this tool)
3. Need filename + content search? → `grep_files` with a `glob` filter
4. Found matches? → `read_file` on the best match to see full context

**Rules:**
- Prefer this tool over `bash` with `grep` or `rg` for repository content lookup
- Use the `glob` parameter to narrow scope when file types are known (e.g., `"*.py"`, `"*.ts"`)
- Use `case_sensitive=false` for case-insensitive searches
- Use `max_matches` to limit results when searching common patterns
- Supports full regex syntax: `def\s+handle_`, `TODO|FIXME|HACK`, `import.*pandas`
- Returned paths are relative to the configured project root
- Returns line numbers alongside matching content for easy follow-up with `read_file`

**Common patterns:**
- Find a function: `def function_name` or `function function_name`
- Find an import: `from module import` or `import module`
- Find a config key: `DATABASE_URL` or `API_KEY`
- Find TODO/FIXME: `TODO|FIXME|HACK|XXX`
- Find a route: `@app.route|@router.get|@router.post`

**Anti-patterns:**
- Searching without a glob filter when you know the file type (wastes time on binaries)
- Using `bash` with `grep -r` when `grep_files` is available and safer
- Searching for very common words without narrowing scope first
```

## Example

```python
result = agent.run(
    "Search /tmp for occurrences of DATABASE_URL and then open the matching config file."
)
```
