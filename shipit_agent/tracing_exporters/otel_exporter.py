"""OpenTelemetry trace exporter.

Translates each incoming ``AgentEvent`` into an OpenTelemetry span on the
provided tracer provider. ``opentelemetry`` is a lazy import -- the package
is only required at instantiation time.
"""

from __future__ import annotations

import logging
from typing import Any

from shipit_agent.models import AgentEvent
from shipit_agent.tracing import TraceRecord

logger = logging.getLogger(__name__)

_INSTALL_HINT = "Install opentelemetry-api and opentelemetry-sdk."


class OpenTelemetryExporter:
    """Emit ``AgentEvent`` records as OpenTelemetry spans.

    Because the trace data supplied to :meth:`append_event` is already
    finalized, each span is started and ended within the same call (no
    context managers). Event payload values become span attributes, and
    any entries under ``payload['events']`` become OTel span events.
    """

    def __init__(
        self,
        *,
        service_name: str = "shipit-agent",
        tracer_provider: Any = None,
    ) -> None:
        try:
            from opentelemetry import trace as _trace
        except ImportError as exc:  # pragma: no cover - exercised via monkeypatch
            raise RuntimeError(_INSTALL_HINT) from exc

        self._trace = _trace
        self.service_name = service_name
        self.tracer_provider = (
            tracer_provider
            if tracer_provider is not None
            else _trace.get_tracer_provider()
        )
        self._tracer = self.tracer_provider.get_tracer(service_name)

    # ------------------------------------------------------------------
    # TraceStore protocol
    # ------------------------------------------------------------------
    def append_event(
        self,
        trace_id: str,
        event: AgentEvent,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        name = f"agent.{event.type}"
        attributes: dict[str, Any] = {
            "shipit.trace_id": trace_id,
            "shipit.event.type": str(event.type),
            "shipit.event.message": event.message,
        }
        sub_events: list[dict[str, Any]] = []
        for key, value in (event.payload or {}).items():
            if key == "events" and isinstance(value, list):
                sub_events = [v for v in value if isinstance(v, dict)]
                continue
            attributes[f"shipit.payload.{key}"] = _coerce_attr(value)
        for key, value in (metadata or {}).items():
            attributes[f"shipit.metadata.{key}"] = _coerce_attr(value)

        span = self._tracer.start_span(name, attributes=attributes)
        try:
            for sub in sub_events:
                sub_name = str(sub.get("name") or sub.get("type") or "event")
                sub_attrs = {
                    f"shipit.event.{k}": _coerce_attr(v)
                    for k, v in sub.items()
                    if k not in {"name", "type"}
                }
                span.add_event(sub_name, attributes=sub_attrs)
        finally:
            span.end()

    def load(self, trace_id: str) -> TraceRecord | None:
        # Exporters ship out; they do not read back from the backend.
        return None


def _coerce_attr(value: Any) -> Any:
    """OTel attributes accept str/bool/int/float (or sequences of same).

    Anything else is coerced to its ``repr`` so we never raise from a weird
    payload type.
    """

    if isinstance(value, (str, bool, int, float)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        if all(isinstance(v, (str, bool, int, float)) for v in value):
            return list(value)
        return [str(v) for v in value]
    return repr(value)
