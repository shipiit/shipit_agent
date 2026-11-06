"""How the accumulator takes in the events that are not tool calls: approvals,
decisions, files made, connection requests, the run's end and notices."""

from __future__ import annotations

from typing import Any, Callable

from shipit_agent.core.models import AgentEvent

from .rows import (
    ApprovalRow,
    ArtifactRow,
    ConnectionRow,
    DecisionRow,
    NoticeRow,
    TranscriptRow,
)

_NOTICES = {
    "context_compacted": "Older turns condensed to stay in the context window",
    "run_cancelled": "Cancelled",
    "guardrail_triggered": "Guardrail triggered",
    "lockdown_engaged": "Lockdown — sensitive data was read, so only "
                        "read-only tools may run for the rest of this run",
}


class CardEventsMixin:
    """Each of these interrupts the work run with a row of its own."""

    _rows: list[TranscriptRow]
    _prose: list[str]
    _group_id: str | None
    _pending_artifacts: list[ArtifactRow]
    usage: dict[str, int]
    # Defined by the accumulator.
    _flush_work: Callable[[], None]
    _flush_prose: Callable[[], None]

    def _settle(self) -> None:
        self._flush_work()
        self._flush_prose()

    def _on_action_queued(self, event: AgentEvent) -> None:
        payload = event.payload
        # An approval interrupts the work run: it is a decision, not a step.
        # Flush prose too — a deferred call never emits `tool_called` (the
        # gate returns before it), so this is the only place the sentence
        # announcing the action gets closed before the card is drawn.
        self._settle()
        self._rows.append(
            ApprovalRow(
                action_id=int(payload.get("action_id") or 0),
                tool=str(payload.get("tool", "?")),
                title=str(payload.get("title") or payload.get("tool", "?")),
                tag=payload.get("tag"),
                auto_approved=bool(payload.get("auto_approved")),
            )
        )

    def _on_agent_decision(self, event: AgentEvent) -> None:
        self._decision_row(event, "decision")

    def _on_agent_observation(self, event: AgentEvent) -> None:
        self._decision_row(event, "observation")

    def _decision_row(self, event: AgentEvent, kind: str) -> None:
        payload = event.payload
        summary = str(payload.get("summary") or event.message or "").strip()
        if not summary:
            return
        # A decision explains the work that follows, so it closes the run
        # before it; an observation explains the work that just happened,
        # so it closes that one. Both flush, for opposite reasons.
        self._settle()
        self._rows.append(
            DecisionRow(
                text=summary,
                kind=kind,
                next_action=str(payload.get("next_action") or ""),
                iteration=payload.get("iteration"),
            )
        )

    def _on_artifact_created(self, event: AgentEvent) -> None:
        payload = event.payload
        card = ArtifactRow(
            path=str(payload.get("path") or ""),
            title=str(payload.get("title") or ""),
            kind=str(payload.get("kind") or "File"),
            tool=str(payload.get("tool") or ""),
        )
        if self._group_id is not None:
            # A group is still open: holding the card until it closes is
            # what keeps `2 tools` from becoming two rows of one with a
            # card wedged between them.
            self._pending_artifacts.append(card)
            return
        # No declared group — the work that made it settles first, and so
        # does the sentence introducing it, or the prose ends up below the
        # thing it was announcing.
        self._settle()
        self._rows.append(card)

    def _on_connection_requested(self, event: AgentEvent) -> None:
        payload = event.payload
        # Like an approval, this interrupts the work run: it is a question
        # for the user, not another step.
        self._settle()
        self._rows.append(
            ConnectionRow(
                connection_id=str(payload.get("connection_id") or ""),
                title=str(payload.get("title") or payload.get("connection_id") or ""),
                reason=str(payload.get("reason") or ""),
                auth=str(payload.get("auth") or "unknown"),
                tool=str(payload.get("tool") or ""),
            )
        )

    def _on_run_completed(self, event: AgentEvent) -> None:
        payload = event.payload
        self.usage = dict(payload.get("usage") or self.usage)
        self._flush_work()
        # An adapter that never streamed deltas hands us the whole answer
        # here; one that did has already given it to us chunk by chunk.
        if not self._prose:
            output = str(payload.get("output", "") or "")
            if output:
                self._prose.append(output)
        self._flush_prose()

    def _on_notice(self, kind: str, payload: dict[str, Any]) -> None:
        notice = _NOTICES.get(kind)
        if notice:
            self._settle()
            detail = payload.get("reason") or payload.get("message")
            self._rows.append(
                NoticeRow(kind=kind, text=f"{notice}: {detail}" if detail else notice)
            )
