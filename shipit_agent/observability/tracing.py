"""Trace records for a run and the stores that keep them (in memory or on disk).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

from shipit_agent.core.models import AgentEvent


@dataclass(slots=True)
class TraceRecord:
    """Every event recorded for one trace, with its metadata."""
    trace_id: str
    metadata: dict[str, Any] = field(default_factory=dict)
    events: list[AgentEvent] = field(default_factory=list)


class TraceStore(Protocol):
    """Where run events are recorded and read back by trace id."""
    def append_event(
        self, trace_id: str, event: AgentEvent, metadata: dict[str, Any] | None = None
    ) -> None: ...

    def load(self, trace_id: str) -> TraceRecord | None: ...


class InMemoryTraceStore:
    """A trace store that lives for the life of the process."""
    def __init__(self) -> None:
        self._records: dict[str, TraceRecord] = {}

    def append_event(
        self, trace_id: str, event: AgentEvent, metadata: dict[str, Any] | None = None
    ) -> None:
        record = self._records.setdefault(
            trace_id, TraceRecord(trace_id=trace_id, metadata=dict(metadata or {}))
        )
        if metadata:
            record.metadata.update(metadata)
        record.events.append(event)

    def load(self, trace_id: str) -> TraceRecord | None:
        return self._records.get(trace_id)


class FileTraceStore:
    """A trace store that writes one JSON file per trace in a folder."""
    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, trace_id: str) -> Path:
        return self.root_dir / f"{trace_id}.json"

    def load(self, trace_id: str) -> TraceRecord | None:
        path = self._path_for(trace_id)
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        return TraceRecord(
            trace_id=raw["trace_id"],
            metadata=dict(raw.get("metadata", {})),
            events=[AgentEvent(**event) for event in raw.get("events", [])],
        )

    def append_event(
        self, trace_id: str, event: AgentEvent, metadata: dict[str, Any] | None = None
    ) -> None:
        record = self.load(trace_id) or TraceRecord(trace_id=trace_id)
        if metadata:
            record.metadata.update(metadata)
        record.events.append(event)
        payload = {
            "trace_id": record.trace_id,
            "metadata": record.metadata,
            "events": [asdict(item) for item in record.events],
        }
        self._path_for(trace_id).write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
