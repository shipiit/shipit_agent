"""Project memory — auto-load ``SHIPIT.md`` / ``AGENTS.md`` instructions.

The SHIPIT answer to a project instructions file: drop a ``SHIPIT.md`` (or the
conventional ``AGENTS.md``) at your repo root and every agent pointed at that
project picks it up automatically — no code. A user-global
``~/.shipit/SHIPIT.md`` applies everywhere. Files may pull in others with
``@relative/path`` imports.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# Searched in order; the first existing project file(s) + the user-global one
# are all included (project context first).
PROJECT_FILES: tuple[str, ...] = (
    "SHIPIT.md",
    "AGENTS.md",
    ".shipit/SHIPIT.md",
    ".shipit/AGENTS.md",
)
USER_FILES: tuple[str, ...] = ("~/.shipit/SHIPIT.md", "~/.shipit/AGENTS.md")

_IMPORT_RE = re.compile(r"^@([^\s]+)[ \t]*$", re.MULTILINE)


def load_project_memory(
    project_root: str | Path,
    *,
    include_user: bool = True,
    max_depth: int = 5,
) -> str:
    """Return a single prompt block of project + user instruction files.

    Resolves ``@path`` imports relative to the importing file (depth-limited,
    cycle-safe). Returns ``""`` when no instruction files exist.
    """
    root = Path(project_root).resolve()
    blocks: list[tuple[Path, str]] = []
    seen: set[Path] = set()

    def _read(path: Path, depth: int) -> None:
        try:
            path = path.resolve()
        except Exception:
            return
        if path in seen or depth > max_depth or not path.is_file():
            return
        seen.add(path)
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            return

        def _expand(match: re.Match[str]) -> str:
            ref = Path(os.path.expanduser(match.group(1)))
            if not ref.is_absolute():
                ref = path.parent / ref
            _read(ref, depth + 1)  # imported content is appended as its own block
            return ""

        body = _IMPORT_RE.sub(_expand, text).strip()
        if body:
            blocks.append((path, body))

    for rel in PROJECT_FILES:
        _read(root / rel, 0)
    if include_user:
        for rel in USER_FILES:
            _read(Path(os.path.expanduser(rel)), 0)

    if not blocks:
        return ""

    parts: list[str] = []
    for path, body in blocks:
        try:
            label: Path | str = path.relative_to(root)
        except ValueError:
            label = path.name
        parts.append(f"<!-- {label} -->\n{body}")
    return (
        "# Project instructions\n\n"
        "The following instructions come from this project's SHIPIT.md / "
        "AGENTS.md. Follow them unless the user says otherwise.\n\n"
        + "\n\n".join(parts)
    )
