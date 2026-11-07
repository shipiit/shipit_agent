"""What the model is told about the glob search tool: when to use it and how."""

from __future__ import annotations

GLOB_SEARCH_PROMPT = """
Find files by name or path pattern (`**/*.py`, `src/**/test_*.py`), newest
first, without reading them.
- To find files by what they contain, use `grep_files` instead.
- Prefer a specific pattern to `**/*`, and this tool to `find` or `ls -R`.
""".strip()
