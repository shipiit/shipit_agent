from __future__ import annotations

FILE_WRITE_PROMPT = """

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
""".strip()
