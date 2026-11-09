---
title: Sandboxed code_execution
description: Opt-in Docker sandbox for run_code — ephemeral container, network off, read-only rootfs, writable /tmp. Safe default for untrusted snippets. Graceful fallback when docker isn't installed.
---

# Sandboxed `code_execution`

The pre-existing `run_code` tool ran snippets in a local subprocess —
fast, but full-trust. For untrusted code (anything a model generates on
behalf of arbitrary user input) that isn't safe.

Passing **`sandbox=True`** runs the exact same snippet inside an
**ephemeral Docker container** with:

- `--network none` — no outbound traffic (opt in with `network=True`)
- `--read-only` root filesystem
- writable `/tmp` tmpfs (64 MB) for normal temp-file usage
- workspace bind-mounted at `/work` **read-only** — the container
  sees the script, can't modify it or anything else on the host

No changes to how you invoke the tool otherwise.

---

## Quick start

```python
from shipit_agent.tools.code_execution import CodeExecutionTool
from shipit_agent.tools.base import ToolContext

tool = CodeExecutionTool()
out = tool.run(
    ToolContext(prompt="demo"),
    language="python",
    code="print('hello from the sandbox')",
    sandbox=True,
)
print(out.text)
# exit_code: 0
# stdout:
# hello from the sandbox
# stderr:
print(out.metadata["sandbox_image"])   # "python:3.11-slim"
print(out.metadata["sandbox_network"]) # False
```

---

## Supported languages + default images

| Language | Image |
| --- | --- |
| `python` | `python:3.11-slim` |
| `javascript` | `node:22-alpine` |
| `typescript` | `node:22-slim` (installs `tsx` on first run) |
| `ruby` | `ruby:3.3-alpine` |
| `php` | `php:8.3-cli-alpine` |
| `perl` | `perl:5.40-slim` |
| `lua` | `alpine:3.20` |
| `r` | `r-base:4.4.1` |
| `bash` / `sh` / `zsh` | `alpine:3.20` |

Override per call:

```python
tool.run(ctx,
    language="python", code="...", sandbox=True,
    image="python:3.12-alpine",          # your own cached image
)
```

---

## Opt-in network

```python
tool.run(ctx,
    language="python", code="import urllib.request; print(urllib.request.urlopen('https://example.com').status)",
    sandbox=True,
    network=True,                         # ← bridge network instead of none
)
```

Use sparingly — when the whole point is isolation, bridge defeats it.

---

## Point at a user-chosen workspace

Specialists (developer, debugger, designer, researcher) are often asked
to work inside a specific project. Pass `workspace_root` per call so
the container mounts that directory:

```python
tool.run(ctx,
    language="python",
    code="import pathlib; print(list(pathlib.Path('.').iterdir())[:5])",
    workspace_root="/path/to/user/project",
    sandbox=True,
)
```

The mount is read-only — the snippet can read the workspace but not
write to it, preventing accidental corruption. Use `bash` +
`write_file` outside the sandbox when you need to write.

---

## Fallback when docker isn't installed

```python
out = tool.run(ctx, language="python", code="print(1)", sandbox=True)
# On a machine without docker:
out.metadata == {"ok": False, "sandbox": True, "error": "[Errno 2] ..."}
out.text     == "Error: docker is not installed or not on PATH. ..."
```

No exception raised — the calling agent can branch on
`metadata["ok"] is False`.

---

## When to reach for `sandbox=True`

- The snippet came from a **prompt you don't fully control** (user
  input, scraped text, a model's own generation).
- You're running across **many PRs** in parallel and don't want one of
  them to mutate your workspace.
- **CI security** — you want provably-isolated untrusted execution.

When **not** to use it:

- Trusted local iteration — the startup cost of a container adds
  ~300–800ms per call.
- You need to *modify* the workspace — the mount is read-only.
- You're running without Docker Desktop / container runtime.

---

## Notebook

- `notebooks/45_cost_router_async_ask_vision_sandbox.ipynb` — live demo including TypeScript and an image override.
