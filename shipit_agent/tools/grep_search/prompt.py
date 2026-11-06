"""What the model is told about the grep search tool: when to use it and how."""

from __future__ import annotations

GREP_SEARCH_PROMPT = """
Search file contents with a regex (ripgrep). Results give paths and line
numbers to follow up with `read_file`.
- Narrow by file type with `glob` (`"*.py"`) when you know it.
- `case_sensitive=false` ignores case; `max_matches` caps a common pattern.
- Use this rather than `grep` or `rg` in `bash`.
""".strip()
