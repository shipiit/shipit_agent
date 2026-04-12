---
title: edit_file
description: Prompt and reference for the built-in edit_file tool.
---

# `edit_file`

**Class:** `EditFileTool`  
**Module:** `shipit_agent.tools.edit_file`  
**Tool ID:** `edit_file`

Applies an exact string replacement patch to an existing file under the configured `project_root`.

## Default prompt

```text
## edit_file
Apply an exact text replacement patch to an existing file.

**When to use:**
- Make a targeted edit without rewriting the whole file
- Replace a known block of code, text, or config
- Rename or update repeated text with `replace_all`

**Rules:**
- Read the file first with `read_file` before editing it
- `old_text` must match the current file contents exactly
- Use the smallest uniquely identifying block that is still stable
- Prefer this tool over `write_file` for surgical edits to existing files
```

## Runtime behavior

- Rejects edits if the file was not previously read with `read_file`
- Fails if `old_text` is missing
- Fails on ambiguous matches unless `replace_all=true`

## Example

```python
result = agent.run(
    "Read /tmp/app/config.py, change DEBUG = True to DEBUG = False, and explain the patch."
)
```
