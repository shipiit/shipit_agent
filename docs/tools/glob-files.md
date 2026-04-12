---
title: glob_files
description: Prompt and reference for the built-in glob_files tool.
---

# `glob_files`

**Class:** `GlobSearchTool`  
**Module:** `shipit_agent.tools.glob_search`  
**Tool ID:** `glob_files`

Finds project files by path pattern under the configured `project_root`.

## Default prompt

```text
## glob_files
Find files in the local project using glob patterns.

**When to use:**
- Locate files by name or extension such as `**/*.py` or `docs/**/*.md`
- Narrow the candidate set before running `grep_files` or `read_file`
- Discover where a feature or config probably lives

**Rules:**
- Use this for filename/path discovery, not content search
- Prefer targeted patterns over broad recursive scans when possible
- Returned paths are relative to the configured project root
```

## Example

```python
result = agent.run(
    "Find all Python migration files under /tmp using glob_files and list the newest candidates."
)
```
