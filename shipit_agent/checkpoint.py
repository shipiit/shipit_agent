"""Enough state to stop a run and start it again somewhere else.

A run that pauses for human approval, hits a rate limit worth waiting out, or
simply outlives its process, has to be resumable — and resuming a *conversation*
is not enough. Three pieces of state live outside the message list and are lost
if only messages are saved:

* **Primed skills.** A run that loaded three skills before pausing must come
  back with those three loaded, or it silently resumes less capable than it
  paused, and the tools they unlocked disappear with them.
* **Discovered deferred tools.** With progressive tool disclosure, a tool's
  schema is bound only after a search found it. On resume the search results
  live in the checkpoint, not in the replayed history, so the names have to be
  carried explicitly or the paused tool call has no schema to validate against.
* **The pending approval itself.** Which call was interrupted, with which
  arguments, so the decision can be applied to the right thing.

Serialisation is plain JSON via injected message coders, so this module works
with the host's ``Message`` type without importing it, and a checkpoint written
by one version stays readable by the next.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

__all__ = [
    "PendingApproval",
    "RunCheckpoint",
    "CheckpointStore",
    "FileCheckpointStore",
    "InMemoryCheckpointStore",
]

CHECKPOINT_VERSION = 1


class _Coder(Protocol):
    def __call__(self, value: Any) -> Any: ...


def _default_encode(message: Any) -> Any:
    to_dict = getattr(message, "to_dict", None)
    return to_dict() if callable(to_dict) else message


@dataclass(frozen=True, slots=True)
class PendingApproval:
    """The tool call a run stopped on."""

    tool_call_id: str
    tool_name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_call_id": self.tool_call_id,
            "tool_name": self.tool_name,
            "arguments": dict(self.arguments),
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PendingApproval":
        return cls(
            tool_call_id=str(data.get("tool_call_id", "")),
            tool_name=str(data.get("tool_name", "")),
            arguments=dict(data.get("arguments") or {}),
            reason=str(data.get("reason", "")),
        )


@dataclass
class RunCheckpoint:
    """Everything needed to continue a run in a fresh process."""

    run_id: str
    session_id: str = ""
    iteration: int = 0
    messages: list[Any] = field(default_factory=list)
    #: Serialised :class:`~skills.catalog.SkillSession`.
    skills: dict[str, Any] = field(default_factory=dict)
    #: Deferred tools whose schemas were discovered before the pause. Without
    #: these the rebuilt binding omits exactly the tool the run stopped on.
    discovered_tools: list[str] = field(default_factory=list)
    pending_approval: PendingApproval | None = None
    #: Fingerprint of the prompt prefix at pause. A mismatch on resume means
    #: config changed underneath the run — worth warning about, not fatal.
    prefix_fingerprint: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    version: int = CHECKPOINT_VERSION

    # -- serialisation -----------------------------------------------------

    def to_dict(self, *, encode_message: _Coder = _default_encode) -> dict[str, Any]:
        return {
            "version": self.version,
            "run_id": self.run_id,
            "session_id": self.session_id,
            "iteration": self.iteration,
            "messages": [encode_message(m) for m in self.messages],
            "skills": dict(self.skills),
            "discovered_tools": sorted(set(self.discovered_tools)),
            "pending_approval": (
                self.pending_approval.to_dict() if self.pending_approval else None
            ),
            "prefix_fingerprint": self.prefix_fingerprint,
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
        *,
        decode_message: Callable[[Any], Any] = lambda value: value,
    ) -> "RunCheckpoint":
        approval = data.get("pending_approval")
        return cls(
            run_id=str(data.get("run_id", "")),
            session_id=str(data.get("session_id", "")),
            iteration=int(data.get("iteration", 0) or 0),
            messages=[decode_message(m) for m in (data.get("messages") or [])],
            skills=dict(data.get("skills") or {}),
            discovered_tools=list(data.get("discovered_tools") or []),
            pending_approval=(
                PendingApproval.from_dict(approval)
                if isinstance(approval, Mapping)
                else None
            ),
            prefix_fingerprint=str(data.get("prefix_fingerprint", "")),
            metadata=dict(data.get("metadata") or {}),
            created_at=float(data.get("created_at", time.time())),
            version=int(data.get("version", CHECKPOINT_VERSION) or CHECKPOINT_VERSION),
        )

    # -- helpers -----------------------------------------------------------

    def drift_from(self, current_fingerprint: str) -> bool:
        """True when the prompt prefix changed while the run was paused."""
        return bool(
            self.prefix_fingerprint
            and current_fingerprint
            and self.prefix_fingerprint != current_fingerprint
        )


class CheckpointStore(Protocol):
    def save(self, checkpoint: RunCheckpoint) -> None: ...
    def load(self, run_id: str) -> RunCheckpoint | None: ...
    def delete(self, run_id: str) -> None: ...
    def list_ids(self) -> Sequence[str]: ...


class InMemoryCheckpointStore:
    """For tests and single-process runs."""

    def __init__(self) -> None:
        self._items: dict[str, RunCheckpoint] = {}

    def save(self, checkpoint: RunCheckpoint) -> None:
        self._items[checkpoint.run_id] = checkpoint

    def load(self, run_id: str) -> RunCheckpoint | None:
        return self._items.get(run_id)

    def delete(self, run_id: str) -> None:
        self._items.pop(run_id, None)

    def list_ids(self) -> list[str]:
        return sorted(self._items)


class FileCheckpointStore:
    """JSON on disk, written atomically.

    A checkpoint truncated by a crash mid-write would make the run
    unresumable — the one situation the file exists to prevent — so every write
    goes to a temp file and is renamed into place. A corrupt or unreadable file
    loads as ``None`` (a miss) rather than raising: a failed resume should fall
    back to a fresh run, not to a traceback.
    """

    def __init__(
        self,
        directory: str | Path,
        *,
        encode_message: _Coder = _default_encode,
        decode_message: Callable[[Any], Any] = lambda value: value,
    ) -> None:
        self._dir = Path(directory)
        self._encode = encode_message
        self._decode = decode_message

    def _path(self, run_id: str) -> Path:
        safe = "".join(c for c in run_id if c.isalnum() or c in "-_")
        return self._dir / f"{safe or 'run'}.json"

    def save(self, checkpoint: RunCheckpoint) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._path(checkpoint.run_id)
        payload = json.dumps(
            checkpoint.to_dict(encode_message=self._encode),
            indent=2,
            default=str,
        )
        handle = tempfile.NamedTemporaryFile(
            "w", dir=self._dir, delete=False, encoding="utf-8", suffix=".tmp"
        )
        try:
            with handle as tmp:
                tmp.write(payload)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(handle.name, path)
        except Exception:
            Path(handle.name).unlink(missing_ok=True)
            raise

    def load(self, run_id: str) -> RunCheckpoint | None:
        path = self._path(run_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        return RunCheckpoint.from_dict(data, decode_message=self._decode)

    def delete(self, run_id: str) -> None:
        self._path(run_id).unlink(missing_ok=True)

    def list_ids(self) -> list[str]:
        if not self._dir.exists():
            return []
        return sorted(p.stem for p in self._dir.glob("*.json"))
