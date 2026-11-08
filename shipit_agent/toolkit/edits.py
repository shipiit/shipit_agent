"""Edit contracts: read tracking, unique-match edits and their errors."""

from __future__ import annotations

import difflib
import hashlib
from dataclasses import dataclass, field
from pathlib import Path


class EditError(Exception):
    """Base for edit preconditions. Always rendered as a tool result."""


class UnreadFileError(EditError):
    """The file has not been read in this session."""


class StaleReadError(EditError):
    """The file changed on disk after it was read."""


class MatchError(EditError):
    """``old_str`` did not match exactly once."""


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


@dataclass
class ReadTracker:
    """Remembers which files this session read, and what they looked like.

    Keyed by resolved path, so ``./src/a.py`` and ``src/a.py`` are one entry —
    otherwise a file read by one spelling and written by another slips the
    check, which is the whole failure this class prevents.
    """

    #: path → content digest at the time of the read.
    seen: dict[str, str] = field(default_factory=dict)

    @staticmethod
    def _key(path: str | Path) -> str:
        return str(Path(path).expanduser().resolve())

    def record_read(self, path: str | Path, content: str) -> None:
        self.seen[self._key(path)] = _digest(content)

    def has_read(self, path: str | Path) -> bool:
        return self._key(path) in self.seen

    def forget(self, path: str | Path) -> None:
        self.seen.pop(self._key(path), None)

    def check_writable(self, path: str | Path, current_content: str) -> None:
        """Raise unless *path* was read this session and has not changed since.

        Called before every edit. Both failures are recoverable: the model reads
        the file and retries, which is one extra turn rather than a lost run.
        """
        key = self._key(path)
        recorded = self.seen.get(key)
        if recorded is None:
            raise UnreadFileError(
                f"{path} has not been read in this session. Read it first, then "
                "edit — editing a file you have not seen risks destroying "
                "content you did not know was there."
            )
        if recorded != _digest(current_content):
            raise StaleReadError(
                f"{path} changed on disk since it was read. Read it again "
                "before editing, or the edit will be based on stale content."
            )


def _near_miss(content: str, needle: str, *, cutoff: float = 0.6) -> str | None:
    """The closest line-window to *needle*, for a useful failure message."""
    needle_lines = needle.splitlines() or [needle]
    span = len(needle_lines)
    lines = content.splitlines()
    if not lines:
        return None
    windows = [
        "\n".join(lines[i : i + span]) for i in range(max(1, len(lines) - span + 1))
    ]
    matches = difflib.get_close_matches(needle, windows, n=1, cutoff=cutoff)
    return matches[0] if matches else None


def apply_unique_edit(
    content: str,
    old_str: str,
    new_str: str,
    *,
    path: str = "",
) -> str:
    """Replace *old_str* with *new_str*, requiring exactly one match.

    Zero matches raises with the nearest near-miss attached, which usually shows
    the model the whitespace or quoting difference immediately. Two or more
    raises asking for more surrounding context, because picking one silently is
    how an edit lands in the wrong place.
    """
    if not old_str:
        raise MatchError("old_str is empty; give the exact text to replace.")

    count = content.count(old_str)
    if count == 1:
        return content.replace(old_str, new_str, 1)

    where = f" in {path}" if path else ""
    if count == 0:
        near = _near_miss(content, old_str)
        hint = (
            f"\nClosest text found{where}:\n---\n{near}\n---"
            if near
            else "\nNo similar text found — check the file was read correctly."
        )
        raise MatchError(
            f"old_str was not found{where}. It must match the file exactly, "
            f"including indentation and line endings.{hint}"
        )
    raise MatchError(
        f"old_str matched {count} times{where}; an edit must be unambiguous. "
        "Include more surrounding lines so exactly one location matches."
    )

