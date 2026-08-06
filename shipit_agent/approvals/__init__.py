"""Deferred approvals — decide later, in bulk, without stalling the agent.

See :mod:`shipit_agent.approvals.queue` for the rationale and usage, and
``docs/design/modern-agent-upgrade.md`` for how this maps onto Cloudflare OS's
Gatekeeper approval model (and where it deliberately diverges).
"""

from .models import ActionState, ApplyFn, PendingAction
from .revert import (
    FileSnapshotReverter,
    Reverter,
    can_revert,
    register_reverter,
    reverter_for,
)
from .queue import (
    ApprovalQueue,
    AutoApprovalDrainer,
    AutoApproveRule,
    coerce_queue,
    iter_pending,
)

__all__ = [
    "ActionState",
    "ApplyFn",
    "ApprovalQueue",
    "AutoApprovalDrainer",
    "AutoApproveRule",
    "FileSnapshotReverter",
    "PendingAction",
    "Reverter",
    "can_revert",
    "register_reverter",
    "reverter_for",
    "coerce_queue",
    "iter_pending",
]
