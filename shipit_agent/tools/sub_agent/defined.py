"""Running a user-defined sub-agent: its model, its tools, how it is described.

Kept apart from :mod:`.sub_agent_tool` so the tool's own flow (background
tasks, collection, timeouts) stays readable.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any

from shipit_agent.agents.subagent_definitions import SubagentDefinition


def describe_agents(agents: Mapping[str, SubagentDefinition]) -> str:
    """The ``agent_type`` description listing each defined sub-agent."""
    if not agents:
        return "A specialist role, e.g. 'researcher', 'code-reviewer'. Omit for general-purpose."
    lines = [
        f"- {name}: {definition.description}"
        for name, definition in sorted(agents.items())
    ]
    return (
        "Which sub-agent to use. Defined here:\n"
        + "\n".join(lines)
        + "\nOmit for general-purpose."
    )


def llm_for(llm: Any, definition: SubagentDefinition) -> Any:
    """*llm*, or a copy of it set to the definition's model; the parent's is untouched."""
    if not definition.model or getattr(llm, "model", None) in (None, definition.model):
        return llm
    child = copy.copy(llm)
    child.model = definition.model
    if hasattr(child, "facts"):
        # The Anthropic adapter derives its request shape from the model.
        from shipit_agent.llms.claude_models import claude_model

        child.facts = claude_model(definition.model)
    return child


def tools_for(definition: SubagentDefinition, inherited: Sequence[Any]) -> list[Any]:
    """The parent's tools the definition allows; never one the parent lacks."""
    if definition.tools is None:
        return list(inherited)
    allowed = set(definition.tools)
    return [tool for tool in inherited if getattr(tool, "name", "") in allowed]
