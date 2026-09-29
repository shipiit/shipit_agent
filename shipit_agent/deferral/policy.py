"""Portable discovery budgets and bounded, schema-validated session reuse."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class DiscoveryPolicy:
    """Initial working-set limits, not limits on tools usable within a run.

    The discovery schema is always resident, even if it alone exceeds the
    budget. Recently discovered definitions compete for the same slots as
    other core tools. Explicit ``deferred_tools=False`` bypasses this policy.
    """

    initial_tools: int = 10
    schema_tokens: int = 4096
    reuse_tools: int = 3

    def __post_init__(self):
        if any(type(value) is not int for value in (self.initial_tools, self.schema_tokens, self.reuse_tools)):
            raise TypeError("Discovery limits must be integers")
        if self.initial_tools < 2 or self.schema_tokens < 1 or self.reuse_tools < 0:
            raise ValueError("Discovery limits require initial_tools >= 2, schema_tokens >= 1, reuse_tools >= 0")


def schema_tokens(schema: dict, model: str | None = None) -> int:
    """Approximate portable estimate; never represents provider billing."""
    encoded = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
    if model:
        from shipit_agent.token_counting import count_tokens
        return max(1, count_tokens(encoded, model))
    return max(1, (len(encoded) + 3) // 4)


def schema_fingerprint(schema: dict) -> str:
    return hashlib.sha256(json.dumps(schema, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def select_resident(tools, schemas, policy, *, core, search_name, recent=(), model=None):
    """Stable priority selection with both count and token constraints."""
    recent_rank = {name: len(recent) - index for index, name in enumerate(recent)}

    def priority(tool):
        value = getattr(tool, "discovery_priority", 0)
        value = float(value) if isinstance(value, (int, float)) else 0.0
        if not math.isfinite(value):
            value = 0.0
        return value, recent_rank.get(tool.name, 0), tool.name in core

    resident = {search_name}
    remaining = policy.schema_tokens - schema_tokens(schemas[search_name], model)
    for tool in sorted(tools, key=priority, reverse=True):
        if tool.name in resident:
            continue
        cost = schema_tokens(schemas[tool.name], model)
        if len(resident) < policy.initial_tools and cost <= remaining:
            resident.add(tool.name)
            remaining -= cost
    return resident
