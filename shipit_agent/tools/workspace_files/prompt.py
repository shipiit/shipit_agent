from __future__ import annotations

WORKSPACE_FILES_PROMPT = """

## workspace_files
Create, read, edit, inspect, list, and delete files in the workspace under `/tmp`.

**When to use:**
- User asks to create, update, or inspect a file
- User asks to save markdown, JSON, CSV, text, or generated output
- User asks for a downloadable file path
- You need to verify whether a file exists before referencing it

**Rules:**
- Prefer relative paths under the workspace instead of inventing unrelated project paths
- Always pass an explicit `action`
- Use `write` to create or replace a file, `append` to add to an existing file, and `mkdir` for folders
- Use `read` or `info` before claiming a file exists
- When you create or update a file, include the returned path and a markdown download link in the response
- When the user asks what is inside a file, use `read` and show the contents instead of guessing
- When showing file contents, prefer a fenced code block so the chat renders it cleanly
""".strip()
