"""Undo an applied action — for the cases where undo is actually possible.

``ToolContract.implements_revert`` used to be a claim with nothing behind it:
eighteen contracts promised revert and zero implementations existed. A UI
reading the flag would offer an undo button that did nothing, which is worse
than offering none.

So the flag now means something checkable: **a contract may only set
``implements_revert=True`` if a reverter is registered for its tool**, and a
test enforces that. Where undo is genuinely impossible the flag is false and
the UI correctly declines to offer it.

What is implementable generically:

- **Filesystem writes.** Snapshot the target before applying; restore it after.
  Covers ``write_file``, ``edit_file``, ``notebook_edit``, ``download_file``
  and the artifact builders — a file that did not exist is deleted again, and
  one that did is put back byte-for-byte.

What is not, and is therefore now declared honestly:

- **Connector writes.** Undoing a Jira comment, a Notion page edit or a Drive
  upload needs a per-vendor inverse operation with its own auth, failure modes
  and race conditions. Cloudflare OS pushes this onto each Gatekeeper for that
  reason. Registering a reverter per connector is the path; until one exists,
  the contract says false.
- **Sends.** You cannot unsend a Slack message. ``comms.send`` was always
  false and stays false.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

__all__ = [
    "Reverter",
    "FileSnapshot",
    "FileSnapshotReverter",
    "REVERTERS",
    "register_reverter",
    "reverter_for",
    "can_revert",
]


class Reverter(Protocol):
    """Captures enough state before an action to undo it afterwards."""

    def capture(self, tool: str, arguments: dict[str, Any]) -> Any:
        """Snapshot whatever the action is about to change."""
        ...

    def restore(self, snapshot: Any) -> None:
        """Put it back. Raises if it cannot."""
        ...


# ── filesystem ───────────────────────────────────────────────────────────

# Argument names that name the file an action will write.
_PATH_KEYS = ("path", "file", "filename", "notebook_path", "target", "output_path")


@dataclass(slots=True)
class FileSnapshot:
    """One file's state before an action touched it."""

    path: Path
    existed: bool
    backup: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"path": str(self.path), "existed": self.existed}


@dataclass(slots=True)
class FileSnapshotReverter:
    """Copy a file aside before it is written; copy it back to undo.

    A file that did not exist before is *deleted* on revert rather than left
    empty — restoring "nothing" has to mean nothing, or a revert leaves litter
    that looks like real output.
    """

    backup_root: Path | None = None
    _backups: list[Path] = field(default_factory=list, repr=False)

    def _root(self) -> Path:
        if self.backup_root is None:
            self.backup_root = Path(tempfile.mkdtemp(prefix="shipit-revert-"))
        else:
            # A caller-supplied root may not exist yet; mkdtemp creates its
            # own, so only this path needs it.
            self.backup_root.mkdir(parents=True, exist_ok=True)
        return self.backup_root

    def capture(self, tool: str, arguments: dict[str, Any]) -> FileSnapshot | None:
        target = _target_path(arguments)
        if target is None:
            # Nothing identifiable to snapshot — better to report that we
            # cannot revert than to silently "succeed" at restoring nothing.
            return None
        if not target.exists():
            return FileSnapshot(path=target, existed=False)

        backup = self._root() / f"{len(self._backups)}-{target.name}"
        shutil.copy2(target, backup)
        self._backups.append(backup)
        return FileSnapshot(path=target, existed=True, backup=backup)

    def restore(self, snapshot: FileSnapshot | None) -> None:
        if snapshot is None:
            raise ValueError("nothing was captured for this action")
        if not snapshot.existed:
            if snapshot.path.exists():
                snapshot.path.unlink()
            return
        if snapshot.backup is None or not snapshot.backup.exists():
            raise FileNotFoundError(
                f"the backup for {snapshot.path} is gone; cannot revert"
            )
        snapshot.path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(snapshot.backup, snapshot.path)

    def cleanup(self) -> None:
        """Drop the backups. After this, revert is no longer possible."""
        if self.backup_root and self.backup_root.exists():
            shutil.rmtree(self.backup_root, ignore_errors=True)
        self._backups.clear()


def _target_path(arguments: dict[str, Any]) -> Path | None:
    for key in _PATH_KEYS:
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            return Path(value).expanduser()
    return None


# ── registry ─────────────────────────────────────────────────────────────

_FILE_REVERTER = FileSnapshotReverter()

# Only these can actually be undone today. The contract table mirrors this
# exactly, and a test asserts the two never drift.
REVERTERS: dict[str, Reverter] = {
    "write_file": _FILE_REVERTER,
    "edit_file": _FILE_REVERTER,
    "notebook_edit": _FILE_REVERTER,
    "download_file": _FILE_REVERTER,
    "build_document": _FILE_REVERTER,
    "build_artifact": _FILE_REVERTER,
    "render_dashboard": _FILE_REVERTER,
}


def register_reverter(tool: str, reverter: Reverter) -> None:
    """Teach the queue how to undo one tool.

    Registering a reverter is what earns a contract the right to set
    ``implements_revert=True``; without one the flag would be a promise
    nothing keeps::

        register_reverter("jira", JiraReverter())
        register_contract("jira", ToolContract(
            action_kind=ISSUE_WRITE, implements_revert=True, auto_approvable=True,
        ))
    """
    if not (hasattr(reverter, "capture") and hasattr(reverter, "restore")):
        raise TypeError("a reverter needs capture() and restore()")
    REVERTERS[tool] = reverter


def reverter_for(tool: str) -> Reverter | None:
    return REVERTERS.get(tool)


def can_revert(tool: str) -> bool:
    """Is undo actually implemented for this tool?"""
    return tool in REVERTERS
