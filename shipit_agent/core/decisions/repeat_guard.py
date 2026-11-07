"""Stopping a model that repeats one call and keeps getting the same result.

Repeated *read-only* calls are suppressed before they run. A call that changes
things cannot be suppressed that way, so a model that sends the same one over
and over, getting the same answer back, would never finish once there is no
step limit. This notices the repetition after it happens: the same calls with
the same results for :data:`REPEAT_LIMIT` steps in a row.

Mixed into :class:`~shipit_agent.core.runtime_core.RuntimeCore`;
the methods run on the runtime instance.
"""

from __future__ import annotations

import hashlib
from typing import Any, Sequence

from shipit_agent.core.decisions.call_keys import WITHHELD_TOOLS_KEY, _arguments_key
from shipit_agent.core.models import Message

#: Identical steps in a row before the repeated tools are withheld. A call
#: whose result changes (polling a build) never counts as a repeat.
REPEAT_LIMIT = 3

_LAST_STEP_KEY = "_repeat_step_key"
_REPEATS_KEY = "_repeat_step_count"


class RepeatGuardMixin:
    """Stopping a model that repeats one call and keeps getting the same result."""

    def settle_repeated_results(
        self,
        state: Any,
        shared_state: dict[str, Any],
        call_records: Sequence[dict[str, Any]],
        *,
        iteration: int,
    ) -> None:
        """Withhold tools whose identical call returned the identical result again.

        First the repeated tools are taken out of what the model is offered;
        a model that calls them anyway is then asked for a text answer, which
        always ends the turn.
        """
        if _all_refused(state.messages, call_records):
            # The model named only withheld tools: it is ignoring the
            # withholding, so the next step must be its answer.
            shared_state["force_text_after_duplicate"] = True
            return
        key = _step_key(state.messages, call_records)
        if key is None or key != shared_state.get(_LAST_STEP_KEY):
            shared_state[_LAST_STEP_KEY] = key
            shared_state[_REPEATS_KEY] = 1
            return
        shared_state[_REPEATS_KEY] = repeats = shared_state.get(_REPEATS_KEY, 1) + 1
        if repeats < REPEAT_LIMIT:
            return
        names = {str(record.get("name") or "") for record in call_records} - {""}
        withheld = shared_state.setdefault(WITHHELD_TOOLS_KEY, set())
        if names <= withheld:
            shared_state["force_text_after_duplicate"] = True
            return
        withheld.update(names)
        self.emit(
            state,
            "tool_withheld",
            "Withheld tools repeating the same call and result",
            tools=sorted(names),
            repeats=repeats,
            iteration=iteration,
        )

    def refuse_withheld_call(
        self,
        state: Any,
        shared_state: dict[str, Any],
        tool_call: Any,
        call_record: dict[str, Any],
        *,
        iteration: int,
    ) -> Message | None:
        """The tool message refusing a call to a withheld tool, or ``None`` to run it.

        A withheld tool is no longer offered, but a model can still name it.
        Running it again would repeat what was just shown to change nothing.
        """
        if tool_call.name not in (shared_state.get(WITHHELD_TOOLS_KEY) or ()):
            return None
        self.emit(
            state,
            "tool_failed",
            f"Not run: {tool_call.name} is withheld",
            tool=tool_call.name,
            call_id=call_record["id"],
            error="tool_withheld",
            iteration=iteration,
        )
        return Message(
            role="tool",
            name=tool_call.name,
            content=(
                f"Not run: {tool_call.name} was withheld because the same call "
                "kept returning the same result. Answer from the results above, "
                "or take a different approach."
            ),
            tool_call_id=call_record["id"],
            metadata={"tool_call_id": call_record["id"], "error": "tool_withheld"},
        )


def _all_refused(
    messages: Sequence[Message], call_records: Sequence[dict[str, Any]]
) -> bool:
    """Whether every call in the step was refused because its tool is withheld."""
    ids = {str(record.get("id", "")) for record in call_records}
    refused = {
        str(message.tool_call_id or "")
        for message in messages
        if message.role == "tool"
        and (message.metadata or {}).get("error") == "tool_withheld"
    }
    return bool(ids) and ids <= refused


def _step_key(
    messages: Sequence[Message], call_records: Sequence[dict[str, Any]]
) -> str | None:
    """A fingerprint of one step's calls and their results, or ``None`` if incomplete."""
    outputs = {
        str(message.tool_call_id or ""): message.content
        for message in messages
        if message.role == "tool"
    }
    parts: list[str] = []
    for record in call_records:
        call_id = str(record.get("id", ""))
        if call_id not in outputs:
            return None
        parts.append(
            f"{record.get('name')}\0{_arguments_key(record.get('arguments'))}\0{outputs[call_id]}"
        )
    if not parts:
        return None
    return hashlib.sha256("\n".join(sorted(parts)).encode()).hexdigest()
