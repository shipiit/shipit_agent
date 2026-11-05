"""What the model is told about the bash tool: when to use it and how."""

from __future__ import annotations

BASH_PROMPT = """

## bash
Run a shell command (bash) in the project root. Any command works: tests,
builds, package managers, git, language runtimes, scripts, pipes and
redirections.

**Use it for:**
- Tests and checks: `pytest -q`, `npm test`, `go test ./...`, `ruff check .`
- Builds and installs: `npm run build`, `make`, `cargo build`, `uv sync`
- Git: `git status`, `git diff`, `git log --oneline -10`, `git add`, `git commit`
- Project scripts and CLIs, and anything without a dedicated tool

**Prefer the dedicated tools when they fit:**
- Read a file: `read_file`, not `cat`. Find files: `glob_files`, not `find`.
- Search contents: `grep_files`, not `grep -r`.
- Change a file: `edit_file` / `write_file`, not `sed -i` or `echo >`.
They track what you have read, show diffs, and keep large output bounded.

**Approval:** commands that delete files, discard git work, push or publish,
use sudo, write outside the project, send data to a server, run a
downloaded script, or stop processes need approval. If one is refused, do
not retry it in another form: say what you wanted to run and why. A few
commands that could wreck the machine (wiping `/` or a home folder,
formatting a disk) never run.

**Time:** a command gets 2 minutes by default (`timeout`, up to 10). One
still running then keeps going in the background, and you get a job id;
check it with `bash_job`. Start servers and watchers with
`background: true` from the start.

**Tips:**
- Quote paths that contain spaces.
- Chain dependent steps with `&&`; run independent commands as separate calls
  so they can run at the same time.
- Use `working_directory` instead of `cd` when a command belongs in a subfolder.
- Long output is clipped to its start and end; the result names the file
  holding all of it.
""".strip()
