"""Permission modes, decisions and the result of a check."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal

PermissionMode = Literal[
    "default", "acceptEdits", "plan", "bypass", "bypassPermissions", "dontAsk"
]


class PermissionDecision(str, Enum):
    """What a permission rule decides about a tool call: allow, deny or ask."""

    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


@dataclass(slots=True)
class PermissionResult:
    """The outcome of a permission check.

    ``updated_arguments`` lets a rule/hook **rewrite** the call before it runs
    (an argument rewrite). ``None`` means "use the original args".
    """

    decision: PermissionDecision
    reason: str = ""
    updated_arguments: dict[str, Any] | None = None
    #: For an ALLOW from the callback: ``"session"`` approves this exact call
    #: (tool and arguments) for the rest of the session, like Claude Code's
    #: "don't ask again"; ``"once"`` approves just this call.
    scope: Literal["once", "session"] = "once"

    @property
    def allowed(self) -> bool:
        return self.decision == PermissionDecision.ALLOW

    @property
    def denied(self) -> bool:
        return self.decision == PermissionDecision.DENY

    @property
    def needs_approval(self) -> bool:
        return self.decision == PermissionDecision.ASK
