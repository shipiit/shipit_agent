"""What every core tool needs: a workspace, and a bounded result.

One shared workspace rather than per-tool state, because the read-before-write
contract only holds if the reader and the editor agree on what was read. One
result helper, because a tool result that is unbounded is a tool result that is
re-sent on every following turn.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Sequence

from shipit_agent.toolkit.contracts import ReadTracker, truncate_output

__all__ = ["Workspace", "ToolBase", "IGNORED_DIRS", "walk", "is_ignored"]

#: Directories never worth walking. Not an optimisation — a grep returning four
#: thousand hits from node_modules is a grep that returned nothing useful and
#: cost a fortune to deliver.
IGNORED_DIRS = frozenset(
    {
        ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
        ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build",
        ".next", ".nuxt", "target", ".tox", ".idea", ".DS_Store", ".shipit",
    }
)


def is_ignored(path: Path, root: Path) -> bool:
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        return False
    return any(part in IGNORED_DIRS for part in parts)


def walk(root: Path) -> Iterator[Path]:
    """Every file under *root*, skipping the noise directories."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS]
        for filename in filenames:
            yield Path(dirpath) / filename


@dataclass
class Workspace:
    """Where the tools work, and what has been read.

    Shared by every core tool in one agent. A per-tool tracker would let a file
    read by one tool look unread to another, which silently disables the
    contract it exists to enforce.
    """

    root: Path = field(default_factory=Path.cwd)
    reads: ReadTracker = field(default_factory=ReadTracker)
    max_output_chars: int = 16_000
    timeout_seconds: int = 120

    def __post_init__(self) -> None:
        self.root = Path(self.root).expanduser().resolve()

    def resolve(self, path: str | Path) -> Path:
        """Resolve inside the workspace, refusing to escape it.

        Containment is checked after resolution, so symlinks and ``..`` cannot
        walk out — checking the string first catches neither.
        """
        target = (self.root / Path(path).expanduser()).resolve()
        if not str(target).startswith(str(self.root)):
            raise ValueError(f"{path} is outside the workspace ({self.root})")
        return target

    def relative(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.root))
        except ValueError:
            return str(path)


class ToolBase:
    """Name, description, schema shape, and a bounded result."""

    name = ""
    description = ""
    prompt_instructions = ""

    def __init__(self, workspace: Workspace | None = None) -> None:
        self.workspace = workspace or Workspace()

    # -- results -----------------------------------------------------------

    def ok(self, text: str, hint: str = "", **metadata: Any) -> Any:
        from shipit_agent.tools_compat import make_output

        bounded, cut = truncate_output(
            text, limit=self.workspace.max_output_chars, recovery_hint=hint
        )
        return make_output(bounded, metadata={**metadata, "truncated": cut})

    def fail(self, text: str, **metadata: Any) -> Any:
        """An error the model can act on. Never an exception: a tool that raises
        ends a run the model could have recovered from in one turn."""
        from shipit_agent.tools_compat import make_output

        return make_output(text, metadata={**metadata, "is_error": True})

    # -- schema ------------------------------------------------------------

    def build_schema(
        self, properties: dict[str, Any], required: Sequence[str] = ()
    ) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": list(required),
                },
            },
        }
