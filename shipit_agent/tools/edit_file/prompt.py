from __future__ import annotations

EDIT_FILE_PROMPT = """

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
""".strip()
