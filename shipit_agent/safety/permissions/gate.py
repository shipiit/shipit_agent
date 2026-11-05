"""Folding hooks and the engine into one decision, and building an engine from what a caller passes."""

from __future__ import annotations

from typing import Any, Sequence

from .engine import PermissionEngine
from .values import PermissionDecision, PermissionMode, PermissionResult


def authorize_tool(
    hooks: Any,
    permissions: "PermissionEngine | None",
    name: str,
    arguments: dict[str, Any],
    tool: Any = None,
    *,
    risk: Sequence[str] = (),
) -> PermissionResult | None:
    """Fold blocking hooks + the permission engine into one decision.

    A call with *risk* is always judged by an engine (a default one when
    none is configured), so it cannot slip through the permissive default.

    Precedence: DENY wins, then ASK, otherwise ALLOW (carrying the last
    argument rewrite). Returns ``None`` when neither has an opinion — the
    historical fully-permissive default. Shared by the sync and async runtimes.
    ``hooks`` is duck-typed (``run_before_tool(name, args)``) to avoid a circular
    import.
    """
    results: list[PermissionResult] = []
    if hooks is not None:
        hook_decision = hooks.run_before_tool(name, arguments)
        if hook_decision is not None:
            results.append(hook_decision)
    if permissions is None and risk:
        permissions = PermissionEngine()
    if permissions is not None:
        results.append(permissions.check(name, arguments, tool, risk=risk))
    if not results:
        return None
    for result in results:
        if result.denied:
            return result
    for result in results:
        if result.needs_approval:
            return result
    updated: dict[str, Any] | None = None
    for result in results:
        if result.updated_arguments is not None:
            updated = result.updated_arguments
    return PermissionResult(PermissionDecision.ALLOW, updated_arguments=updated)


def coerce_permissions(
    spec: PermissionEngine | PermissionMode | dict[str, Any] | None,
) -> PermissionEngine | None:
    """Normalize a user-supplied permissions spec into a ``PermissionEngine``.

    Accepts an engine, a bare mode string, a dict of kwargs, or ``None``.
    """
    if spec is None:
        return None
    if isinstance(spec, PermissionEngine):
        return spec
    if isinstance(spec, str):
        return PermissionEngine(mode=spec)  # type: ignore[arg-type]
    if isinstance(spec, dict):
        return PermissionEngine(**spec)
    raise TypeError(f"Unsupported permissions spec: {type(spec)!r}")
