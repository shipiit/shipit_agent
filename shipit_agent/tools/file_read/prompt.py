from __future__ import annotations

FILE_READ_PROMPT = """

## read_file
Read a file from the local project root. Returns line-numbered output.

**When to use:**
- Inspect source files, configs, logs, generated outputs, and local data files
- Read the exact text before editing or patching a file — **required** before calling `edit_file`
- Pull a targeted range of lines when you already know the relevant area
- Verify file contents after a write or edit operation
- Understand existing code structure before proposing changes

**Decision tree:**
1. Need to find a file first? → use `glob_files` then `read_file`
2. Need to search inside files? → use `grep_files` then `read_file` on matches
3. Need to change the file? → `read_file` first, then `edit_file`
4. Need a full rewrite? → `read_file` first, then `write_file`

**Rules:**
- Paths are relative to the configured project root
- **Always read before editing** — `edit_file` will reject patches on unread files
- Use `start_line` and `max_lines` for large files instead of reading the whole thing
- Prefer focused reads: read the function, not the whole module
- Directories are not valid inputs — use `glob_files` for directory listing
- Reading tracks state: the file is marked as "read" for subsequent `edit_file` calls

**Anti-patterns:**
- Reading an entire 10k-line file when you only need lines 50–80
- Skipping the read and going straight to `edit_file` (will be rejected)
- Using `bash` with `cat` when `read_file` is available
""".strip()
