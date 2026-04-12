---
title: bash
description: Prompt and reference for the built-in bash tool.
---

# `bash`

**Class:** `BashTool`  
**Module:** `shipit_agent.tools.bash`  
**Tool ID:** `bash`

Runs a bounded shell command from the configured `project_root`. The built-in tool defaults to `project_root="/tmp"` unless you override it on `Agent` or `DeepAgent`.

## Default prompt

```text
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
```

## Safety model

- Uses an allowlist of command prefixes like `git`, `pytest`, `python`, `npm`, `uv`, `sed`, and `cat`
- Blocks dangerous substrings like `git reset --hard`, `git clean -fd`, `sudo `, and destructive disk commands
- Rejects working directories that escape the configured `project_root`

## Example

```python
from shipit_agent import Agent

agent = Agent.with_builtins(
    llm=llm,
    project_root="/tmp",
)

result = agent.run("Run pytest in /tmp and summarize any failures.")
```
