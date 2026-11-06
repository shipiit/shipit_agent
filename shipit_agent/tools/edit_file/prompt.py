"""What the model is told about the edit file tool: when to use it and how."""

from __future__ import annotations

EDIT_FILE_PROMPT = """
Replace exact text in an existing file. Use it for any change smaller than a
rewrite; use `write_file` for a new file or to replace most of one.
- Read the file first with `read_file`; a file you just wrote counts as read.
- `old_text` must match the file exactly, whitespace and indentation included.
  Copy it from the `read_file` output without the line-number prefix (`  12: `).
- Use the smallest block that is unique. If it occurs more than once, add
  surrounding lines to pick one, or set `replace_all=true` to change them all.
- If the file changed since you read it, the edit still applies while
  `old_text` is intact; you are asked to re-read only when it is not.
""".strip()
