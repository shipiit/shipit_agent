"""``present_plan`` — the plan-mode exit affordance (Claude Code's ExitPlanMode).

In plan mode the agent researches read-only and must not act. When it has a
plan, it calls this tool to *submit* it: the plan is captured as a structured
artifact, surfaced to the user for approval, and the run pauses on it. The
caller approves (switching the agent out of plan mode) or sends changes.

Without this, plan mode is only a gate — the model narrates a plan into prose
and there is no captured object, no explicit approve-to-execute step.
"""

from __future__ import annotations

from shipit_agent.tools.base import ToolContext, ToolOutput


class PresentPlanTool:
    #: Read-only: it produces a plan, it does not act. So it is allowed to
    #: run in plan mode (it is the one write-shaped thing plan mode needs).
    read_only = True

    def __init__(self, *, name: str = "present_plan") -> None:
        self.name = name
        self.description = (
            "Submit your plan for approval and stop. Call this once, in plan "
            "mode, when you have finished researching and are ready to act — "
            "the plan is shown to the user, who approves it (letting you "
            "execute) or asks for changes. Do not act before it is approved."
        )
        self.prompt = (
            "When you are in plan mode and have a concrete plan, call "
            "present_plan with the plan (a short title and the ordered steps). "
            "This is how you hand the plan to the user for approval; do not "
            "start executing until they accept it."
        )
        self.prompt_instructions = (
            "Call present_plan(title, steps=[...]) to submit a plan for "
            "approval. Steps is an ordered list of what you will do."
        )

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "A one-line summary of the plan.",
                        },
                        "steps": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "The ordered steps you will take.",
                        },
                        "notes": {
                            "type": "string",
                            "description": "Optional risks, assumptions, or alternatives.",
                        },
                    },
                    "required": ["title", "steps"],
                },
            },
        }

    def run(self, context: ToolContext, **kwargs) -> ToolOutput:
        title = str(kwargs.get("title", "")).strip() or "Plan"
        steps = kwargs.get("steps") or []
        if not isinstance(steps, list) or not steps:
            return ToolOutput(
                text="present_plan needs a non-empty `steps` array — the "
                "ordered actions you intend to take.",
                metadata={"error": "empty_plan"},
            )
        steps = [str(s) for s in steps]
        notes = str(kwargs.get("notes", "")).strip()
        rendered = f"## {title}\n\n" + "\n".join(
            f"{i}. {s}" for i, s in enumerate(steps, start=1)
        )
        if notes:
            rendered += f"\n\nNotes: {notes}"
        return ToolOutput(
            text=(
                rendered
                + "\n\nThis plan is awaiting your approval. Approve it to let "
                "the agent execute, or reply with changes."
            ),
            metadata={
                # The runtime surfaces `interactive` results as an
                # interactive_request event and pauses on them — the same
                # channel ask_user uses, so a UI already renders it.
                "interactive": True,
                "kind": "plan_approval",
                "title": title,
                "steps": steps,
                "notes": notes,
                "awaiting_approval": True,
            },
        )
