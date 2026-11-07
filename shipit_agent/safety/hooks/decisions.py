"""Reading a hook's return value as a permission decision."""

from __future__ import annotations

from typing import Any

from shipit_agent.safety.permissions import PermissionDecision, PermissionResult


def _coerce_hook_decision(value: Any) -> PermissionResult | None:
    """Normalize whatever a before-tool hook returned into a PermissionResult.

    Accepts ``None`` (no opinion / observe-only), a ``PermissionResult``, a
    ``bool`` (``False`` → deny), or a dict like
    ``{"decision": "deny", "reason": "...", "updated_arguments": {...}}``.
    """
    if value is None:
        return None
    if isinstance(value, PermissionResult):
        return value
    if isinstance(value, bool):
        return (
            None
            if value
            else PermissionResult(PermissionDecision.DENY, reason="hook returned False")
        )
    if isinstance(value, dict) and "decision" in value:
        return PermissionResult(
            PermissionDecision(str(value["decision"]).lower()),
            reason=str(value.get("reason", "")),
            updated_arguments=value.get("updated_arguments"),
        )
    return None
