---
title: read_file
description: Prompt and reference for the built-in read_file tool.
---

# `read_file`

**Class:** `FileReadTool`  
**Module:** `shipit_agent.tools.file_read`  
**Tool ID:** `read_file`

Reads a file from the configured `project_root`. The built-in tool defaults to `project_root="/tmp"`.

## Default prompt

```text
## read_file
Read a file from the local project root.

**When to use:**
- Inspect source files, configs, logs, generated outputs, and local data files
- Read the exact text before editing or patching a file
- Pull a targeted range of lines when you already know the relevant area

**Rules:**
- Paths are relative to the configured project root
- Read before editing an existing file
- Prefer focused reads for very large files
- Directories are not valid inputs for this tool
```

## Runtime behavior

- Returns line-numbered output
- Supports `start_line` and `max_lines`
- Tracks which files were read so `edit_file` can enforce read-before-patch behavior

## Example

```python
result = agent.run("Read /tmp/app/settings.py and summarize the database config.")
```
