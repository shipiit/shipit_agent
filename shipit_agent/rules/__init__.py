"""Agent rules — durable behavioural guidance, at the agent and the tool level.

Rules are the policy layer that complements skills (capability): AGENTS.md-style
house rules that ride in the system prompt, optionally scoped to paths or tools,
ordered by priority.

    from shipit_agent.rules import RuleSet, Rule, load_project_rules

    rules = RuleSet()
    rules.add("Always write a test before the implementation.")
    rules.add({"text": "Never edit files under infra/prod/**.",
               "paths": ["infra/prod/**"], "priority": 10})
    rules.extend(load_project_rules("."))            # AGENTS.md + .shipit/rules/
    print(rules.render(tools=frozenset({"bash"})))   # the prompt block

A tool can also ship its own rules (a ``rules`` attribute); ``collect_tool_rules``
gathers them, scoped so they surface only when the tool is active.
"""

from .loader import load_project_rules
from .registry import RuleSet, collect_tool_rules
from .rule import Rule, coerce_rule

__all__ = [
    "Rule",
    "RuleSet",
    "coerce_rule",
    "collect_tool_rules",
    "load_project_rules",
]
