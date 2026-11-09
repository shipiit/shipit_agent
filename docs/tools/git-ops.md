---
title: git_ops
description: Structured git for agents. Status, diff, log, blame, add, commit, branches, stash and worktrees, with push and reset off unless you turn them on.
---

# `git_ops`

`git_ops` gives an agent git as named actions with fixed arguments, instead of shell strings. It runs real `git` in the project, with a timeout, and never takes a free-form command line, so a model can't slip extra flags in.

Push and reset are **off** by default. Turn each on deliberately.

## Actions

| Action | Arguments | What it does |
| --- | --- | --- |
| `status` | | Changed, staged and untracked files |
| `diff` | `paths`, `staged` | The working-tree diff, or `--staged` |
| `log` | `ref`, `limit` (default 15) | Recent commits |
| `show` | `ref` | One commit |
| `blame` | `paths` | Who changed each line |
| `branch` | | Branches |
| `add` | `paths` | Stage files |
| `commit` | `message` | Commit what is staged |
| `checkout` | `ref` or `paths` | Switch branch, or restore files |
| `stash`, `stash_list`, `stash_pop` | `message` | Park and restore changes |
| `worktree_add`, `worktree_list`, `worktree_remove` | `ref` | Work on another branch in a second folder |
| `push`, `reset` | | Refused unless enabled |

## Use it

`Agent.with_builtins()` includes `git_ops` for the project root. To set it up yourself:

```python
from shipit_agent import Agent, GitOpsTool
from shipit_agent.llms import build_llm_from_env

git = GitOpsTool(root_dir=".", allow_push=False, allow_reset=False, timeout_seconds=60)
agent = Agent(llm=build_llm_from_env(), tools=[git])
agent.run("Summarise what changed since the last commit, then commit it with a clear message.")
```

| Argument | Default | What it does |
| --- | --- | --- |
| `root_dir` | `"."` | The repository it works in |
| `allow_push` | `False` | Let the agent push |
| `allow_reset` | `False` | Let the agent reset |
| `timeout_seconds` | `60` | Longest a git command may run |

Pair it with [permissions](../guides/permissions.md) to ask before a commit, for example `ask=["git_ops"]`.

## See also

- [Bash](bash.md) for everything that isn't git
- [GitHub](github.md) for pull requests and issues
