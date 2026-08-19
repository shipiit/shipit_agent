"""Rendering rules into the stable prefix, scoped to what is actually active.

``shipit_agent.rules`` already models the hard part: a rule can be scoped to
paths, to tools, or to neither, and ``Rule.applies`` decides. What was missing is
the step that turns a rule set into the block that ships in the prompt — and two
properties that block must have.

**Rendered once per run.** Rebuilding it per iteration moves the prompt prefix,
and implicit prompt caching keys on a byte-stable prefix. A rules block assembled
fresh on every call is a cache miss on every call.

**Deterministically ordered.** Priority first, then id, then source. Two runs
with the same rules must produce identical bytes, or the ordering itself becomes
a cache miss — and rule sets arrive from several places (agent, AGENTS.md,
per-tool) whose merge order is incidental.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

__all__ = ["render_rules", "collect_tool_rules"]


def collect_tool_rules(tools: Iterable[Any]) -> list[Any]:
    """Rules a tool ships with itself.

    A tool that carries its own policy — "never `rm -rf`" on bash — keeps that
    policy next to the thing it constrains, and it surfaces only when the tool
    is actually bound.
    """
    collected: list[Any] = []
    for tool in tools:
        rules = getattr(tool, "rules", None)
        if not rules:
            continue
        for rule in rules:
            if getattr(rule, "text", ""):
                collected.append(rule)
    return collected


def render_rules(
    rules: Sequence[Any],
    *,
    active_tools: Iterable[str] = (),
    active_paths: Sequence[str] = (),
    max_rules: int = 60,
) -> str:
    """The rules block for the prefix: filtered, ordered, deduplicated.

    Deduplication is by text, not by id: the same guidance often arrives twice —
    once from ``AGENTS.md`` and once from an agent's own list — and showing it
    twice tells the model it matters twice.
    """
    tools = frozenset(active_tools)
    paths = tuple(active_paths)

    applicable: list[Any] = []
    for rule in rules:
        applies = getattr(rule, "applies", None)
        if callable(applies):
            if not applies(tools=tools, paths=paths):
                continue
        applicable.append(rule)

    # Stable and total: priority descending, then id, then source. Anything less
    # specific leaves the order dependent on how the sets were merged.
    applicable.sort(
        key=lambda r: (
            -int(getattr(r, "priority", 0) or 0),
            str(getattr(r, "id", "")),
            str(getattr(r, "source", "")),
        )
    )

    seen: set[str] = set()
    lines: list[str] = []
    for rule in applicable:
        text = " ".join(str(getattr(rule, "text", "")).split())
        if not text or text in seen:
            continue
        seen.add(text)
        lines.append(f"- {text}")
        if len(lines) >= max_rules:
            break

    return "\n".join(lines)
