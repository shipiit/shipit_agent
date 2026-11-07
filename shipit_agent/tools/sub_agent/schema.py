"""The ``sub_agent`` tool's JSON schema, as the model sees it."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from shipit_agent.agents.subagent_definitions import SubagentDefinition

from .defined import describe_agents


def sub_agent_schema(
    name: str, description: str, agents: Mapping[str, SubagentDefinition]
) -> dict[str, Any]:
    """The tool schema, with ``agent_type`` listing the defined sub-agents."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": (
                            "The task, stated so someone with no other "
                            "context could do it. Say what to return."
                        ),
                    },
                    # NOT named "context": ToolRunner strips `context`
                    # and `self` from tool arguments because they collide
                    # with the positional ToolContext. The original tool
                    # used that name, so the model's supporting context
                    # was silently dropped before the tool ever saw it.
                    "details": {
                        "type": "string",
                        "description": (
                            "Facts the sub-agent needs — paths, ids, "
                            "constraints. It cannot see your conversation."
                        ),
                    },
                    "agent_type": {
                        "type": "string",
                        "description": describe_agents(agents),
                    },
                    "background": {
                        "type": "boolean",
                        "description": (
                            "Start it and return a task id immediately so "
                            "you can keep working."
                        ),
                        "default": False,
                    },
                    "collect": {
                        "type": "string",
                        "description": (
                            "A task id from a background call — waits for "
                            "and returns that task's result. Pass 'all' to "
                            "collect every outstanding task. When "
                            "collecting, `task` is ignored, so repeat the "
                            "original task text there."
                        ),
                    },
                },
                # `task` is required even though a collect call does not
                # use it. An all-optional schema tells a weaker model that
                # nothing is needed, and it sends `{}` — observed live with
                # Gemma 4, which called the tool with no arguments at all.
                "required": ["task"],
            },
        },
    }
