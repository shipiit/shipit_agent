"""What the model is told about the file write tool: when to use it and how."""

from __future__ import annotations

FILE_WRITE_PROMPT = """
Create a file, or overwrite or append to one, under the project root. Parent
folders are created as needed.
- For a change to part of an existing file, use `edit_file` instead.
- Read the existing file first before overwriting it, so nothing is lost.
- Use this rather than `echo >` or a heredoc in `bash`.
""".strip()
