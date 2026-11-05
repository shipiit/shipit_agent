"""File checkpoints for ``rewind_files``, as in the Claude Agent SDK.

Before the first write to a file in a turn, its contents (or its absence)
are recorded under that turn's user message id. Rewinding to a message puts
back every file that turn and the turns after it changed, and deletes the
files they created. Like the SDK's, this covers the file tools (edit, write,
multi-edit, notebook edit), not files a shell command changed.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

__all__ = ["FileCheckpoints", "WRITING_TOOLS"]

WRITING_TOOLS = frozenset({"edit_file", "write_file", "multi_edit", "notebook_edit"})


class FileCheckpoints:
    """Files' contents before each turn changed them, newest turn last."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._turns: list[tuple[str, dict[Path, bytes | None]]] = []
        self._lock = threading.Lock()

    def begin_turn(self, user_message_id: str) -> None:
        with self._lock:
            self._turns.append((user_message_id, {}))

    def before_tool(self, name: str, arguments: dict[str, Any]) -> None:
        """A before-tool hook: remember the file a writing tool is about to change."""
        path = arguments.get("path")
        if name not in WRITING_TOOLS or not isinstance(path, str) or not path or not self._turns:
            return None
        target = Path(path) if Path(path).is_absolute() else self.root / path
        target = target.resolve()
        with self._lock:
            saved = self._turns[-1][1]
            # Each turn keeps the file as it found it, so rewinding to any turn
            # can restore the state between turns.
            if target not in saved:
                saved[target] = target.read_bytes() if target.is_file() else None
        return None

    def rewind(self, user_message_id: str) -> list[Path]:
        """Restore files to how they were before *user_message_id*; the paths touched."""
        with self._lock:
            index = next((i for i, (turn, _) in enumerate(self._turns) if turn == user_message_id), None)
            if index is None:
                raise KeyError(f"no checkpoint for user message {user_message_id!r}")
            restored: dict[Path, bytes | None] = {}
            for _, saved in reversed(self._turns[index:]):
                restored.update(saved)
            del self._turns[index:]
        for path, content in restored.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
        return sorted(restored)
