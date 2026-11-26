"""Scrub events before they leave the process for a tracing backend."""

from __future__ import annotations

import dataclasses
import re
from typing import Any, Callable

from shipit_agent.core.models import AgentEvent
from shipit_agent.observability.tracing import TraceRecord, TraceStore
from shipit_agent.safety.guardrail_patterns import _PII_PATTERNS, _SECRET_PATTERNS

#: Ids join a trace together; their digits are not phone or card numbers.
_UUID = re.compile(r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})")
_CREDENTIAL_KEY = re.compile(r"(?i)(api[_-]?key|authorization|password|passwd|secret|token|cookie|credential)")


class RedactingTraceStore:
    """Wrap a trace store or exporter so it only ever sees scrubbed events.

    Secrets matching the guardrail patterns, and any value under a key that
    names a credential, are replaced; ``pii=True`` also redacts emails, phone,
    card and SSN numbers; ``redact`` runs last on every string. The run's own
    events are not changed, only the copies handed to *inner*::

        Agent(llm=llm, trace_store=RedactingTraceStore(LangfuseExporter(...), pii=True))
    """

    def __init__(
        self, inner: TraceStore, *, pii: bool = False, redact: Callable[[str], str] | None = None
    ) -> None:
        self.inner = inner
        self._patterns = list(_SECRET_PATTERNS) + (list(_PII_PATTERNS) if pii else [])
        self._redact = redact

    def append_event(self, trace_id: str, event: AgentEvent, metadata: dict[str, Any] | None = None) -> None:
        scrubbed = dataclasses.replace(event, message=self._text(event.message), payload=self._value(event.payload))
        self.inner.append_event(trace_id, scrubbed, self._value(metadata) if metadata else metadata)

    def load(self, trace_id: str) -> TraceRecord | None:
        return self.inner.load(trace_id)

    def _text(self, text: str) -> str:
        pieces = _UUID.split(text)  # odd pieces are the UUIDs, kept as they are
        for index in range(0, len(pieces), 2):
            for kind, pattern in self._patterns:
                pieces[index] = pattern.sub(f"[REDACTED:{kind}]", pieces[index])
        text = "".join(pieces)
        return self._redact(text) if self._redact is not None else text

    def _value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self._text(value)
        if isinstance(value, dict):
            return {
                # Credentials are strings; "input_tokens": 120 is a count, not a token.
                key: "[REDACTED]"
                if isinstance(key, str) and isinstance(item, str) and item and _CREDENTIAL_KEY.search(key)
                else self._value(item)
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return type(value)(self._value(item) for item in value)
        return value
