"""Looking a model up in the table, adding rules, and cleaning request parameters for it."""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any, Iterable

from .model import ModelCapabilities
from .rules import DEFAULT_CAPABILITIES, RULES


def capabilities_for(model: str | None) -> ModelCapabilities:
    """Capabilities for *model*, or permissive defaults when unmatched."""
    if not model:
        return DEFAULT_CAPABILITIES
    for pattern, caps in RULES:
        if pattern.search(model):
            return caps
    return DEFAULT_CAPABILITIES


def sanitize_params(
    model: str | None, params: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Strip parameters *model* is known to reject.

    Returns ``(accepted, dropped)``. Callers that want to surface the drop to a
    user have the dropped mapping; callers that don't can ignore it.
    """
    if not params:
        return {}, {}
    return capabilities_for(model).sanitize(params, model=model or "")


def apply_recommended_params(
    model: str | None, params: dict[str, Any]
) -> dict[str, Any]:
    """Fill this family's recommended values for keys the caller left unset."""
    return capabilities_for(model).with_recommendations(params or {})


def register_rule(
    pattern: str | re.Pattern[str],
    capabilities: ModelCapabilities,
    *,
    first: bool = True,
) -> None:
    """Add a rule at runtime, for a model this package doesn't know yet.

    Defaults to the front of the list so a caller's specific rule wins over a
    shipped general one — the common case being a private or preview model
    whose id matches an existing family pattern but behaves differently.
    """
    compiled = re.compile(pattern, re.I) if isinstance(pattern, str) else pattern
    if first:
        RULES.insert(0, (compiled, capabilities))
    else:
        RULES.append((compiled, capabilities))


def supports(model: str | None, capability: str) -> bool:
    """Does *model* support *capability*? Unknown capability names are False."""
    return bool(getattr(capabilities_for(model), capability, False))


def describe(models: Iterable[str]) -> list[dict[str, Any]]:
    """A capability matrix for *models* — for ``doctor``, docs, or a UI."""
    rows: list[dict[str, Any]] = []
    for model in models:
        caps = capabilities_for(model)
        rows.append(
            {
                "model": model,
                "tools": caps.supports_tools,
                "vision": caps.supports_vision,
                "prompt_cache": caps.prompt_cache_mode,
                "reasoning": caps.supports_reasoning,
                "reasoning_history": caps.reasoning_history,
                "schema_dialect": caps.schema_dialect,
                "context_window": caps.context_window,
                "service_tier": caps.supports_service_tier,
                "blocked": sorted(caps.blocked_params),
                "renamed": dict(caps.renamed_params),
                "recommended": dict(caps.recommended_params),
            }
        )
    return rows


def with_reason(caps: ModelCapabilities, reason: str) -> ModelCapabilities:
    """Copy *caps* with a different explanation — for registering variants."""
    return replace(caps, reason=reason)
