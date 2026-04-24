"""`ask_user_async` — tool implementation.

The tool is deliberately tiny: it appends one question to the channel
and returns a synthetic string that tells the model to end the turn so
Autopilot can halt into ``awaiting_user`` state.

The runtime integration (adding awaiting_user as an Autopilot halt
reason, resume picking up the answer) lives in Autopilot itself via
the helpers in :mod:`shipit_agent.askuser_channel`. That way this tool
works equally well for a plain `Agent` run — the user is expected to
invoke it when the surrounding runtime knows how to handle halts.
"""

from __future__ import annotations

from typing import Any

from shipit_agent.askuser_channel import ask_question
from shipit_agent.tools.base import ToolContext, ToolOutput

from .prompt import ASK_USER_ASYNC_PROMPT


class AskUserAsyncTool:
    name = "ask_user_async"
    description = (
        "Pause an Autopilot run to ask the user a clarifying question — "
        "non-blocking; the run halts into awaiting_user and resumes once "
        "the user answers via `shipit answer <run_id> \"...\"`."
    )
    prompt_instructions = ASK_USER_ASYNC_PROMPT

    def __init__(self) -> None:
        self.prompt = self.prompt_instructions

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "The ONE focused question to put to the user.",
                        },
                        "context": {
                            "type": "string",
                            "description": "Optional one-line context on why you need the answer (what you tried, what is ambiguous).",
                        },
                        "choices": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional list of suggested answers — the user is not forced to pick one.",
                        },
                    },
                    "required": ["question"],
                },
            },
        }

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolOutput:
        # Positional param is `ctx` (not `context`) because this tool
        # accepts a `context` *kwarg* in its schema — Python would
        # otherwise raise TypeError when both are supplied.
        question = str(kwargs.get("question", "")).strip()
        if not question:
            return ToolOutput(text="Error: `question` is required.", metadata={"ok": False})

        run_id = _resolve_run_id(ctx)
        entry = ask_question(
            run_id,
            question,
            context=str(kwargs.get("context", "")).strip(),
            choices=[str(c) for c in kwargs.get("choices", []) if c],
        )

        # Signal Autopilot (and any other runtime that cares) to halt
        # into awaiting_user — the metadata is the contract. The `text`
        # is rendered back to the model so it sees confirmation and
        # knows to end its turn.
        return ToolOutput(
            text=(
                f"[ask_user_async] Question queued for run_id={run_id!r}:\n"
                f"  {entry.question}\n\n"
                f"The run will halt into status='awaiting_user'. "
                f"End your turn now; Autopilot will resume after the user replies via "
                f"`shipit answer {run_id} \"...\"`."
            ),
            metadata={
                "ok": True,
                "awaiting_user": True,          # ← the sentinel Autopilot watches
                "run_id": run_id,
                "question": entry.question,
                "context": entry.context,
                "choices": list(entry.choices),
            },
        )


def _resolve_run_id(context: ToolContext) -> str:
    """Pull the active run_id out of the ToolContext.

    Autopilot sets ``state['autopilot_run_id']`` on every context it
    dispatches; plain `Agent` users can pass it via metadata or
    ``session_id`` as a fallback.
    """
    state = getattr(context, "state", None) or {}
    meta = getattr(context, "metadata", None) or {}
    for src in (state, meta):
        rid = src.get("autopilot_run_id") or src.get("run_id")
        if rid:
            return str(rid)
    return str(getattr(context, "session_id", None) or "default")
