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


#: When the model keeps restating the same plan across steps instead of acting.
#: The observed failure (a benchmark): the model announced *"I will check the
#: required evidence and classify the urgency…"* four separate times, each a
#: model call, before doing the work — 3× the tokens of a terser loop for the
#: same answer. This fires only when a near-identical narration has already been
#: seen this turn, so a first, honest "here's my plan" is never discouraged.
REANNOUNCE_DAMPER = (
    "You have already stated this plan earlier this turn. Do not restate your "
    "intent again — issue the next tool call now, or give your final answer. "
    "Repeating the plan does not advance the task and costs a step."
)


def _normalize_narration(text: str) -> str:
    return " ".join(str(text).lower().split())


def is_reannouncing(
    messages: list, *, threshold: float = 0.85, window: int = 3, min_len: int = 15
) -> bool:
    """Has the model just restated a plan it already narrated this turn?

    Reads the assistant's own text messages (its narration) — no tool payloads,
    no names. True when the most recent narration is near-identical to one of the
    couple before it (normalized similarity ≥ ``threshold``). A short blurb
    ("ok", "done") is ignored (``min_len``) so only real plan-restatement counts.
    Stateless: it inspects the message list the step already carries.
    """
    import difflib

    narrations = [
        c.strip()
        for m in messages
        if getattr(m, "role", "") == "assistant"
        and isinstance((c := getattr(m, "content", "")), str)
        and c.strip()
    ]
    if len(narrations) < 2:
        return False
    recent = narrations[-window:]
    last = _normalize_narration(recent[-1])
    if len(last) < min_len:
        return False
    for prior in recent[:-1]:
        if difflib.SequenceMatcher(None, last, _normalize_narration(prior)).ratio() >= threshold:
            return True
    return False


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
