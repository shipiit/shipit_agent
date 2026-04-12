from __future__ import annotations

GLOB_SEARCH_PROMPT = """

## glob_files
Find files in the local project by name or path pattern. Fast file discovery without reading contents.

**When to use:**
- Locate files by name or extension: `**/*.py`, `docs/**/*.md`, `**/config.*`
- Discover project structure and file layout before diving into content
- Narrow the candidate set before running `grep_files` or `read_file`
- Check whether a specific file or directory path exists
- Find migration files, test files, config files, or generated outputs

**Decision tree:**
1. Know the filename or extension? → `glob_files` (this tool)
2. Know the content but not the file? → use `grep_files` instead
3. Need both? → `glob_files` first to narrow scope, then `grep_files` with a glob filter
4. Found the file? → `read_file` to inspect its contents

**Rules:**
- Use this for **filename/path discovery**, not content search
- Prefer targeted patterns over broad recursive scans when possible
- Returned paths are relative to the configured project root
- Results are sorted by modification time (newest first)

**Common patterns:**
- All Python files: `**/*.py`
- All test files: `**/test_*.py` or `**/*_test.go`
- Config files: `**/config.*` or `**/*.yml`
- Specific directory: `src/models/**/*.py`
- Migrations: `**/migrations/*.sql` or `**/migrations/*.py`
- Package manifests: `**/package.json` or `**/pyproject.toml`

**Anti-patterns:**
- Using `bash` with `find` or `ls -R` when `glob_files` is available
- Scanning `**/*` (everything) when you know the file type
- Using `grep_files` to find files by name instead of by content
""".strip()
