"""What the model is told about the file read tool: when to use it and how."""

from __future__ import annotations

FILE_READ_PROMPT = """
Read a file under the project root. Text comes back line-numbered; a
`.docx`, `.xlsx`, `.pptx`, `.html` or `.csv` comes back as Markdown, and
images and PDFs as viewable media.
- Read a file before you edit or overwrite it: `edit_file` rejects edits to
  files you have not read.
- For a large file, read the part you need with `start_line` and `max_lines`.
- Find files with `glob_files` and search inside them with `grep_files`;
  directories are not valid paths.
- Use this rather than `cat` in `bash`.
""".strip()
