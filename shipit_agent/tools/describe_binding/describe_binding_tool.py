"""``describe_binding`` — learn one resource's API, on demand.

The counterweight to code mode. Collapsing 50 tool schemas into a handful of
`env` bindings only helps if the agent can still find out how to *use* one, so
this returns the full surface of a single binding — its methods, their
parameters, its gating, and its catalog — and nothing about any other.

Cloudflare OS is explicit about why it is scoped to one: return the types for
this resource "rather than the entire API space of the vendor, which may
support many kinds of resources." The prompt stays small because discovery is
pull, not push.
"""

from __future__ import annotations

from typing import Any

from shipit_agent.tools.base import ToolContext, ToolOutput

DESCRIBE_BINDING_PROMPT = """
Before calling a binding you have not used yet, call `describe_binding` with
its name to learn its methods and parameters. Do it once per binding per task —
the answer does not change mid-run.

You do not need this for a binding you have already described, and you do not
need to describe every binding up front. Describe the one you are about to use.
""".strip()

# The key `execute_code` and the runtime both use to publish the env namespace.
BINDINGS_STATE_KEY = "codemode_bindings"


class DescribeBindingTool:
    """Return the API of one `env` binding."""

    # Pure inspection of the agent's own environment.
    read_only = True

    def __init__(self, *, name: str = "describe_binding") -> None:
        self.name = name
        self.description = (
            "Return the methods and parameters of one binding in `env`. "
            "Call this before using a binding for the first time."
        )
        self.prompt_instructions = DESCRIBE_BINDING_PROMPT

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": (
                                "Binding name as it appears in `env`, e.g. "
                                "'GITHUB'. Case-insensitive."
                            ),
                        }
                    },
                    "required": ["name"],
                },
            },
        }

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        bindings: dict[str, Any] = context.state.get(BINDINGS_STATE_KEY) or {}
        if not bindings:
            return ToolOutput(
                text=(
                    "No bindings are available in this run. `env` is only "
                    "populated when the agent runs in code mode."
                ),
                metadata={"binding": None, "available": []},
            )

        requested = str(kwargs.get("name") or "").strip()
        if not requested:
            return ToolOutput(
                text=_available(bindings),
                metadata={"binding": None, "available": sorted(bindings)},
            )

        binding = _resolve(bindings, requested)
        if binding is None:
            return ToolOutput(
                text=(
                    f"No binding named {requested!r}.\n\n" + _available(bindings)
                ),
                metadata={"binding": None, "available": sorted(bindings)},
            )

        return ToolOutput(
            text=binding.describe(),
            metadata={
                "binding": binding.name,
                "tool": binding.tool_name,
                "methods": binding.method_names(),
                "read_only": binding.contract.read_only,
            },
        )


def _resolve(bindings: dict[str, Any], requested: str) -> Any:
    """Find a binding by name, tolerantly.

    Models write ``env.GITHUB``, ``github``, and ``GitHub`` interchangeably;
    failing on case would spend a turn on nothing.
    """
    stripped = requested.removeprefix("env.").strip()
    if stripped in bindings:
        return bindings[stripped]
    lowered = stripped.lower()
    for name, binding in bindings.items():
        if name.lower() == lowered:
            return binding
    for name, binding in bindings.items():
        if getattr(binding, "tool_name", "").lower() == lowered:
            return binding
    return None


def _available(bindings: dict[str, Any]) -> str:
    lines = ["Available bindings:"]
    lines.extend(
        binding.summary_line() for _, binding in sorted(bindings.items())
    )
    return "\n".join(lines)
