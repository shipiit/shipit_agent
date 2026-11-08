"""What the model is told about the bash tool: when to use it and how."""

from __future__ import annotations

BASH_PROMPT = """
Run a shell command in the project root: tests, builds, package managers,
git, scripts, pipes and redirections.
- Run tests with the project's runner (`pytest -q`, `npm test`, `go test ./...`);
  running a test file with `python` executes no tests.
- Prefer `read_file`, `glob_files`, `grep_files` and `edit_file` to `cat`,
  `find`, `grep -r` and `sed -i`: they track reads and bound output. One
  mechanical rename across many files is the exception: one
  `perl -pi -e 's/\\bold\\b/new/g' <files>`, then `grep_files` to confirm.
- Throwaway scripts go in a temp folder (`mktemp -d`), never the project.
- Deleting files, discarding git work, pushing, publishing, sudo, writing
  outside the project, sending data out and stopping processes need approval,
  which the runtime asks for when you call: make the call rather than asking
  in text. If one is refused, do not retry it another way; say what you wanted.
- A command gets 2 minutes (`timeout`, up to 10), then continues in the
  background with a job id for `bash_job`. Start servers with `background: true`.
- Chain dependent steps with `&&`; make independent commands separate calls so
  they run at once. Use `working_directory`, not `cd`; quote paths with spaces.
- Long output is clipped; the result names the file holding all of it.
""".strip()
