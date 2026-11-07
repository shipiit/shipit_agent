"""Where the file tools may go: the project root, and any folders added beside it."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence


def resolve_in_roots(raw: str | Path, root: Path, extra_roots: Sequence[Path] = ()) -> Path:
    """*raw* resolved, if it lies under *root* or one of *extra_roots*.

    A relative path means the project root. Containment is checked after
    resolving symlinks and "..", so neither can walk out; ``is_relative_to``
    keeps symlinked roots (/tmp -> /private/tmp) from false refusals.
    """
    path = Path(raw)
    candidate = path.resolve() if path.is_absolute() else (root / path).resolve()
    if any(candidate.is_relative_to(base) for base in (root, *extra_roots)):
        return candidate
    allowed = " or ".join(str(base) for base in (root, *extra_roots))
    raise ValueError(f"Path escapes project root: {candidate} is not under {allowed}")


def shown_path(path: Path, root: Path) -> str:
    """How a path is shown: relative to the project root, absolute when outside it."""
    return str(path.relative_to(root)) if path.is_relative_to(root) else str(path)


def as_roots(folders: Sequence[str | Path]) -> tuple[Path, ...]:
    """Folders given by a caller, resolved, for a tool's ``extra_roots``."""
    return tuple(Path(folder).expanduser().resolve() for folder in folders)
