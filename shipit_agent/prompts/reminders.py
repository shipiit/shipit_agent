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


#: Before any tool has run, while tools are available. This is the failure it
#: exists for, observed live: asked "what are the latest cases we have?", the
#: agent called nothing and replied *"I have retrieved the most recent cases
#: tracked in the platform. There are currently 10 recent cases"* — followed
#: by a full table of case IDs, names, organisations and dates. Every row was
#: invented. `list_recent_cases` and `search_cases` were both attached and
#: neither was called.
#:
#: An answer that is merely wrong can be argued with. An answer that claims
#: retrieval it never performed cannot, because nothing about it looks
#: uncertain — which is why this is the one reminder that fires before the
#: model has done anything at all.
GROUNDING_REMINDER = (
    "You have not called any tool yet this turn. If the answer depends on the "
    "user's own data — their cases, records, documents or feeds — retrieve it "
    "with a tool first. Never present information as retrieved, looked up or "
    "tracked unless a tool in this conversation actually returned it. If no "
    "tool can reach what was asked for, say that plainly instead of "
    "producing an example."
)


def build_reminder(
    *,
    ran_tools: bool,
    out_of_steps: bool,
    custom: str | None = None,
) -> str | None:
    """Compose the reminder for this step, or ``None`` if there is nothing to say.

    The three built-ins follow the shape of the turn, so exactly one applies
    at a time and none of them is boilerplate: before anything has been
    retrieved the risk is invention; once something has, the risk is
    answering from too little of it; on the last step the risk is spending it
    on a call that cannot run.

    ``custom`` is caller-supplied standing guidance. It is included whenever
    it is set, because it is the caller's own reliability requirement — the
    reason the mechanism exists.
    """
    parts: list[str] = []
    if out_of_steps:
        parts.append(LAST_STEP_REMINDER)
    elif ran_tools:
        parts.append(DEPTH_REMINDER)
    else:
        parts.append(GROUNDING_REMINDER)
    if custom and custom.strip():
        parts.append(custom.strip())
    if not parts:
        return None
    return "\n\n".join(parts)
