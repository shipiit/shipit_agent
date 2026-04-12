from __future__ import annotations

GLOB_SEARCH_PROMPT = """

## glob_files
Find files in the local project using glob patterns.

**When to use:**
- Locate files by name or extension such as `**/*.py` or `docs/**/*.md`
- Narrow the candidate set before running `grep_files` or `read_file`
- Discover where a feature or config probably lives

**Rules:**
- Use this for filename/path discovery, not content search
- Prefer targeted patterns over broad recursive scans when possible
- Returned paths are relative to the configured project root
""".strip()
