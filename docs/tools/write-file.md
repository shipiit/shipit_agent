---
title: write_file
description: Prompt and reference for the built-in write_file tool.
---

# `write_file`

**Class:** `FileWriteTool`  
**Module:** `shipit_agent.tools.file_write`  
**Tool ID:** `write_file`

Creates or overwrites a file under the configured `project_root`.

## Default prompt

```text
## write_file
Create or overwrite a file under the local project root.

**When to use:**
- Create a brand-new file
- Replace an entire file when a full rewrite is cleaner than a patch
- Append generated output or logs when the workflow needs a saved artifact

**Rules:**
- Prefer `edit_file` for targeted changes to an existing file
- Read the existing file first before overwriting it
- Paths are relative to the configured project root
- Keep writes scoped to task-relevant project files
```

## Example

```python
result = agent.run(
    "Create /tmp/output/report.json with the cleaned results from the previous step."
)
```
