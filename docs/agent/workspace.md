---
title: The SHIPIT Workspace
description: Point an agent at a repo and it just works — auto-loaded SHIPIT.md / AGENTS.md project memory, file-based /slash commands from .shipit/commands/, and a checked-in .shipit/settings.json policy wired straight into the permission engine.
---

# The SHIPIT Workspace

The **SHIPIT Workspace** lets you point an agent at a
repository and have it *just work* — no glue code. Drop a few conventional
files in the repo and every agent rooted there picks them up automatically:

- **Project memory** — a `SHIPIT.md` (or `AGENTS.md`) at the repo root is
  auto-loaded into the system prompt.
- **Slash commands** — markdown files under `.shipit/commands/` become
  `/commands` you can invoke with arguments.
- **Settings** — a checked-in `.shipit/settings.json` declares permissions,
  env vars, and a default model, and wires straight into the
  [control plane](../guides/permissions.md).

`Agent.for_project(llm=..., project_root="/repo")` loads all three in one call.
None of this is Anthropic-specific — it works with **any LLM provider**.

> **TL;DR** —
> ```python
> from shipit_agent import Agent
>
> # Loads .shipit/settings.json + SHIPIT.md + builtin tools + /commands.
> agent = Agent.for_project(llm=llm, project_root="/my/repo")
> agent.run("/review src/app.py")
> ```

## Project memory — `SHIPIT.md` / `AGENTS.md`

The SHIPIT answer to a project-instructions file: drop a `SHIPIT.md` at your
repo root and every agent pointed at that project picks it up — no code.

```text
my-repo/
├── SHIPIT.md          ← project instructions, auto-loaded
└── src/...
```

```python
from shipit_agent import Agent

# auto_project_memory is True by default.
agent = Agent(llm=llm, project_root=".")
# SHIPIT.md is now part of the system prompt.
```

The loader searches these locations and includes **every file that exists**
(project context first, then your user-global file), each appended as its own
labeled block under a `# Project instructions` heading:

| Order | Path | Scope |
| --- | --- | --- |
| 1 | `SHIPIT.md` | project |
| 2 | `AGENTS.md` | project |
| 3 | `.shipit/SHIPIT.md` | project |
| 4 | `.shipit/AGENTS.md` | project |
| 5 | `~/.shipit/SHIPIT.md` | user-global (applies everywhere) |
| 6 | `~/.shipit/AGENTS.md` | user-global |

### `@path` imports

An instruction file can pull in others with a line starting `@` followed by a
relative (or `~`-expanded) path. Imports resolve relative to the **importing**
file, are depth-limited, and are cycle-safe — so you can split conventions
across files:

```markdown
# Project instructions

Always run `make lint` before finishing.

@docs/style-guide.md
@~/.shipit/personal-prefs.md
```

### Opting out

Set `auto_project_memory=False` to skip **project-memory injection** entirely:

```python
agent = Agent(llm=llm, project_root=".", auto_project_memory=False)
```

> **Note** — this flag governs *only* the project-memory injection.
> `/slash` commands (below) are always expanded on `run()` regardless of this
> setting.

### Direct API

Need the assembled block yourself? Call `load_project_memory` directly:

```python
from shipit_agent.workspace import load_project_memory

block = load_project_memory(".", include_user=True, max_depth=5)
# Returns "" when no instruction files exist.
```

## Slash commands — `.shipit/commands/`

Drop a markdown file at `.shipit/commands/<name>.md` and invoke it with
`agent.run("/<name> ...args")`. The file body becomes the prompt — no catalog
edit, no registration.

```text
my-repo/
└── .shipit/
    └── commands/
        └── review.md
```

```markdown
---
description: Code-review a file
---
Review $ARGUMENTS for bugs, security issues, and style. Be concise.
Focus especially on $1.
```

```python
agent.run("/review src/app.py")
```

- **`$ARGUMENTS`** → everything after the command name (`"src/app.py"`).
- **`$1`, `$2`, …** → individual whitespace-separated args.
- A leading **YAML frontmatter** block (between `---` fences) is **stripped**
  before substitution, so you can annotate commands without leaking metadata
  into the prompt.
- **Unknown `/cmd`** text passes through unchanged — a prompt that happens to
  start with `/` but isn't a known command is sent to the model verbatim.

### Discovery & expansion API

```python
from shipit_agent.workspace import discover_commands, expand_command

discover_commands(".")            # {"review": Path(".shipit/commands/review.md"), ...}
expand_command(".", "/review src/app.py")  # the expanded prompt, or None if unknown
```

## Settings — `.shipit/settings.json`

Check a policy into the repo: permissions, env vars, and a default model. A
user-global `~/.shipit/settings.json` is merged **underneath** the project file
(project wins).

```json
{
  "model": "bedrock/google.gemma-4-31b",
  "permissions": {
    "mode": "default",
    "allow": ["read*", "grep*"],
    "deny": ["bash", "*_delete"],
    "ask": ["sql"]
  },
  "env": { "SHIPIT_LLM_PROVIDER": "bedrock" }
}
```

| Field | Type | Meaning |
| --- | --- | --- |
| `model` | string | A default model id (any provider). |
| `permissions.mode` | string | Permission engine mode (e.g. `default`). |
| `permissions.allow` / `deny` / `ask` | string[] | Glob rules over tool names. |
| `env` | object | Env vars to set (opt-in — see below). |

### Loading and wiring

```python
from shipit_agent.workspace import load_settings

settings = load_settings(".")          # merges ~/.shipit then .shipit
engine = settings.to_permission_engine()
```

`to_permission_engine()` returns a `PermissionEngine` built from the rules — or
**`None`** when nothing constrains tools (default mode with no allow/deny/ask),
so the agent stays unrestricted unless the file asks otherwise. Env vars from
`settings.env` are applied only when you call `settings.apply_env()` (which uses
`setdefault`, so it never overrides vars already in the environment).

### `Agent.for_project(...)` — everything in one call

`Agent.for_project` is the front door. Point it at a repo and it:

1. Loads `.shipit/settings.json` (+ user-global), and turns its permissions
   into a `PermissionEngine` (unless you pass your own `permissions=`).
2. Attaches the full **builtin tool catalogue** (it calls
   [`with_builtins`](with-tools.md) under the hood).
3. Picks up **`SHIPIT.md` / `AGENTS.md`** project memory.
4. Enables **`/slash`** commands from `.shipit/commands/`.

```python
from shipit_agent import Agent

agent = Agent.for_project(llm=llm, project_root="/my/repo")
agent.run("/review src/app.py")
```

To also apply `settings.env`, pass `apply_env=True` (it's `False` by default,
so checked-in env vars never silently mutate your process):

```python
agent = Agent.for_project(llm=llm, project_root="/my/repo", apply_env=True)
```

> **Provider-agnostic** — `for_project` is just configuration loading on top of
> `with_builtins`; it works with **any** LLM provider you pass as `llm=`.

## See also

- [Permissions, plan mode & hooks](../guides/permissions.md) — the control plane the
  settings file feeds into.
- [With Tools](with-tools.md) — the builtin tool catalogue `for_project`
  attaches.
- [TodoTool — live task tracking](../tools/todo-tool.md) — the builtin that
  keeps long workspace runs observable.
