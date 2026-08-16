"""RuleSet — collect rules from every source and render the ones that apply.

Rules arrive from three places, all merged here:
1. **Agent-level** — passed to ``Agent(rules=[...])`` or discovered from an
   ``AGENTS.md`` in the project (the cross-agent house-style convention).
2. **Tool-level** — a tool exposes a ``rules`` attribute; those rules surface
   only when that tool is active. This is the "rule lives in the tool" case.
3. **Files** — ``.shipit/rules/*.md`` with optional frontmatter for scope.

For a given run the set filters to the applicable rules (by active tools and
working paths), orders them by priority, and renders one block the runtime folds
into the system prompt — placed with the tools, where behavioural instructions
are followed most reliably.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .rule import Rule, coerce_rule


@dataclass(slots=True)
class RuleSet:
    """An ordered collection of rules with context-aware rendering."""

    rules: list[Rule] = field(default_factory=list)

    def add(self, value: "Rule | str | dict", *, source: str = "") -> "RuleSet":
        rule = coerce_rule(value, source=source)
        if rule.text:  # a blank rule is nothing to say — drop it
            self.rules.append(rule)
        return self

    def extend(self, values: "list[Rule | str | dict]", *, source: str = "") -> "RuleSet":
        for value in values:
            self.add(value, source=source)
        return self

    def for_context(
        self, *, tools: frozenset[str] = frozenset(), paths: tuple[str, ...] = ()
    ) -> list[Rule]:
        """The applicable rules, highest priority first (stable within a tier)."""
        applicable = [r for r in self.rules if r.applies(tools=tools, paths=paths)]
        # Stable sort by descending priority — Python's sort is stable, so rules
        # of equal priority keep the order they were added (source order).
        return sorted(applicable, key=lambda r: -r.priority)

    def render(
        self, *, tools: frozenset[str] = frozenset(), paths: tuple[str, ...] = ()
    ) -> str:
        """Render the applicable rules as a prompt block, or ``""`` if none.

        Deliberately terse and imperative — a numbered list under a heading that
        states these are non-negotiable. Scope is not printed (the model doesn't
        need the bookkeeping); only the rules that already passed the filter are
        shown, so every line is one it must follow right now.
        """
        applicable = self.for_context(tools=tools, paths=paths)
        if not applicable:
            return ""
        lines = [
            "# Rules",
            "",
            "Non-negotiable instructions for this project. Follow every one; if a "
            "task appears to require breaking a rule, stop and say so instead.",
            "",
        ]
        for index, rule in enumerate(applicable, start=1):
            lines.append(f"{index}. {rule.text}")
        return "\n".join(lines)

    def __bool__(self) -> bool:
        return bool(self.rules)

    def __len__(self) -> int:
        return len(self.rules)


def collect_tool_rules(tools: list) -> list[Rule]:
    """Pull rules a tool ships in its own ``rules`` attribute.

    A tool declares ``rules = ["never run rm -rf", ...]`` (strings or dicts);
    each becomes a Rule scoped to that tool, sourced to its name. They then
    surface only when the tool is active — guidance that travels with the
    capability instead of living far away in a global prompt.
    """
    collected: list[Rule] = []
    for tool in tools:
        raw = getattr(tool, "rules", None)
        if not raw:
            continue
        name = str(getattr(tool, "name", "") or "")
        for value in raw:
            rule = coerce_rule(value, source=f"tool:{name}")
            if not rule.text:
                continue
            # Force the rule to be scoped to this tool if the tool didn't say so,
            # so a tool's own rule never leaks into runs without that tool.
            if not rule.tools and name:
                rule = Rule(
                    text=rule.text, id=rule.id, paths=rule.paths,
                    tools=(name,), priority=rule.priority, source=rule.source,
                )
            collected.append(rule)
    return collected
