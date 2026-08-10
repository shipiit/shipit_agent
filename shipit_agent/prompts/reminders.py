"""A short instruction placed at the very end of the context.

Models attend most strongly to the tokens closest to generation. An
instruction that must be followed reliably — not merely stated once — belongs
after the conversation, not in the system prompt at the top of it. This is the
difference between a rule the model usually follows and one it follows nearly
always.

Three properties make a reminder work, and losing any of them undoes it:

- **It is short.** It competes with the user's last message for attention. A
  reminder that restates the system prompt buries the one line that matters.
- **It is conditional.** A reminder that appears every turn stops being read.
  Each one below is gated on a state the runtime can actually observe.
- **It is rebuilt, never accumulated.** The runtime appends it to a per-call
  copy of the message list, so it is always last and never stacks.

Nothing here inspects tool payloads or names a tool. The conditions are facts
the runtime already knows: whether tools ran, and whether any step remains.
"""

from __future__ import annotations

#: After tools ran and steps remain. Targets the observed failure: a search
#: returns fifteen items, the model opens one, and answers as if it had read
#: them all — a sample presented as a finding.
DEPTH_REMINDER = (
    "Before answering: if a tool returned several relevant items and you have "
    "examined only one, open the others now — several in one response. If your "
    "answer would rest on a fraction of what you retrieved, either go back and "
    "read the rest or say plainly which part you checked."
)

#: On the final step, when no further tool call is possible. Without this the
#: model spends its last step announcing a call that can never run, and the
#: turn ends with no answer at all.
LAST_STEP_REMINDER = (
    "This is your final step — no further tool calls are possible. Answer now "
    "from what you already have, and state plainly anything you could not "
    "verify."
)


def build_reminder(
    *,
    ran_tools: bool,
    out_of_steps: bool,
    custom: str | None = None,
) -> str | None:
    """Compose the reminder for this step, or ``None`` if there is nothing to say.

    ``custom`` is caller-supplied standing guidance. It is included whenever
    it is set, because it is the caller's own reliability requirement — the
    reason the mechanism exists.
    """
    parts: list[str] = []
    if out_of_steps:
        parts.append(LAST_STEP_REMINDER)
    elif ran_tools:
        parts.append(DEPTH_REMINDER)
    if custom and custom.strip():
        parts.append(custom.strip())
    if not parts:
        return None
    return "\n\n".join(parts)
