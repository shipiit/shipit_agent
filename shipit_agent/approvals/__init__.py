"""Deferred approvals — decide later, in bulk, without stalling the agent.

See :mod:`shipit_agent.approvals.queue` for the rationale and usage, and
``docs/design/modern-agent-upgrade.md`` for how this maps onto Cloudflare OS's
Gatekeeper approval model (and where it deliberately diverges).
"""

from .models import ActionState, ApplyFn, PendingAction
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
    "PendingAction",
    "coerce_queue",
    "iter_pending",
]
