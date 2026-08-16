"""A rule — one piece of durable behavioural guidance the agent must follow.

Skills add *capability* ("here's how to make a slide deck"); rules add *policy*
("never touch production config", "always write a test first"). They're the
AGENTS.md / house-style layer: persistent constraints that ride in the system
prompt regardless of which task is running, unlike a skill that switches in only
when its intent matches.

A rule can be **scoped** so it only applies where it's relevant:
- ``paths`` — glob patterns; the rule applies when the agent is working on a
  matching file/dir (e.g. ``tests/**`` → "every test uses pytest, no unittest").
- ``tools`` — tool names; the rule applies only when that tool is in play
  (e.g. a ``bash`` rule that forbids ``rm -rf``). This is the "rule in a tool"
  case: a tool ships its own rules and they surface only when it's available.

Unscoped rules are global. ``priority`` orders them (higher first) so the most
important guidance leads.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Rule:
    """One behavioural rule, optionally scoped to paths and/or tools."""

    text: str
    id: str = ""
    #: Glob patterns; empty means "any path". A rule with paths applies when at
    #: least one active working path matches.
    paths: tuple[str, ...] = ()
    #: Tool names; empty means "any tool". A rule with tools applies when at
    #: least one of those tools is active in the run.
    tools: tuple[str, ...] = ()
    #: Higher sorts first. Ties keep insertion order (stable sort).
    priority: int = 0
    #: Where it came from — a file path, a tool name, "agent", "AGENTS.md" —
    #: shown to no one but invaluable when debugging why a rule is present.
    source: str = ""

    def applies(self, *, tools: frozenset[str] = frozenset(), paths: tuple[str, ...] = ()) -> bool:
        """Does this rule apply in a context of active ``tools`` and ``paths``?

        A scope dimension that the rule leaves empty is a wildcard. A scope
        dimension the rule sets must be satisfied by the context — but only
        when the context supplies that dimension. An unknown context (no paths
        provided) does not suppress a path-scoped rule: better to show a rule
        that might not apply than to hide one that does. Tool scope is the
        opposite — tools are always known, so a tool-scoped rule is hidden when
        none of its tools are active.
        """
        if self.tools and not (set(self.tools) & set(tools)):
            return False
        if self.paths and paths:
            if not any(
                fnmatch.fnmatch(path, pattern)
                for pattern in self.paths
                for path in paths
            ):
                return False
        return True


def coerce_rule(value: "Rule | str | dict", *, source: str = "") -> Rule:
    """Accept a Rule, a bare string, or a dict — return a Rule.

    Lets a caller write ``rules=["always write a test first"]`` or the richer
    ``rules=[{"text": ..., "paths": ["tests/**"], "priority": 10}]`` without
    importing the dataclass.
    """
    if isinstance(value, Rule):
        return value if value.source or not source else _with_source(value, source)
    if isinstance(value, str):
        return Rule(text=value.strip(), source=source)
    if isinstance(value, dict):
        return Rule(
            text=str(value.get("text", "")).strip(),
            id=str(value.get("id", "")),
            paths=tuple(value.get("paths", ()) or ()),
            tools=tuple(value.get("tools", ()) or ()),
            priority=int(value.get("priority", 0) or 0),
            source=str(value.get("source", "") or source),
        )
    raise TypeError(f"cannot coerce {type(value).__name__} to a Rule")


def _with_source(rule: Rule, source: str) -> Rule:
    return Rule(
        text=rule.text, id=rule.id, paths=rule.paths, tools=rule.tools,
        priority=rule.priority, source=source,
    )
