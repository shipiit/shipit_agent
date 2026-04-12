from __future__ import annotations

FILE_READ_PROMPT = """

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
""".strip()
