---
title: Artifacts — structured deliverables
description: Claude-Desktop-style deliverable collection. Code blocks and markdown docs auto-extracted from every iteration, tool results with `artifact=True` captured explicitly, optional disk persistence for CI runs.
---

# Artifacts — structured deliverables

The `ArtifactCollector` captures structured deliverables produced during
an Autopilot run: code blocks, markdown documents, tool outputs. The
final `AutopilotResult.artifacts` is a list your UI can render as a
deliverable panel — Claude-Desktop-style.

> **TL;DR** — pass `artifacts=True` (or an `ArtifactCollector()` instance)
> to Autopilot. After the run, `result.artifacts` is a list of
> auto-extracted code fences and markdown docs. Tools can also push
> explicit artifacts via result metadata.

---

## What gets collected automatically

From every iteration's output text:

1. **Fenced code blocks** — every `` ```lang\n...\n``` `` becomes one
   `Artifact` with `kind="code"`, `language="lang"`, and a generated
   name like `iter3-block1.py`.
2. **Markdown documents** — if the remaining non-fenced text begins with
   `#` and is >200 chars, it's captured as `kind="markdown"` with a
   slug-based filename.

From every tool result metadata:

3. Any dict with `{"artifact": True, "kind": ..., "name": ..., "content": ...}`
   becomes an artifact. Tools can return a single dict or a list.

---

## Quick start

```python
from shipit_agent import Goal
from shipit_agent.autopilot import Autopilot, BudgetPolicy, ArtifactCollector

collector = ArtifactCollector()
autopilot = Autopilot(
    llm=llm,
    goal=Goal(
        objective="Write a Python `fib(n)` function with a usage example.",
        success_criteria=[
            "Contains a `def fib(n)` in a fenced block",
            "Shows example usage in a second fenced block",
        ],
    ),
    budget=BudgetPolicy(max_iterations=4),
    artifacts=collector,
)
result = autopilot.run(run_id="fib-demo")

for a in result.artifacts:
    print(a["kind"], a["name"], a["language"], len(a["content"]), "chars")
```

Want a default collector without the extra import?

```python
autopilot = Autopilot(..., artifacts=True)
```

---

## The `Artifact` shape

| Field | Type | Description |
| --- | --- | --- |
| `kind` | `str` | `"code"`, `"markdown"`, `"file"`, `"table"`, `"answer"` — extensible |
| `name` | `str` | Filename-safe id (e.g. `iter3-block1.py`, `iter2-report.md`) |
| `content` | `str` | The payload; capped at 64 KB per artifact |
| `language` | `str \| None` | Set for `kind="code"` — `"python"`, `"ts"`, etc. |
| `iteration` | `int` | Which Autopilot iteration produced it |
| `created_at` | `float` | Unix timestamp |
| `metadata` | `dict` | Anything extra the tool passed through |

---

## Tool-side contract

A tool that wants its output captured as an artifact returns metadata
shaped like:

```python
from shipit_agent.tools.base import ToolOutput

ToolOutput(
    text="Generated report — see metadata for the full thing.",
    metadata={
        "artifact": True,
        "kind": "file",
        "name": "incident-report-2026-04-21.md",
        "content": long_markdown_string,
        "language": "md",
    },
)
```

Multiple artifacts from one tool call:

```python
ToolOutput(
    text="Produced three artifacts.",
    metadata=[
        {"artifact": True, "kind": "file", "name": "analysis.md", "content": "..."},
        {"artifact": True, "kind": "code", "name": "plot.py",    "content": "..."},
        {"artifact": True, "kind": "file", "name": "data.csv",   "content": "..."},
    ],
)
```

---

## Live streaming

When you use `autopilot.stream()`, each artifact emits an
`autopilot.artifact` event the instant it lands in the collector:

```python
for ev in autopilot.stream(run_id="live"):
    if ev["kind"] == "autopilot.artifact":
        print(f"[+] {ev['artifact_kind']:<8} {ev['name']} ({len(ev['content'])} chars)")
```

> **Why `artifact_kind`, not `kind`?** The event envelope uses `kind`
> for its own message type (`autopilot.artifact`). The artifact's
> native `kind` (`code`, `markdown`, …) is exposed under
> `artifact_kind` to avoid collision.

---

## Disk persistence — handy for CI

Pass `persist_dir` when you want one JSON file per artifact (good for
uploading as a CI build output, or diffing across runs):

```python
from pathlib import Path
from shipit_agent.autopilot import ArtifactCollector

collector = ArtifactCollector(persist_dir=Path.home() / ".shipit_agent" / "artifacts" / "nightly")
autopilot = Autopilot(..., artifacts=collector)
```

Each artifact gets atomic-written to `<persist_dir>/<slug>.json`.
Failures are logged but never fail the run.

---

## Reading after the run

```python
# All artifacts, chronological order
for a in collector.all():
    print(a.kind, a.name)

# Filter by kind
code_blocks = collector.by_kind("code")
for a in code_blocks:
    print(a.language, a.name, len(a.content))
```

From the result envelope:

```python
result = autopilot.run(run_id="x")
# result.artifacts is a list of dicts (to_dict'd)
for a in result.artifacts:
    print(a["kind"], a["name"])
```

---

## API reference

```python
class Artifact:
    kind: str
    name: str
    content: str                           # capped at 64 KB
    language: str | None = None
    iteration: int = 0
    created_at: float                      # unix ts
    metadata: dict[str, Any]

class ArtifactCollector:
    MAX_CONTENT_CHARS: int = 64_000

    def __init__(
        self, *,
        persist_dir: str | Path | None = None,
        on_add: Callable[[Artifact], None] | None = None,
    ) -> None: ...

    def all(self) -> list[Artifact]: ...
    def by_kind(self, kind: str) -> list[Artifact]: ...
    def add(self, *, kind, name, content, language=None, iteration=0, metadata=None) -> Artifact: ...
    def extract_from_output(self, text: str, *, iteration: int) -> list[Artifact]: ...
    def ingest_tool_metadata(self, metadata: Any, iteration: int) -> list[Artifact]: ...
```

---

## Notebooks

- `notebooks/43_fanout_critic_artifacts.ipynb` — focused deep-dive.
- `notebooks/44_complete_tour.ipynb` — artifacts alongside fan-out + critic.
