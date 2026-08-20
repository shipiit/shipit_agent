"""``give_up`` — let the agent say it is stuck, structurally.

Without this, an agent that cannot proceed emits prose ("I'm not able to find
the config file…") and the loop reads that as a final answer. The runtime does
not guess intent from language-specific phrases; only malformed call structure
receives a bounded recovery attempt. A genuine blocker therefore needs an
explicit protocol of its own.

Cloudflare OS gives the model a real tool for it, with a required reason. A
declared stop is unambiguous: the caller can branch on it, an autopilot loop
can halt instead of burning its budget, and the reason is in the transcript
rather than buried in prose.

    result = agent.run("Deploy to prod")
    if result.metadata.get("gave_up"):
        print(result.metadata["give_up_reason"])
"""

from __future__ import annotations

from typing import Any

from shipit_agent.tools.base import ToolContext, ToolOutput

GIVE_UP_PROMPT = """
Call `give_up` when you genuinely cannot complete the task — a required file,
credential, permission, or piece of information is missing and no tool you have
can obtain it.

Give a specific reason: what you needed, what you tried, and what would unblock
you. "I couldn't do it" is not a reason.

Do NOT call this because a task is large or tedious. Do NOT call it before you
have actually tried. It is for being blocked, not for being reluctant.
""".strip()


class GiveUpTool:
    """Declare the task blocked, with a reason."""

    # An observation: it changes nothing outside the run, so gating it would
    # only stop the agent from telling you it is stuck.
    read_only = True

    def __init__(self, *, name: str = "give_up") -> None:
        self.name = name
        self.description = (
            "Declare that you cannot complete the task, with a specific reason. "
            "Use only when genuinely blocked, not when the work is merely hard."
        )
        self.prompt_instructions = GIVE_UP_PROMPT

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "reason": {
                            "type": "string",
                            "description": (
                                "What you needed, what you tried, and what would "
                                "unblock you."
                            ),
                        },
                        "needs": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Specific things that would unblock you — a file "
                                "path, a credential, a decision from the user."
                            ),
                        },
                    },
                    "required": ["reason"],
                },
            },
        }

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        reason = str(kwargs.get("reason") or "").strip()
        needs = [str(n) for n in (kwargs.get("needs") or []) if str(n).strip()]

        if not reason:
            # Refuse an empty give-up rather than recording a useless stop —
            # this is the one case where pushing back is more useful than
            # accepting the call.
            return ToolOutput(
                text=(
                    "give_up needs a reason. Say what you needed, what you tried, "
                    "and what would unblock you — then either call it again with "
                    "that reason, or keep working."
                ),
                metadata={"gave_up": False, "error": "missing_reason"},
            )

        lines = [f"Blocked: {reason}"]
        if needs:
            lines.append("")
            lines.append("Would unblock this:")
            lines.extend(f"- {need}" for need in needs)

        return ToolOutput(
            text="\n".join(lines),
            metadata={
                "gave_up": True,
                "give_up_reason": reason,
                "give_up_needs": needs,
                # Surfaced to the caller via AgentResult.metadata, and worth
                # keeping: a stop is exactly the kind of fact a later run wants.
                "persist": True,
            },
        )
