from __future__ import annotations

BASH_PROMPT = """

## bash
Run a bounded shell command inside the configured project root.

**When to use:**
- Inspect the repo with trusted shell commands like `ls`, `git status`, `pytest`, or build/test commands
- Run developer workflows that are easier in shell than in Python
- Execute repo-local utilities, package scripts, or verification commands

**Rules:**
- Commands run from the configured project root by default
- Dangerous commands are blocked unless the tool allowlist explicitly permits them
- Prefer dedicated tools like `read_file`, `grep_files`, and `edit_file` when they fit
- Keep commands short, task-specific, and reviewable
""".strip()
