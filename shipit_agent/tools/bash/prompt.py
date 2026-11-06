"""What the model is told about the bash tool: when to use it and how."""

from __future__ import annotations

BASH_PROMPT = """
Run a shell command in the project root: tests, builds, package managers,
git, scripts, pipes and redirections.
- Use the dedicated tools when they fit: `read_file` not `cat`, `glob_files`
  not `find`, `grep_files` not `grep -r`, `edit_file` or `write_file` not
  `sed -i` or `echo >`. They track reads and keep output bounded.
- Commands that delete files, discard git work, push or publish, use sudo,
  write outside the project, send data out or stop processes need approval.
  If one is refused, do not retry it in another form: say what you wanted to
  run and why.
- A command gets 2 minutes by default (`timeout`, up to 10). One still running
  then continues in the background with a job id; check it with `bash_job`.
  Start servers and watchers with `background: true`.
- Chain dependent steps with `&&`; make independent commands separate calls so
  they run at once. Use `working_directory` rather than `cd`, and quote paths
  with spaces.
- Long output is clipped to its start and end; the result names the file
  holding all of it.
""".strip()
