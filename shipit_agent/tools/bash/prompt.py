from __future__ import annotations

BASH_PROMPT = """

## bash
Run a bounded shell command inside the configured project root. Use for operations that have no dedicated tool.

**When to use:**
- Run tests: `pytest`, `npm test`, `go test`, `cargo test`
- Check git state: `git status`, `git log --oneline -10`, `git diff`
- Run build commands: `npm run build`, `make`, `cargo build`
- Install dependencies: `pip install`, `npm install`, `uv sync`
- Run linters and formatters: `ruff check`, `eslint`, `black --check`
- Execute project-specific scripts and CLI tools
- Inspect system state: `ls`, `pwd`, `which`, `env`

**Decision tree — prefer dedicated tools first:**
1. Need to read a file? → use `read_file` (not `cat`)
2. Need to search file contents? → use `grep_files` (not `grep -r`)
3. Need to find files by name? → use `glob_files` (not `find`)
4. Need to edit a file? → use `edit_file` (not `sed`)
5. Need to create a file? → use `write_file` (not `echo >`)
6. None of the above? → `bash` is the right choice

**Rules:**
- Commands run from the configured project root by default
- An **allowlist** of safe command prefixes is enforced — dangerous commands are blocked
- Blocked patterns include: `rm -rf`, `sudo`, `git reset --hard`, `git clean -fd`, destructive disk operations
- Keep commands short, task-specific, and reviewable
- Chain related commands with `&&` for sequential execution
- Prefer dedicated tools when they exist — `bash` is the fallback, not the default

**Anti-patterns:**
- Using `cat file.py` instead of `read_file` (loses state tracking)
- Using `grep -r pattern .` instead of `grep_files` (misses safety features)
- Running long-running processes without timeout consideration
- Using `bash` for file edits with `sed` when `edit_file` is available
""".strip()
