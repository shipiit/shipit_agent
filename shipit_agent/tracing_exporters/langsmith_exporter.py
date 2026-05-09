"""LangSmith trace exporter.

Implements the :class:`shipit_agent.tracing.TraceStore` protocol by batching
``AgentEvent`` records and POSTing them to the LangSmith ``/runs`` endpoint.
No third-party dependency is required; all HTTP goes through ``urllib.request``.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from shipit_agent.models import AgentEvent
from shipit_agent.tracing import TraceRecord

logger = logging.getLogger(__name__)

_DEFAULT_BATCH_SIZE = 20
_DEFAULT_FLUSH_INTERVAL = 2.0


class LangSmithExporter:
    """Stream ``AgentEvent`` records to LangSmith as runs.

    Spans are batched in-memory; a batch is flushed when it reaches
    ``batch_size`` events or when ``flush_interval_seconds`` has elapsed
    since the first buffered event -- whichever comes first. Transport
    failures are logged at ``WARNING`` and never raised to the caller.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_url: str = "https://api.smith.langchain.com",
        project: str = "shipit-agent",
        timeout_seconds: float = 5.0,
        batch_size: int = _DEFAULT_BATCH_SIZE,
        flush_interval_seconds: float = _DEFAULT_FLUSH_INTERVAL,
        time_source: Callable[[], float] = time.monotonic,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.environ.get(
            "LANGCHAIN_API_KEY"
        )
        self.api_url = api_url.rstrip("/")
        self.project = project
        self.timeout_seconds = timeout_seconds
        self.batch_size = max(1, batch_size)
        self.flush_interval_seconds = flush_interval_seconds
        self._time = time_source

        self._lock = threading.Lock()
        self._buffer: list[dict[str, Any]] = []
        self._buffer_started_at: float | None = None

    # ------------------------------------------------------------------
    # TraceStore protocol
    # ------------------------------------------------------------------
    def append_event(
        self,
        trace_id: str,
        event: AgentEvent,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        run = self._event_to_run(trace_id, event, metadata or {})
        should_flush = False
        with self._lock:
            if self._buffer_started_at is None:
                self._buffer_started_at = self._time()
            self._buffer.append(run)
            if len(self._buffer) >= self.batch_size:
                should_flush = True
            elif (
                self._buffer_started_at is not None
                and (self._time() - self._buffer_started_at)
                >= self.flush_interval_seconds
            ):
                should_flush = True
        if should_flush:
            self.flush()

    def load(self, trace_id: str) -> TraceRecord | None:
        # Exporters write out to an external backend and do not read back.
        return None

    # ------------------------------------------------------------------
    # Flushing
    # ------------------------------------------------------------------
    def flush(self) -> None:
        """Flush any buffered runs to LangSmith immediately."""
        with self._lock:
            if not self._buffer:
                self._buffer_started_at = None
                return
            batch = self._buffer
            self._buffer = []
            self._buffer_started_at = None

        if not self.api_key:
            logger.warning(
                "LangSmithExporter has no API key configured; dropping %d run(s).",
                len(batch),
            )
            return

        self._post(batch)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _event_to_run(
        self,
        trace_id: str,
        event: AgentEvent,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        payload = _to_plain(event.payload)
        extra_metadata = _to_plain(metadata)
        return {
            "name": str(event.type),
            "run_type": "chain",
            "inputs": {"message": event.message},
            "outputs": payload,
            "start_time": now,
            "end_time": now,
            "extra": {
                "trace_id": trace_id,
                "project": self.project,
                "metadata": extra_metadata,
            },
        }

    def _post(self, batch: list[dict[str, Any]]) -> None:
        url = f"{self.api_url}/runs"
        body = json.dumps({"runs": batch}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key or "",
            },
        )
        try:
            urllib.request.urlopen(req, timeout=self.timeout_seconds)
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            logger.warning(
                "LangSmithExporter failed to post %d run(s) to %s: %s",
                len(batch),
                url,
                exc,
            )


def _to_plain(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _to_plain(asdict(value))
    if isinstance(value, dict):
        return {str(k): _to_plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_plain(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
