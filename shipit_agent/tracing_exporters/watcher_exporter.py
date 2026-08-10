"""Ship agent runs to shipit-watcher.

``LangfuseExporter`` sends traces and stops there. This sends the same runs
through watcher, which adds the things a trace alone does not give you:

- **a local ledger** — generations persisted to your own database, so
  retention outlives a hosted plan and cost-per-tenant is a SQL query
  rather than an export from someone else's UI
- **masking** — PII redacted before anything leaves the process
- **attribution** — every trace carries a tenant, a user and a cost centre,
  so a multi-tenant run is billable rather than anonymous
- **scores, datasets and prompts** — watcher's own surfaces, reachable from
  the same credentials
- **the agent graph** — with ``WATCHER_LANGFUSE_TRANSPORT=otlp``, tools and
  sub-agents carry semantic observation types, which is what makes Langfuse
  draw a graph instead of a flat list of spans

It is a :class:`~shipit_agent.tracing.TraceStore`, so it attaches the same
way anything else does and composes with the rest::

    from shipit_agent import Agent
    from shipit_agent.tracing_exporters import WatcherExporter

    agent = Agent(llm=llm, tools=tools, trace_store=WatcherExporter())

Watcher's API is built around context managers — a trace is open while work
happens inside it — but an agent reports events *after* they finish. The
open scopes are therefore held in an :class:`~contextlib.ExitStack` per
trace and closed when the matching end event arrives. Only watcher's public
API is used, so this keeps working across its releases.
"""

from __future__ import annotations

import logging
from contextlib import ExitStack
from typing import Any

from shipit_agent.models import AgentEvent
from shipit_agent.tracing import TraceRecord

logger = logging.getLogger(__name__)

__all__ = ["WatcherExporter"]


class _Scope:
    """One run's open watcher scopes, closed in reverse order."""

    def __init__(self) -> None:
        self.stack = ExitStack()
        self.tools: dict[str, ExitStack] = {}
        self.events: list[AgentEvent] = []


class WatcherExporter:
    """A :class:`TraceStore` that reports through shipit-watcher."""

    def __init__(self, *, tracer: Any = None, keep_events: bool = True) -> None:
        """
        ``tracer`` overrides watcher's process tracer, for tests.

        ``keep_events`` retains events in memory so :meth:`load` can answer.
        Turn it off for long-running services, where holding every event of
        every run is a leak wearing the name of a feature.
        """
        self._tracer = tracer
        self._scopes: dict[str, _Scope] = {}
        self._keep_events = keep_events

    # ── watcher plumbing ────────────────────────────────────────────────

    def _watcher(self) -> Any:
        if self._tracer is not None:
            return self._tracer
        from shipit_watcher import get_tracer

        return get_tracer()

    # ── TraceStore ──────────────────────────────────────────────────────

    def append_event(
        self,
        trace_id: str,
        event: AgentEvent,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Translate one agent event.

        Never raises. Observability that can break a run is worse than no
        observability: the run is the thing the user asked for, and a
        failed export is a monitoring gap, not a failed request.
        """
        scope = self._scopes.get(trace_id)
        if scope is None:
            scope = self._scopes[trace_id] = _Scope()
        if self._keep_events:
            scope.events.append(event)

        try:
            self._translate(trace_id, scope, event, metadata or {})
        except Exception:
            logger.warning(
                "shipit-watcher: could not export %s", event.type, exc_info=True
            )

    def _translate(
        self,
        trace_id: str,
        scope: _Scope,
        event: AgentEvent,
        metadata: dict[str, Any],
    ) -> None:
        watcher = self._watcher()
        payload = dict(event.payload or {})

        if event.type == "run_started":
            scope.stack.enter_context(
                watcher.trace(
                    metadata.get("name") or "agent.run",
                    input=payload.get("prompt"),
                    **{k: v for k, v in metadata.items() if k != "name"},
                )
            )

        elif event.type == "tool_called":
            name = str(payload.get("tool") or payload.get("name") or "tool")
            call_id = str(payload.get("call_id") or name)
            stack = ExitStack()
            stack.enter_context(
                watcher.tool(name, arguments=payload.get("arguments"))
            )
            scope.tools[call_id] = stack

        elif event.type in ("tool_completed", "tool_failed", "tool_denied"):
            name = str(payload.get("tool") or payload.get("name") or "tool")
            call_id = str(payload.get("call_id") or name)
            stack = scope.tools.pop(call_id, None)
            if stack is not None:
                stack.close()

        elif event.type == "agent_decision":
            # The narration the runtime already produced, as a decision
            # node — so the graph shows why, not only what.
            watcher.decision(
                "agent.decision",
                chosen=str(payload.get("next_action") or "continue"),
                options=[],
                rationale=str(payload.get("summary") or ""),
            )

        elif event.type == "run_completed":
            self._close(trace_id, scope, payload)

    def _close(self, trace_id: str, scope: _Scope, payload: dict) -> None:
        """Close every scope this run opened, innermost first.

        A tool whose completion never arrived — a crash, a cancellation —
        would otherwise hold its scope open forever and leak the run.
        """
        for stack in list(scope.tools.values()):
            try:
                stack.close()
            except Exception:
                logger.warning("shipit-watcher: tool scope", exc_info=True)
        scope.tools.clear()
        try:
            scope.stack.close()
        except Exception:
            logger.warning("shipit-watcher: trace scope", exc_info=True)
        if not self._keep_events:
            self._scopes.pop(trace_id, None)

    def load(self, trace_id: str) -> TraceRecord | None:
        scope = self._scopes.get(trace_id)
        if scope is None:
            return None
        return TraceRecord(trace_id=trace_id, events=list(scope.events))

    # ── watcher surfaces, reachable from the agent side ─────────────────

    def score(self, name: str, value: Any, *, comment: str = "") -> None:
        """Attach a score to the run in flight.

        Here rather than left to the caller because scoring needs the trace
        id, and the exporter is the one object that has it.
        """
        try:
            from shipit_watcher import Score, record_score

            record_score(Score(name=name, value=value, comment=comment))
        except Exception:
            logger.warning("shipit-watcher: could not record score", exc_info=True)

    def flush(self) -> None:
        """Send anything buffered. Call before a short-lived process exits."""
        try:
            self._watcher().flush()
        except Exception:
            logger.warning("shipit-watcher: flush failed", exc_info=True)
