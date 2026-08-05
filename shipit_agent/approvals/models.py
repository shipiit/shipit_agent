"""What a queued action is, and how it describes itself to a human.

Modelled on Cloudflare OS's ``ActionLogEntry`` / ``ActionDescription``: an
action carries everything needed to (a) decide whether it needs review, (b)
show it to the reviewer, and (c) keep it in an audit log afterwards.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from shipit_agent.tools.contracts import ToolContract

__all__ = ["ActionState", "PendingAction", "ApplyFn"]

# Applying a queued action means actually running the tool that was deferred.
ApplyFn = Callable[[], Any]


class ActionState(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    FAILED = "failed"


@dataclass(slots=True)
class PendingAction:
    """One side-effecting call, held for a human decision.

    ``id`` counts up within a queue and is the ordering the drain walks, so an
    action is never applied ahead of an earlier one awaiting a manual gate.
    """

    id: int
    tool: str
    arguments: dict[str, Any]
    contract: ToolContract
    title: str
    description: str
    apply_fn: ApplyFn | None = field(default=None, repr=False)

    state: ActionState = ActionState.PENDING
    created_at: float = field(default_factory=time.time)
    applied_at: float | None = None
    resolved_by: str | None = None
    auto_approved: bool = False
    result: Any = None
    error: str | None = None

    # ── classification ───────────────────────────────────────────────────

    @property
    def tag(self) -> str | None:
        """The auto-approval key, or ``None`` for a permanently manual action."""
        return self.contract.tag

    @property
    def kind_label(self) -> str | None:
        return self.contract.action_kind.label if self.contract.action_kind else None

    @property
    def is_pending(self) -> bool:
        return self.state is ActionState.PENDING

    @property
    def blocks_agent(self) -> bool:
        """Must the turn suspend rather than continue with this queued?"""
        return self.contract.await_decision

    @property
    def can_revert(self) -> bool:
        return self.contract.implements_revert

    def eligible_for_auto(self, enabled_tags: set[str]) -> bool:
        """Both signals, per Cloudflare's rule — neither alone is enough.

        The contract's standing verdict that this *kind* of call is safe, AND
        a rule the user enabled for that tag. A destructive action is never
        eligible regardless.
        """
        if not self.is_pending or self.contract.destructive:
            return False
        if not self.contract.auto_approvable or self.tag is None:
            return False
        return self.tag in enabled_tags

    # ── the message the model sees while this sits queued ────────────────

    def deferral_notice(self) -> str:
        """What the agent is told when the call is queued instead of run.

        Deliberately **not** a fabricated result. Cloudflare can simulate a
        pending action because each Gatekeeper owns the remote resource and
        can model its state; shipit's tools are unrelated functions and a
        simulated ``bash`` output would be a lie the model then reasons over.
        So we tell it the truth and tell it what to do about it.
        """
        return (
            f"[{self.tool} is queued for approval — it has NOT run yet. "
            f"Assume it will succeed and continue with the rest of the task. "
            f"Do not retry it and do not read back its effects; anything that "
            f"depends on those effects is still stale.]"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tool": self.tool,
            "arguments": dict(self.arguments),
            "title": self.title,
            "description": self.description,
            "state": self.state.value,
            "tag": self.tag,
            "kind_label": self.kind_label,
            "created_at": self.created_at,
            "applied_at": self.applied_at,
            "resolved_by": self.resolved_by,
            "auto_approved": self.auto_approved,
            "can_revert": self.can_revert,
            "error": self.error,
        }
