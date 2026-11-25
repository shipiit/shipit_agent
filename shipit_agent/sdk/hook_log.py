"""Hook lifecycle messages (``include_hook_events``), collected as hooks run.

Hooks run on the agent's worker threads, so their start and result are kept
here and handed to the message stream between events.
"""

from __future__ import annotations

import json
import threading
import uuid
from typing import Any

__all__ = ["HookLog"]


class HookLog:
    """A thread-safe list of ``hook_started`` / ``hook_response`` records."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: list[tuple[str, dict[str, Any]]] = []

    def started(self, event: str, name: str) -> str:
        hook_id = str(uuid.uuid4())
        self._add("hook_started", {"hook_id": hook_id, "hook_name": name, "hook_event": event})
        return hook_id

    def finished(self, hook_id: str, event: str, name: str, output: Any, error: str | None) -> None:
        text = json.dumps(output, default=str) if output else ""
        self._add("hook_response", {
            "hook_id": hook_id, "hook_name": name, "hook_event": event, "output": text,
            "stdout": text, "stderr": error or "", "exit_code": None,
            "outcome": "error" if error is not None else "success",
        })

    def _add(self, subtype: str, data: dict[str, Any]) -> None:
        with self._lock:
            self._items.append((subtype, {**data, "uuid": str(uuid.uuid4())}))

    def drain(self) -> list[tuple[str, dict[str, Any]]]:
        with self._lock:
            items, self._items = self._items, []
        return items
