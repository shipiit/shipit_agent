"""Auto-approval: rules a person turned on, and the drainer that applies them."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING


from .models import PendingAction

if TYPE_CHECKING:
    from .queue import ApprovalQueue


class AutoApproveRule:
    """A user's standing "always approve this kind" decision.

    ``enabled_by`` matters: an auto-approval runs under the authority of the
    person who enabled the rule, and the audit log says so.
    """

    __slots__ = ("tag", "label", "enabled_by", "enabled_at")

    def __init__(self, tag: str, label: str, enabled_by: str) -> None:
        self.tag = tag
        self.label = label
        self.enabled_by = enabled_by
        self.enabled_at = time.time()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"AutoApproveRule({self.tag!r}, by={self.enabled_by!r})"


class AutoApprovalDrainer:
    """Applies eligible pending actions, in order, never skipping a gate.

    A direct port of Cloudflare OS's ``AutoApprovalDrainer``, including the
    three properties that make it safe:

    1. **In id order, stopping at the first ineligible action.** A pending
       action awaiting a manual decision is never jumped over — otherwise
       "approve later" could silently reorder your effects.
    2. **Both signals required** — the contract's ``auto_approvable`` verdict
       *and* an enabled rule for its tag.
    3. **Single-flight with a rerun flag**, so two concurrent drains can't
       double-apply, and work submitted mid-drain isn't lost.
    """

    def __init__(self, queue: "ApprovalQueue") -> None:
        self._queue = queue
        self._draining = False
        self._rerun = False
        self._lock = threading.Lock()

    def drain(self, *, by: str) -> list[PendingAction]:
        """Apply everything currently eligible; return what was applied."""
        with self._lock:
            if self._draining:
                # A drain is already running — ask it to loop again rather
                # than starting a second one over the same actions.
                self._rerun = True
                return []
            self._draining = True
            self._rerun = False

        applied: list[PendingAction] = []
        try:
            while True:
                applied.extend(self._drain_once(by=by))
                with self._lock:
                    if not self._rerun:
                        break
                    self._rerun = False
        finally:
            with self._lock:
                self._draining = False
        return applied

    def _drain_once(self, *, by: str) -> list[PendingAction]:
        applied: list[PendingAction] = []
        enabled = self._queue.auto_tags()
        # Snapshot: applying mutates the queue as we walk it.
        for action in list(self._queue.pending()):
            if not action.eligible_for_auto(enabled):
                # A manual gate. Stop rather than reaching past it.
                break
            # Re-check immediately before applying, in case a concurrent
            # decision already took this one.
            fresh = self._queue.get(action.id)
            if fresh is None or not fresh.is_pending:
                continue
            rule = self._queue.rule_for(fresh.tag)
            try:
                # Attribute to whoever enabled the rule — it runs under their
                # authority, not the agent's.
                self._queue.approve(
                    fresh.id,
                    by=rule.enabled_by if rule else by,
                    auto=True,
                )
            except Exception:
                # Leave it pending for manual handling and stop the drain;
                # never skip ahead of a failure.
                break
            applied.append(fresh)
        return applied
