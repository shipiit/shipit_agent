"""``can_use_tool`` the Claude Agent SDK way.

    async def can_use_tool(tool_name, input_data, context):
        if tool_name == "bash" and "deploy" in input_data.get("command", ""):
            return PermissionResultDeny(message="No deploys from the agent.")
        return PermissionResultAllow(updated_input=input_data)

The callback runs only for calls no rule, mode or hook has settled and
that need approval, as in the SDK: read-only calls (reads, searches) are
approved without it, and a clarifying question reaches it once, as
``"AskUserQuestion"``. An ``addRules`` allow in ``updated_permissions`` approves this call
for the rest of the session; other update types are accepted and ignored.
``interrupt=True`` refuses the call; it does not end the session.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from shipit_agent.safety.permissions import PermissionDecision, PermissionResult

from .tools import run_maybe_async

__all__ = [
    "PermissionResultAllow",
    "PermissionResultDeny",
    "ToolPermissionContext",
    "permission_callback",
]

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PermissionResultAllow:
    behavior: Literal["allow"] = "allow"
    updated_input: dict[str, Any] | None = None
    updated_permissions: list[dict[str, Any]] | None = None


@dataclass(slots=True)
class PermissionResultDeny:
    behavior: Literal["deny"] = "deny"
    message: str = ""
    interrupt: bool = False


@dataclass(slots=True)
class ToolPermissionContext:
    """What the callback is told about the call besides its name and input."""

    signal: Any = None
    suggestions: list[dict[str, Any]] = field(default_factory=list)
    tool_use_id: str | None = None
    agent_id: str | None = None
    decision_reason: str | None = None


def permission_callback(
    can_use_tool: Callable[..., Any],
) -> Callable[[str, dict[str, Any]], PermissionResult | None]:
    """Wrap an SDK-style ``can_use_tool`` as a shipit ``permission_callback``."""

    from shipit_agent.safety.permissions import PermissionEngine

    classifier = PermissionEngine()

    def callback(name: str, arguments: dict[str, Any]) -> PermissionResult | None:
        # As in the SDK, calls that need no approval never reach can_use_tool:
        # reads, searches, and questions (AskUserQuestion asks it itself).
        if classifier.is_read_only(name):
            return PermissionResult(PermissionDecision.ALLOW, reason="read-only")
        try:
            answer = run_maybe_async(can_use_tool, name, dict(arguments), ToolPermissionContext())
        except Exception as error:
            # Fail closed: a broken approval check must not become "allow".
            logger.warning("can_use_tool failed for %s; denying the call", name, exc_info=True)
            return PermissionResult(
                PermissionDecision.DENY, reason=f"can_use_tool failed: {type(error).__name__}: {error}"
            )
        if isinstance(answer, PermissionResultDeny) or _behavior(answer) == "deny":
            message = getattr(answer, "message", None) or _get(answer, "message") or "denied by can_use_tool"
            return PermissionResult(PermissionDecision.DENY, reason=str(message))
        if isinstance(answer, PermissionResultAllow) or _behavior(answer) == "allow":
            updates = getattr(answer, "updated_permissions", None) or _get(answer, "updated_permissions") or []
            updated = getattr(answer, "updated_input", None) or _get(answer, "updated_input")
            return PermissionResult(
                PermissionDecision.ALLOW,
                reason="allowed by can_use_tool",
                updated_arguments=dict(updated) if isinstance(updated, dict) else None,
                scope="session" if _grants_for_session(updates) else "once",
            )
        return None

    return callback


def _behavior(answer: Any) -> str | None:
    return _get(answer, "behavior")


def _get(answer: Any, key: str) -> Any:
    return answer.get(key) if isinstance(answer, dict) else None


def _grants_for_session(updates: list[Any]) -> bool:
    return any(
        isinstance(update, dict) and update.get("type") == "addRules" and update.get("behavior", "allow") == "allow"
        for update in updates
    )
