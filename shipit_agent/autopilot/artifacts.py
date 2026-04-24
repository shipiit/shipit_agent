"""ArtifactCollector — collect structured deliverables during an Autopilot run.

Claude Desktop surfaces "artifacts" — code blocks, markdown docs, tables —
as first-class attachments on the run. Our equivalent is a lightweight
in-memory collector that any consumer can read after `run()` / `stream()`:

    autopilot = Autopilot(..., artifacts=ArtifactCollector())
    result = autopilot.run(run_id="r")
    for a in result.artifacts:
        print(a.kind, a.name, a.content[:80])

Two ways artifacts land in the collector:

1. **Auto-extraction** from each iteration's output — we scan fenced code
   blocks (```python ... ```), markdown document boundaries (## heading),
   and tool results that declare `artifact=True` in their metadata.
2. **Explicit add** from tools or callers — `collector.add(kind=..., name=..., content=...)`.

Every `add()` emits an `autopilot.artifact` event on the stream so a UI
can render deliverable cards in real time.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable


@dataclass(slots=True)
class Artifact:
    """A structured deliverable produced during an Autopilot run."""

    kind: str  # e.g. "code", "markdown", "table", "file", "answer"
    name: str  # short id — filename, section title, etc.
    content: str  # the actual payload (trimmed to a cap)
    language: str | None = None  # when kind=="code": "python", "ts", etc.
    iteration: int = 0  # which autopilot iteration produced it
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ArtifactCollector:
    """In-memory artifact store with optional disk persistence.

    Thread-safety: simple list-append. If you're fanning out across
    threads, wrap calls in a lock or use one collector per child.
    """

    MAX_CONTENT_CHARS = 64_000  # cap per artifact to avoid giant blobs

    def __init__(
        self,
        *,
        persist_dir: str | Path | None = None,
        on_add: Callable[[Artifact], None] | None = None,
    ) -> None:
        self._items: list[Artifact] = []
        self.persist_dir = Path(persist_dir).expanduser() if persist_dir else None
        if self.persist_dir:
            self.persist_dir.mkdir(parents=True, exist_ok=True)
        self._on_add = on_add

    # ── accessors ───────────────────────────────────────────────

    def all(self) -> list[Artifact]:
        return list(self._items)

    def by_kind(self, kind: str) -> list[Artifact]:
        return [a for a in self._items if a.kind == kind]

    def __len__(self) -> int:
        return len(self._items)

    # ── writes ──────────────────────────────────────────────────

    def add(
        self,
        *,
        kind: str,
        name: str,
        content: str,
        language: str | None = None,
        iteration: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> Artifact:
        """Append a new artifact; emits a side-effect via ``on_add`` if wired."""
        if len(content) > self.MAX_CONTENT_CHARS:
            content = content[: self.MAX_CONTENT_CHARS] + "\n…(truncated)"
        artifact = Artifact(
            kind=kind,
            name=name,
            content=content,
            language=language,
            iteration=iteration,
            metadata=dict(metadata or {}),
        )
        self._items.append(artifact)
        if self.persist_dir:
            self._persist(artifact)
        if self._on_add:
            try:
                self._on_add(artifact)
            except Exception:
                pass  # never let a callback kill the run
        return artifact

    def extract_from_output(self, text: str, *, iteration: int) -> list[Artifact]:
        """Scan an iteration's output for embedded artifacts and collect them.

        Recognized:
          - fenced code blocks (```LANG\\n…\\n```)           → kind=code
          - a leading top-level markdown doc (# Title\\n…)   → kind=markdown
        """
        if not text:
            return []
        added: list[Artifact] = []
        for i, (language, body) in enumerate(_iter_fences(text)):
            name = f"iter{iteration}-block{i+1}{_ext(language)}"
            added.append(
                self.add(
                    kind="code",
                    name=name,
                    content=body,
                    language=language,
                    iteration=iteration,
                )
            )

        # If the remaining non-fenced text reads like a doc (starts with '#'
        # and is substantial), capture it as a markdown artifact.
        non_fenced = _strip_fences(text).strip()
        if non_fenced.startswith("#") and len(non_fenced) > 200:
            title = non_fenced.split("\n", 1)[0].lstrip("# ").strip()[:80]
            name = f"iter{iteration}-{_slug(title) or 'doc'}.md"
            added.append(
                self.add(
                    kind="markdown",
                    name=name,
                    content=non_fenced,
                    iteration=iteration,
                )
            )
        return added

    def ingest_tool_metadata(
        self, tool_metadata: Any, iteration: int
    ) -> list[Artifact]:
        """If a tool result declared `artifact=True`, collect it.

        Expected shape: ``{"artifact": True, "kind": "...", "name": "...",
        "content": "..."}`` or a list of such dicts.
        """
        if isinstance(tool_metadata, dict) and tool_metadata.get("artifact"):
            return [self._from_meta(tool_metadata, iteration)]
        if isinstance(tool_metadata, list):
            return [
                self._from_meta(m, iteration)
                for m in tool_metadata
                if isinstance(m, dict) and m.get("artifact")
            ]
        return []

    # ── internals ───────────────────────────────────────────────

    def _from_meta(self, meta: dict[str, Any], iteration: int) -> Artifact:
        return self.add(
            kind=str(meta.get("kind", "file")),
            name=str(meta.get("name", f"iter{iteration}-unnamed")),
            content=str(meta.get("content", "")),
            language=meta.get("language"),
            iteration=iteration,
            metadata={
                k: v
                for k, v in meta.items()
                if k not in {"artifact", "kind", "name", "content", "language"}
            },
        )

    def _persist(self, a: Artifact) -> None:
        assert self.persist_dir is not None
        safe = _slug(a.name) or f"artifact-{len(self._items)}"
        path = self.persist_dir / f"{safe}.json"
        try:
            path.write_text(json.dumps(a.to_dict(), indent=2))
        except OSError:
            pass  # best-effort — disk errors shouldn't stop the run


# ── helpers ─────────────────────────────────────────────────────


_FENCE_RE = re.compile(r"```([a-zA-Z0-9_\-+.]*)\n([\s\S]*?)\n```", re.MULTILINE)
_LANG_EXT = {
    "python": ".py",
    "py": ".py",
    "ts": ".ts",
    "typescript": ".ts",
    "js": ".js",
    "javascript": ".js",
    "jsx": ".jsx",
    "tsx": ".tsx",
    "sh": ".sh",
    "bash": ".sh",
    "zsh": ".sh",
    "shell": ".sh",
    "rs": ".rs",
    "rust": ".rs",
    "go": ".go",
    "golang": ".go",
    "ruby": ".rb",
    "rb": ".rb",
    "java": ".java",
    "kt": ".kt",
    "kotlin": ".kt",
    "sql": ".sql",
    "yaml": ".yml",
    "yml": ".yml",
    "toml": ".toml",
    "json": ".json",
    "html": ".html",
    "css": ".css",
    "md": ".md",
    "markdown": ".md",
    "swift": ".swift",
    "cpp": ".cpp",
    "c": ".c",
}


def _iter_fences(text: str) -> Iterable[tuple[str, str]]:
    """Yield (language, body) for each fenced code block."""
    for m in _FENCE_RE.finditer(text):
        lang = (m.group(1) or "").strip().lower() or "text"
        body = m.group(2).rstrip("\n")
        if body:
            yield lang, body


def _strip_fences(text: str) -> str:
    return _FENCE_RE.sub("", text)


def _ext(language: str | None) -> str:
    if not language:
        return ".txt"
    return _LANG_EXT.get(language.lower(), ".txt")


def _slug(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip().lower())
    return cleaned.strip("-")[:80]
