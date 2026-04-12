---
title: Write File
description: Prompt and reference for the built-in write_file tool.
---

# Write File

**Class:** `FileWriteTool`  
**Module:** `shipit_agent.tools.file_write`  
**Tool ID:** `write_file`

Creates or overwrites a file under the configured `project_root`.

## Default prompt

```text
## write_file
Create or overwrite a file under the local project root. Supports `overwrite` and `append` modes.

**When to use:**
- Create a brand-new file that does not yet exist
- Replace an entire file when a full rewrite is cleaner than surgical patches
- Append generated output, logs, or results when the workflow needs a saved artifact
- Generate configuration files, scripts, or templates from scratch

**Decision tree:**
1. File does not exist yet? → `write_file` (mode: overwrite)
2. Changing a few lines in an existing file? → use `edit_file` instead
3. Rewriting most of the file? → `read_file` first, then `write_file`
4. Appending to a log or result file? → `write_file` (mode: append)

**Rules:**
- Prefer `edit_file` for targeted changes — it preserves surrounding context and is safer
- **Read the existing file first** before overwriting it so you understand what you are replacing
- Paths are relative to the configured project root
- Parent directories are created automatically if they do not exist
- Keep writes scoped to task-relevant project files — do not write outside the project
- After writing, consider reading the file back to confirm the result

**Anti-patterns:**
- Overwriting a large file to change one line (use `edit_file` instead)
- Writing files without reading the original first (risks losing content)
- Using `bash` with `echo >` or heredocs when `write_file` is available
```

## Example

```python
result = agent.run(
    "Create /tmp/output/report.json with the cleaned results from the previous step."
)
```
