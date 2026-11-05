"""Tool calls from one response: ids, argument checks, duplicates, withheld tools and which calls may run in parallel.

Mixed into :class:`~shipit_agent.core.runtime_core.RuntimeCore`;
the methods run on the runtime instance.
"""

from __future__ import annotations

from typing import Any, Sequence

from shipit_agent.core.decisions.call_keys import WITHHELD_TOOLS_KEY, _arguments_key
from shipit_agent.core.models import Message
from shipit_agent.llms.base import LLMResponse


class ToolCallsMixin:
    """Tool calls from one response: ids, argument checks, duplicates, withheld tools and which calls may run in parallel."""

    def model_supports_parallel_tool_calls(self) -> bool:
        """Return the active model's declared tool-call batching capability."""
        from shipit_agent.llms.capabilities import capabilities_for

        model = str(getattr(getattr(self, "llm", None), "model", "") or "")
        return capabilities_for(model).supports_parallel_tool_calls

    def assign_tool_call_ids(
        self,
        tool_calls: Sequence[Any],
        messages: Sequence[Message],
        iteration: int,
    ) -> list[dict[str, Any]]:
        """Give every call a conversation-unique ID and return wire records.

        Provider IDs are kept unless the provider has reused one earlier in
        this conversation. Text-healed calls have no provider ID, so the
        familiar ``call_<iteration>_<position>`` form is used when available
        and receives a suffix only on a later-turn collision.
        """
        used = {
            call.id
            for message in messages
            for call in (getattr(message, "tool_calls", None) or [])
            if call.id
        }
        records: list[dict[str, Any]] = []
        for index, tool_call in enumerate(tool_calls, start=1):
            base = str(tool_call.id or f"call_{iteration}_{index}")
            call_id = base
            suffix = 2
            while call_id in used:
                call_id = f"{base}_{suffix}"
                suffix += 1
            used.add(call_id)
            tool_call.id = call_id
            records.append(
                {
                    "id": call_id,
                    "name": tool_call.name,
                    "arguments": dict(tool_call.arguments),
                }
            )
        return records

    def check_arguments(self, tool: Any, tool_call: Any) -> str | None:
        """Repair a call's arguments in place; return an error if it cannot run.

        Returns ``None`` when the call is fine — including when it was fixed,
        since a repaired call is a working one. Returns a sentence addressed
        to the model when a declared-required argument is absent, so the next
        step supplies it instead of the tool being handed nothing.

        Refusing is the point. A search tool with an optional filter reads a
        missing filter as "no filter" and returns everything it has; the model
        then answers confidently about the corpus rather than the question,
        and every layer reports success. An error the model can act on is far
        better than an answer nobody can tell is wrong.
        """
        from shipit_agent.safety.tool_healing import (
            call_carries_nothing,
            repair_argument_names,
            schemas_from_tools,
        )

        schema = schemas_from_tools([tool]).get(getattr(tool, "name", ""))
        if not schema:
            return None
        arguments = dict(getattr(tool_call, "arguments", None) or {})
        repaired = repair_argument_names(arguments, schema)
        if repaired != arguments:
            tool_call.arguments = repaired
            arguments = repaired
        from shipit_agent.safety.action_detection import is_degenerate_repetition

        def _strings(value: Any):
            if isinstance(value, str):
                yield value
            elif isinstance(value, dict):
                for nested in value.values():
                    yield from _strings(nested)
            elif isinstance(value, (list, tuple)):
                for nested in value:
                    yield from _strings(nested)

        import json

        encoded_size = len(
            json.dumps(
                arguments, ensure_ascii=False, default=str, separators=(",", ":")
            )
        )
        limit = getattr(self, "max_tool_argument_chars", 0)
        if limit and encoded_size > limit:
            return (
                f"Error: {getattr(tool, 'name', 'tool')} produced {encoded_size:,} "
                f"characters of arguments, above this agent's {limit:,}-character "
                "per-call safety limit. It was not run. Retry once with only the "
                "specific input needed for the user's request."
            )
        if any(
            len(" ".join(value.split())) >= 512 and is_degenerate_repetition(value)
            for value in _strings(arguments)
        ):
            return (
                f"Error: {getattr(tool, 'name', 'tool')} produced a pathologically "
                "repetitive argument. It was not run. Retry once with a concise "
                "argument copied from the user's request; do not repeat planning "
                "or instructions inside tool arguments."
            )
        absent = call_carries_nothing(arguments, schema)
        if not absent:
            return None
        names = ", ".join(f"'{name}'" for name in absent)
        # Blind-call repair: a model running with deferred_tools never saw this
        # tool's schema, so it guesses argument names (``items`` for
        # ``provided_items``) and the guess bounces here. Handing back the full
        # signature — every parameter, its type, which are required — turns a
        # dead retry into a correct one. Weak models (gemini-flash) especially
        # cannot recover from a name-only bounce without it.
        signature = self._signature_hint(tool)
        signature_clause = f" Signature: {signature}." if signature else ""
        return (
            f"Error: {getattr(tool, 'name', 'tool')} was called with no usable "
            f"arguments. It was not run. Call it again and pass {names} — a "
            f"value taken from the user's question, not an empty string."
            f"{signature_clause} With nothing to go on this tool returns "
            f"everything it has, which is not what was asked for."
        )

    @staticmethod
    def _signature_hint(tool: Any) -> str:
        """A one-line callable signature for ``tool``, or ``""`` if unavailable.

        The compact form (``name(required: type, optional?: type)``) is the same
        one the deferred-tool index prints, so a blind call gets exactly the
        contract it would have seen had the schema not been withheld.
        """
        from shipit_agent.deferral.core import signature_line

        try:
            return signature_line(tool.schema())
        except Exception:  # noqa: BLE001 — a hint that can't render is just absent
            return ""

    def ignore_calls_on_text_step(
        self, state: Any, response: LLMResponse, iteration: int
    ) -> None:
        """On a step sent with no tools, a tool call is not an option the model
        was given. Processing it re-arms the duplicate cycle and loops the run
        to max_iterations, so the calls are dropped and the text is the answer."""
        names = sorted({str(call.name) for call in response.tool_calls})
        response.tool_calls = []
        self.emit(
            state,
            "tool_calls_ignored",
            "Ignored tool calls on a text-only step",
            tools=names,
            iteration=iteration,
        )

    @staticmethod
    def without_withheld(schemas: list[Any], shared_state: dict[str, Any]) -> list[Any]:
        withheld = shared_state.get(WITHHELD_TOOLS_KEY) or set()
        if not withheld:
            return schemas
        return [
            schema
            for schema in schemas
            if str((schema.get("function") or {}).get("name", "")) not in withheld
        ]

    @staticmethod
    def force_text_after_duplicate_batch(
        messages: Sequence[Message], call_records: Sequence[dict[str, Any]]
    ) -> bool:
        """Whether every call in the latest batch was already executed."""
        ids = {str(record.get("id", "")) for record in call_records}
        outcomes = [
            message
            for message in messages
            if message.role == "tool" and str(message.tool_call_id or "") in ids
        ]
        return (
            bool(ids)
            and len(outcomes) == len(ids)
            and all(
                message.metadata.get("duplicate_suppressed") for message in outcomes
            )
        )

    @classmethod
    def settle_duplicate_batch(
        cls,
        shared_state: dict[str, Any],
        messages: Sequence[Message],
        call_records: Sequence[dict[str, Any]],
    ) -> None:
        """After a step made only of repeats, take the repeated tools away.

        A model that ignores the "already ran" note will call the same thing
        again next step. Withholding just those tools leaves it everything
        else — including whatever it still has to do with the result. Only a
        model that repeats again after that is sent to text-only.
        """
        if not cls.force_text_after_duplicate_batch(messages, call_records):
            return
        names = {str(record.get("name") or "") for record in call_records} - {""}
        withheld = shared_state.setdefault(WITHHELD_TOOLS_KEY, set())
        if names and not names <= withheld:
            withheld.update(names)
            return
        shared_state["force_text_after_duplicate"] = True

    @staticmethod
    def read_only_calls(tool_calls: list[Any], registry: Any) -> list[bool]:
        """Per-call: is this tool read-only (safe to run concurrently)?

        Uses each tool's contract — the same declaration the permission and
        artifact layers trust. Read-only calls (grep, glob, file reads, a
        lookup) have no side effects and no ordering constraint, so they can
        fan out; anything that writes, sends, or mutates must stay ordered.
        The user-visible speed win is exactly this: batch the reads,
        serialize the writes.
        """
        from shipit_agent.tools.contracts import contract_for

        flags: list[bool] = []
        for call in tool_calls:
            name = getattr(call, "name", "")
            tool = registry.get(name) if registry is not None else None
            flags.append(bool(contract_for(name, tool).read_only))
        return flags

    @staticmethod
    def remember_tool_call(
        state: Any, signature: tuple[str, str] | None, *, failed: bool
    ) -> None:
        """Update the duplicate-call memory after a tool finishes.

        A read-only call is remembered so an identical repeat is skipped. A
        successful call that may change state (a write, an edit, a command)
        clears that memory: an earlier read may now describe a file that has
        changed, and re-reading after an edit is how an agent checks its work.
        A failed mutation changed nothing, so the memory stays.
        """
        if signature is not None:
            state.executed_readonly_calls.add(signature)
        elif not failed:
            state.executed_readonly_calls.clear()

    @staticmethod
    def readonly_call_signature(tool: Any, tool_call: Any) -> tuple[str, str] | None:
        """A dedup key for a READ-ONLY call, or None if the tool may mutate.

        Returns ``(name, arguments_key)`` only for a tool whose contract is
        read-only — the one case where skipping an exact repeat is always safe
        (no side effect, the result is already in context). Anything that
        writes, sends, or mutates returns None and is never suppressed. Shared
        by both loops so the duplicate-call gate behaves identically.
        """
        from shipit_agent.tools.contracts import contract_for

        name = str(getattr(tool_call, "name", "") or "")
        if not contract_for(name, tool).read_only:
            return None
        return (name, _arguments_key(getattr(tool_call, "arguments", None)))
