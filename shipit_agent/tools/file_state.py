"""Which files this run has seen, so edits are made against known contents.

``edit_file`` refuses to patch a file the run has never read, and refuses
again if the file changed on disk since then. Both checks read the record
kept here in the run's shared tool state. Reading a file records it; so does
writing one, because the agent then knows its exact contents.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

READ_FILES_KEY = "read_files"
READ_MTIMES_KEY = "read_file_mtimes"


def record_file_seen(state: Any, path: Path) -> None:
    """Remember *path* and its current modification time in *state*.

    Does nothing when *state* is not the run's shared dict (a tool called
    outside a run has nowhere to record).
    """
    if not isinstance(state, dict):
        return
    key = str(path)
    seen = list(state.get(READ_FILES_KEY, []))
    if key not in seen:
        seen.append(key)
    state[READ_FILES_KEY] = seen
    mtimes = dict(state.get(READ_MTIMES_KEY, {}))
    try:
        mtimes[key] = path.stat().st_mtime_ns
    except OSError:
        pass
    state[READ_MTIMES_KEY] = mtimes


def changed_on_disk(state: Any, path: Path) -> bool:
    """Whether *path* was modified after the run last read or wrote it."""
    recorded = (
        (state.get("read_file_mtimes") or {}).get(str(path))
        if isinstance(state, dict)
        else None
    )
    if recorded is None:
        return False
    try:
        return path.stat().st_mtime_ns != recorded
    except OSError:
        return False


#: read_file's line-number gutter: optional spaces, digits, a colon, a space.
_GUTTER = re.compile(r"^\s*\d+: ", re.MULTILINE)


def missing_text_hint(old_text: str, content: str) -> str:
    """Why *old_text* may be missing from *content*, as one sentence, or ``""``.

    Names the commonest cause: line numbers copied from read_file's output.
    """
    if _GUTTER.search(old_text):
        stripped = _GUTTER.sub("", old_text)
        if stripped and stripped in content:
            return (
                " old_text includes read_file's line-number prefixes (like "
                "'  12: '); copy only the text after them."
            )
        return (
            " old_text looks like it includes read_file's line-number "
            "prefixes (like '  12: '); copy only the text after them."
        )
    return ""
