"""The parts of the agent loop that are the same whether you await or not.

``runtime.py`` and ``async_runtime.py`` are two implementations of one loop.
They have drifted, repeatedly and silently: ``tool_denied`` was missing its
payload in both and got fixed in one; ten capabilities — guardrails, tool-call
healing, compaction, lockdown, code mode, cancellation, usage ticks — existed
only in the sync one. Nobody decided that; it is just what happens when the
same decision is written twice.

So the decisions live here, once, and both runtimes inherit them. What is
genuinely different between the two is exactly one thing: whether the LLM call
and the tool call are awaited. Everything else — what to do with the response,
when to compact, when to latch lockdown, what state a tool can see — is the
same logic and now the same code.

A method belongs here if it does not need to await anything.
"""

from __future__ import annotations

import hashlib
import json
import threading
from copy import deepcopy
import re

from typing import Any, Sequence

from shipit_agent.action_detection import is_malformed_action_attempt
from shipit_agent.llms.base import LLMResponse
from shipit_agent.models import Message
from shipit_agent.permissions import (
    PermissionDecision,
    PermissionResult,
    authorize_tool,
)

__all__ = ["RuntimeCore", "is_malformed_action_attempt"]


# What a file extension means to a person. Anything unlisted is "File" —
# a wrong label is worse than a plain one.
_ARTIFACT_KINDS = {
    ".html": "Page",
    ".htm": "Page",
    ".md": "Doc",
    ".txt": "Doc",
    ".rtf": "Doc",
    ".pdf": "PDF",
    ".docx": "Doc",
    ".csv": "Sheet",
    ".tsv": "Sheet",
    ".xlsx": "Sheet",
    ".xls": "Sheet",
    ".json": "Data",
    ".yaml": "Data",
    ".yml": "Data",
    ".xml": "Data",
    ".png": "Image",
    ".jpg": "Image",
    ".jpeg": "Image",
    ".svg": "Image",
    ".gif": "Image",
    ".webp": "Image",
    ".pptx": "Deck",
    ".key": "Deck",
    ".py": "Code",
    ".js": "Code",
    ".ts": "Code",
    ".sql": "Code",
    ".sh": "Code",
    ".zip": "Archive",
    ".tar": "Archive",
    ".gz": "Archive",
}

# Metadata keys a tool uses to say "I wrote this".
_PATH_KEYS = ("path", "file", "filepath", "file_path", "output_path", "artifact")
_PATH_LIST_KEYS = ("paths", "files", "artifacts", "outputs")


def _artifact_kind(path: Any) -> str:
    from pathlib import Path as _Path

    return _ARTIFACT_KINDS.get(_Path(path).suffix.lower(), "File")


def _declared_paths(metadata: dict) -> list:
    """Paths a tool declared, that exist on disk, in first-seen order."""
    from pathlib import Path as _Path

    candidates: list[str] = []
    for key in _PATH_KEYS:
        value = metadata.get(key)
        if isinstance(value, str) and value:
            candidates.append(value)
    for key in _PATH_LIST_KEYS:
        value = metadata.get(key)
        if isinstance(value, (list, tuple)):
            candidates += [item for item in value if isinstance(item, str)]

    found: list = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            path = _Path(candidate)
            # A path that does not exist is a plan, not an artifact.
            if path.is_file():
                found.append(path)
        except OSError:
            continue
    return found


#: Below this, a repeated result is cheaper to resend than to explain.
_REPEAT_MIN_CHARS = 2_000

#: Tools taken out of the advertised set for the rest of a run because the
#: model kept repeating an identical call to them.
WITHHELD_TOOLS_KEY = "withheld_tool_names"

#: Below this, the stub costs more than the payload it replaces.
_EVICT_MIN_CHARS = 1_000


def _evicted_notice(message: Message, *, recall_tool_name: str = "") -> str:
    """A compact, factual pointer that does not invite a repeat-call loop."""
    metadata = dict(message.metadata or {})
    call_id = str(message.tool_call_id or metadata.get("tool_call_id") or "")
    path = str(metadata.get("persisted_output_path") or "")
    original_chars = len(message.content) if isinstance(message.content, str) else 0
    details = [
        f"call_id={call_id}" if call_id else "",
        f"original_chars={original_chars}" if original_chars else "",
        f"stored_at={path}" if path else "",
    ]
    suffix = "; ".join(detail for detail in details if detail)
    recall = (
        f" Retrieve the exact result with {recall_tool_name}(call_id={call_id!r}) "
        "only if it is needed."
        if recall_tool_name and call_id
        else ""
    )
    return (
        "[Earlier tool result omitted from the active prompt to save context"
        + (f" ({suffix})" if suffix else "")
        + ". The structured call and the assistant's answer remain above. "
        "Use those first."
        + recall
        + " Rerun the original external tool only when its data may have changed.]"
    )


def evict_prior_tool_outputs(
    messages: list[Message],
    *,
    min_chars: int = _EVICT_MIN_CHARS,
    recall_tool_name: str = "",
) -> list[Message]:
    """Replace tool *payloads* from earlier turns with a short notice.

    A message list is cumulative across turns as well as within one. A search
    that returned fifteen thousand characters in turn one is re-sent, in full,
    on every request of turn two, turn three, and so on — long after the model
    has written whatever mattered into its answer.

    What is kept is the part that stays useful and costs almost nothing: the
    assistant's tool call, with its name and arguments. That is what tells the
    model what it already looked for, so it doesn't look again. What goes is
    the payload, which it has already read.

    The messages themselves are never dropped. A tool result removed while its
    assistant tool-call message remains is a malformed conversation that some
    providers reject outright, so each is replaced in place — same role, same
    name, same ``tool_call_id`` — and only the content changes.

    Small outputs are left alone: below ``min_chars`` the notice is the larger
    of the two.
    """
    evicted: list[Message] = []
    for message in messages:
        if (
            getattr(message, "role", "") == "tool"
            # Block-content messages (images) are never evicted here — they
            # have their own recency-based pruning in step_request, and
            # replacing a list with a text notice would corrupt the shape.
            and isinstance(message.content, str)
            and len(message.content or "") >= min_chars
        ):
            evicted.append(
                Message(
                    role="tool",
                    name=message.name,
                    content=_evicted_notice(message, recall_tool_name=recall_tool_name),
                    tool_call_id=message.tool_call_id,
                    metadata=dict(message.metadata or {}),
                )
            )
        else:
            evicted.append(message)
    return evicted


def _arguments_key(arguments: Any) -> str:
    """A stable key for a call's arguments, whatever they are.

    Sorted so that ``{"a": 1, "b": 2}`` and ``{"b": 2, "a": 1}`` are the
    same call, and falling back to ``repr`` for anything JSON cannot hold
    rather than raising inside the tool path.
    """
    try:
        return json.dumps(arguments or {}, sort_keys=True, default=str)
    except Exception:
        return repr(arguments)


class RuntimeCore:
    """Shared, synchronous decisions for both agent loops.

    Expects the host to provide: ``llm``, ``prompt``, ``metadata``, ``mcps``,
    ``permissions``, ``guardrails``, ``hooks``, ``lockdown``, ``approvals``,
    ``heal_tool_calls``, ``context_window_tokens``, ``credential_store``,
    ``memory_store``, and an ``emit(state, type, message, **payload)``.
    """

    # ── set up by the host's __init__ ────────────────────────────────────

    def _init_core(self, **options: Any) -> None:
        """Initialise the shared fields. Call from the host's ``__init__``."""
        from shipit_agent.approvals import coerce_queue
        from shipit_agent.lockdown import coerce_lockdown

        self.guardrails = options.get("guardrails")
        self.lockdown = coerce_lockdown(options.get("lockdown"))
        self.approvals = coerce_queue(options.get("approvals"))
        self.heal_tool_calls = bool(options.get("heal_tool_calls", True))
        self.code_mode = bool(options.get("code_mode", False))
        self.context_window_tokens = int(options.get("context_window_tokens", 0) or 0)
        self._session_runtime_state = options.get("session_runtime_state")
        if self._session_runtime_state is None:
            self._session_runtime_state = {}
        # The fixed prompt prefix (system prompt + tool schemas) is sent on
        # every call but lives outside ``messages``. Counted toward the
        # compaction trigger so it does not fire ~a-prefix's-worth late. 0 keeps
        # the pre-existing messages-only behaviour.
        self._fixed_prefix_tokens = int(options.get("fixed_prefix_tokens", 0) or 0)
        self._configured_fixed_prefix_tokens = self._fixed_prefix_tokens
        # Learns the per-model gap between our chars/4 estimate and the
        # provider's real ``prompt_tokens`` (fed at each completion) so the
        # trigger uses a calibrated number. Always present; harmless until it
        # has enough samples, and clamped so it can only ever compact earlier.
        from shipit_agent.token_calibration import TokenCalibrator

        self.token_calibrator = self._session_runtime_state.setdefault(
            "token_calibrator", TokenCalibrator()
        )
        self.max_tool_output_chars = int(options.get("max_tool_output_chars", 0) or 0)
        self.max_tool_output_group_chars = int(
            options.get("max_tool_output_group_chars", 0) or 0
        )
        self.tool_output_dir = str(options.get("tool_output_dir") or "")
        self.reminder = options.get("reminder") or None
        # Verify-on-stop: refuse to finish a turn that edited code without fresh
        # passing tests (evidence-gated coding). Off by default — it changes the
        # loop's stop behaviour, so a caller opts in.
        self.verify_before_stop = bool(options.get("verify_before_stop", False))
        self.evict_prior_tool_outputs = bool(
            options.get("evict_prior_tool_outputs", True)
        )
        # False | True | iterable of names — see shipit_agent.deferral.
        self.deferred_tools = options.get("deferred_tools", "auto")

        self._total_usage: dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        }
        self._total_uncached_input = 0
        self._total_context_input = 0
        self._request_estimates = {"system": 0, "conversation": 0, "tool_results": 0, "schemas": 0}
        self._purpose_usage = {"main": 0, "compaction": 0}
        # Tokens a routed step spent on a call it then threw away (StepRouter
        # escalation): real spend, so budgets and totals count it.
        self._discarded_tokens = 0
        # Per-model token buckets, so a run served by several models (a
        # StepRouter) is priced at each model's own rate.
        self._usage_by_model: dict[str, dict[str, int]] = {}
        self._schema_prefix = ""
        self._prefix_changes = 0
        self._cache_counters_reported = False
        self._usage_reports = 0
        self._complete_usage_reports = 0
        self._completed_model_calls = 0
        self._cancel_event = threading.Event()
        self._guarded_tool_calls = 0
        self._nudges_used = 0
        self._last_nudged_text = ""
        self._requested_tool_nudges: set[str] = set()
        self._compactor_instance: Any = self._session_runtime_state.get("compactor")
        self.connections: Any = None

    def model_supports_parallel_tool_calls(self) -> bool:
        """Return the active model's declared tool-call batching capability."""
        from shipit_agent.llms.capabilities import capabilities_for

        model = str(getattr(getattr(self, "llm", None), "model", "") or "")
        return capabilities_for(model).supports_parallel_tool_calls

    @staticmethod
    def install_result_recall(registry: Any, messages: Sequence[Message]) -> str:
        """Attach exact historical-result recall only when there is data for it."""
        from shipit_agent.tools.recall_result.recall_result_tool import (
            RecallToolResult,
            recallable_results,
        )

        results = recallable_results(list(messages), min_chars=_EVICT_MIN_CHARS)
        if not results or registry.get(RecallToolResult.name) is not None:
            return ""
        registry.register(RecallToolResult(results))
        return RecallToolResult.name

    @staticmethod
    def requested_tool_names(user_prompt: str, registry: Any) -> set[str]:
        """Return exact tool identifiers mentioned in the prompt.

        This is diagnostic only. Natural-language intent belongs to the model;
        mandatory execution belongs to the explicit ``required_tools`` API.
        The runtime must not turn prose around "tool" or "MCP" into policy.
        """
        source = user_prompt.lower()
        return {
            name
            for tool in registry.values()
            if (name := str(getattr(tool, "name", "") or ""))
            and re.search(
                rf"(?<![a-z0-9_]){re.escape(name.lower())}(?![a-z0-9_])",
                source,
            )
        }

    def missing_requested_tools(
        self, user_prompt: str, registry: Any, tool_results: Sequence[Any]
    ) -> list[str]:
        # Compatibility seam for custom RuntimeCore subclasses. Shipit no
        # longer promotes language guesses into mandatory execution policy.
        return []

    def initial_required_tool_names(self, user_prompt: str, registry: Any) -> set[str]:
        """Resolve first-step required tools against the live registry.

        Hosts may provide ``Agent(required_tools=[...])`` when their own
        routing has made an unambiguous capability choice. Unknown names are
        ignored so a changing connector catalogue cannot break a run.
        """
        available = {str(getattr(tool, "name", "") or "") for tool in registry.values()}
        configured = {
            str(name)
            for name in (getattr(self, "required_tools", None) or ())
            if str(name)
        }
        return configured & available

    def record_requested_tool_nudge(self, names: Sequence[str]) -> None:
        self._requested_tool_nudges.update(names)

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
    def without_withheld(
        schemas: list[Any], shared_state: dict[str, Any]
    ) -> list[Any]:
        withheld = shared_state.get(WITHHELD_TOOLS_KEY) or set()
        if not withheld:
            return schemas
        return [
            schema
            for schema in schemas
            if str((schema.get("function") or {}).get("name", "")) not in withheld
        ]

    @staticmethod
    def label_user_turns(messages: Sequence[Message]) -> list[Message]:
        """Label user turns in the transient model view.

        Tool calls insert several assistant/tool messages between user turns,
        so an instruction such as "use facts from turns 1, 3, and 5" is
        otherwise ambiguous to a model counting raw messages. Copies are
        returned because these labels are navigation aids, not user content,
        and must never enter the runtime transcript or durable session record.
        """
        labelled: list[Message] = []
        human_user_indexes = [
            index
            for index, message in enumerate(messages)
            if message.role == "user"
            and not (
                message.metadata.get("internal")
                or message.metadata.get("compacted")
                or message.metadata.get("vision_bridge")
                or message.metadata.get("regrounding")
                or message.metadata.get("source") == "planner"
            )
        ]
        current_user_index = human_user_indexes[-1] if human_user_indexes else -1
        turn = 0
        for index, message in enumerate(messages):
            clone = deepcopy(message)
            synthetic = bool(
                clone.metadata.get("internal")
                or clone.metadata.get("compacted")
                or clone.metadata.get("vision_bridge")
                or clone.metadata.get("regrounding")
                or clone.metadata.get("source") == "planner"
            )
            if clone.role == "user" and not synthetic:
                turn += 1
                if index != current_user_index and isinstance(clone.content, str):
                    clone.content = f"[User turn {turn}]\n{clone.content}"
            labelled.append(clone)
        return labelled

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
        from shipit_agent.tool_healing import (
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
        from shipit_agent.action_detection import is_degenerate_repetition

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
            json.dumps(arguments, ensure_ascii=False, default=str, separators=(",", ":"))
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
            len(" ".join(value.split())) >= 512
            and is_degenerate_repetition(value)
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

    # ── what one step sends ──────────────────────────────────────────────

    def step_request(
        self,
        *,
        messages: list[Message],
        tool_schemas: list[Any],
        iteration: int,
        ran_tools: bool,
    ) -> tuple[list[Message], list[Any]]:
        """The messages and schemas for one step.

        Two decisions live here rather than in either loop, because having
        them in both is how the loops drift apart.

        **The final step is sent without tools.** A tool call emitted there
        has no iteration left to run in: the run ends with the model having
        announced work instead of doing it, and the user gets no answer.
        Withholding the schemas forces the answer, and drops the largest
        fixed cost in the request from the longest prompt of the run. A run
        configured with a single step keeps its tools — dropping them there
        would mean the tool could never be called at all.

        **The reminder goes last.** Models attend most strongly to the tokens
        closest to generation. It is appended to the returned copy, never to
        the caller's list, so it is rebuilt each step and cannot stack.
        """
        from shipit_agent.prompts.reminders import (
            REANNOUNCE_DAMPER,
            build_reminder,
            is_reannouncing,
        )

        max_iterations = int(getattr(self, "max_iterations", 0) or 0)
        last_step = iteration == max_iterations and max_iterations > 1
        step_schemas = [] if last_step else list(tool_schemas)

        # Screenshots age fast; only the newest few are worth their tokens.
        # Applied to this per-call copy only — the originals stay stored.
        messages = self.prune_stale_images(list(messages))

        # The built-in reminders are about tool use, so they attach only when
        # tools exist — but a caller's own standing instruction applies to
        # every agent, tools or not. Dropping it silently for a tool-less
        # agent made `Agent(reminder=...)` a no-op in exactly the
        # configuration where the caller has no other end-of-context channel.
        if tool_schemas:
            reminder = build_reminder(
                ran_tools=ran_tools,
                out_of_steps=last_step,
                custom=self.reminder,
            )
            # Re-announcement damping: if the model keeps restating the same plan
            # across steps instead of acting, append a terse "act, don't restate"
            # line. Only with tools and not on the last step (which already tells
            # it to answer), and only once repetition is actually observed — a
            # first honest "here's my plan" is never discouraged.
            if not last_step and is_reannouncing(messages):
                reminder = (
                    f"{reminder}\n\n{REANNOUNCE_DAMPER}"
                    if reminder
                    else REANNOUNCE_DAMPER
                )
        else:
            reminder = (self.reminder or "").strip() or None
        if reminder:
            messages = [*messages, Message(role="user", content=reminder)]
        return messages, step_schemas

    # ── parallel safety ──────────────────────────────────────────────────

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

    # ── vision: tool results that carry an image ─────────────────────────

    #: How many image messages a request keeps. Screenshots age fast — the
    #: model acts on the newest one; older ones are pure input cost.
    MAX_VISION_MESSAGES = 3

    def vision_followup(self, tool_result: Any, tool_name: str) -> Message | None:
        """A user message carrying a tool result's image, or ``None``.

        Tools that produce something to LOOK AT (screenshots, image files,
        rendered pages) declare it: ``metadata["image_base64"]`` +
        ``metadata["media_type"]`` (the convention computer_use introduced),
        or the explicit ``metadata["vision"]`` flag. Providers want images
        in a *user* turn — Anthropic rejects rich blocks inside tool_result
        content on several transports — so the bridge is a synthetic user
        message appended right after the tool message.
        """
        metadata = dict(getattr(tool_result, "metadata", None) or {})
        data = metadata.get("image_base64")
        if not data or metadata.get("vision") is False:
            return None
        media_type = str(metadata.get("media_type") or "image/png")
        return Message(
            role="user",
            content=[
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": str(data),
                    },
                },
                {
                    "type": "text",
                    "text": f"[image returned by the {tool_name} tool]",
                },
            ],
            metadata={"vision_bridge": True, "internal": True, "tool": tool_name},
        )

    @classmethod
    def prune_stale_images(cls, messages: list[Message]) -> list[Message]:
        """Keep only the newest ``MAX_VISION_MESSAGES`` image messages.

        Applied to the per-request copy, never the stored conversation — the
        original screenshots stay in the session for replay. Older images
        are replaced by a one-line stub so the model still knows something
        was there (and can re-request it) without paying image tokens for a
        state of the world that no longer exists.
        """
        image_indexes = [
            i
            for i, m in enumerate(messages)
            if isinstance(m.content, list)
            and any(isinstance(b, dict) and b.get("type") == "image" for b in m.content)
        ]
        stale = set(image_indexes[: -cls.MAX_VISION_MESSAGES or None])
        if not stale:
            return messages
        pruned = list(messages)
        for i in stale:
            source = (pruned[i].metadata or {}).get("tool", "a tool")
            pruned[i] = Message(
                role=pruned[i].role,
                name=pruned[i].name,
                content=(
                    f"[an earlier image from {source} was shown here; it is "
                    "stale and has been removed — re-run the tool if you "
                    "need a fresh look]"
                ),
                metadata=dict(pruned[i].metadata or {}),
            )
        return pruned

    # ── deferred tool loading ────────────────────────────────────────────

    def restore_discovery(self, checkpoint: Any) -> None:
        """Restore names/hashes only; setup revalidates the current catalog.

        SessionStore authorization remains the caller's responsibility.
        Checkpoints carry no tool results, credentials, or permissions.
        """
        if not isinstance(checkpoint, dict) or checkpoint.get("version") != 1:
            return
        session_id = str(getattr(self, "session_id", ""))
        if checkpoint.get("session_id") != session_id:
            return
        entries = checkpoint.get("schemas")
        if not isinstance(entries, dict):
            return
        valid = {name: digest for name, digest in list(entries.items())[-64:]
                 if isinstance(name, str) and len(name) <= 256
                 and isinstance(digest, str) and len(digest) == 64}
        sessions = self._session_runtime_state.setdefault("discovery_sessions", {})
        sessions[session_id] = valid
        while len(sessions) > 32:
            sessions.pop(next(iter(sessions)))

    def discovery_checkpoint(self) -> dict[str, Any]:
        session_id = str(getattr(self, "session_id", ""))
        schemas = self._session_runtime_state.get("discovery_sessions", {}).get(session_id, {})
        return {"version": 1, "session_id": session_id, "schemas": dict(schemas)}

    def setup_deferral(self, registry: Any, shared_state: dict[str, Any]) -> str:
        """Activate deferred tool loading for this run, if configured.

        Publishes the deferred/loaded name sets and a schema lookup into
        the shared tool state (so ``tool_search`` can load tools and print
        signatures), and returns the name-only index section for the
        system prompt — empty when deferral is off or nothing qualifies.

        Code mode already collapses the catalogue its own way; when both
        are enabled, code mode wins and this is a no-op.
        """
        from shipit_agent.deferral import (
            DEFERRED_NAMES_KEY,
            LOADED_NAMES_KEY,
            SCHEMAS_BY_NAME_KEY,
            deferred_index,
            resolve_deferred_names,
        )

        permissions = getattr(self, "permissions", None)
        visibility = getattr(permissions, "discoverable", None)
        hidden = {t.name for t in registry.values() if callable(visibility) and not visibility(t.name, t)}
        shared_state["discovery_hidden"] = hidden
        shared_state["available_tools"] = [t for t in shared_state.get("available_tools", []) if t.get("name") not in hidden]
        if self.code_mode or not getattr(self, "deferred_tools", False):
            return ""
        tools = [t for t in registry.values() if t.name not in hidden]
        from shipit_agent.deferral.policy import (
            DiscoveryPolicy, schema_tokens, schema_fingerprint, select_resident,
        )
        from shipit_agent.deferral import DEFAULT_CORE_TOOLS

        policy = self.deferred_tools if isinstance(self.deferred_tools, DiscoveryPolicy) else DiscoveryPolicy()
        automatic = self.deferred_tools == "auto" or isinstance(self.deferred_tools, DiscoveryPolicy)
        schemas = {(s.get("function") or {}).get("name"): s for s in registry.schemas()
                   if (s.get("function") or {}).get("name") not in hidden}
        model = getattr(self.llm, "model", None)
        if automatic:
            # Small catalogs can still have very expensive schemas.
            needs_search = len(tools) > policy.initial_tools or sum(schema_tokens(s, model) for s in schemas.values()) > policy.schema_tokens
            deferred = {t.name for t in tools} if needs_search else set()
        else:
            deferred = resolve_deferred_names(tools, self.deferred_tools)
        if not deferred:
            return ""
        from shipit_agent.tools.tool_search import ToolSearchTool

        search = next((t for t in tools if isinstance(t, ToolSearchTool)), None)
        if search is None:
            # Do not replace a user tool sharing the preferred name.
            name = "search_tools"
            existing = {getattr(t, "name", "") for t in registry.values()}
            while name in existing:
                name = "_" + name
            search = ToolSearchTool(name=name, default_limit=3)
            registry.register(search)
        schemas[search.name] = search.schema()
        shared_state["discovery_search_name"] = search.name
        if automatic:
            # Session ID isolates concurrent conversations on one Agent. The
            # current registry and schema fingerprint invalidate stale entries.
            sessions = self._session_runtime_state.setdefault("discovery_sessions", {})
            session_key = str(getattr(self, "session_id", ""))
            cached = sessions.get(session_key, {})
            valid = {name: digest for name, digest in cached.items()
                     if name in schemas and digest == schema_fingerprint(schemas[name])}
            recent = list(valid)[-policy.reuse_tools:][::-1] if policy.reuse_tools else []
            resident = select_resident(tools, schemas, policy, core=DEFAULT_CORE_TOOLS,
                                       search_name=search.name, recent=recent, model=model)
            deferred = set(schemas) - resident
            shared_state["discovery_policy"] = policy
            shared_state["discovery_session_key"] = session_key
            shared_state["discovery_fingerprints"] = {name: schema_fingerprint(schema) for name, schema in schemas.items()}
            shared_state["discovery_cached"] = valid
        deferred.discard(search.name)
        shared_state[DEFERRED_NAMES_KEY] = deferred
        shared_state[LOADED_NAMES_KEY] = set()
        shared_state[SCHEMAS_BY_NAME_KEY] = schemas
        return deferred_index(
            tools, deferred, search_name=search.name,
            compact=automatic,
        )

    def select_step_schemas(
        self, tool_schemas: list[Any], shared_state: dict[str, Any]
    ) -> list[Any]:
        """The schemas this step advertises: core + everything loaded so far.

        Re-evaluated every iteration because the loaded set grows mid-run —
        a tool_search result on step 2 must be callable on step 3.
        """
        from shipit_agent.deferral import (
            DEFERRED_NAMES_KEY,
            LOADED_NAMES_KEY,
            select_schemas,
        )

        selected = select_schemas(
            [s for s in tool_schemas if (s.get("function") or {}).get("name") not in shared_state.get("discovery_hidden", set())],
            shared_state.get(DEFERRED_NAMES_KEY),
            shared_state.get(LOADED_NAMES_KEY),
        )
        policy = shared_state.get("discovery_policy")
        if policy is not None:
            # Persist only loaded definitions, bounded per session and globally.
            cache = dict(shared_state.get("discovery_cached", {}))
            fingerprints = shared_state.get("discovery_fingerprints", {})
            for schema in selected:
                name = (schema.get("function") or {}).get("name")
                if name in (shared_state.get(LOADED_NAMES_KEY) or set()) and name != shared_state.get("discovery_search_name"):
                    cache.pop(name, None)
                    cache[name] = fingerprints[name]
            cache = dict(list(cache.items())[-policy.reuse_tools:]) if policy.reuse_tools else {}
            sessions = self._session_runtime_state.setdefault("discovery_sessions", {})
            key = shared_state["discovery_session_key"]
            sessions.pop(key, None)
            sessions[key] = cache
            while len(sessions) > 32:
                sessions.pop(next(iter(sessions)))
        if not shared_state.get(DEFERRED_NAMES_KEY):
            return selected
        # Append new definitions after previously advertised ones. Inserting a
        # discovered schema into the middle of the prefix wastes cache reuse.
        by_name = {
            (schema.get("function") or {}).get("name"): schema
            for schema in selected
        }
        order = [name for name in shared_state.get("advertised_tool_order", []) if name in by_name]
        seen = set(order)
        order.extend(name for name in by_name if name not in seen)
        shared_state["advertised_tool_order"] = order
        return [by_name[name] for name in order]

    # ── cancellation ─────────────────────────────────────────────────────

    def cancel(self) -> None:
        """Request cancellation (thread-safe); the loop stops at its next checkpoint."""
        self._cancel_event.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel_event.is_set()

    # ── guardrails ───────────────────────────────────────────────────────

    def check_input(self, state: Any, user_prompt: str) -> tuple[str, str | None]:
        """Apply the input gate. Returns ``(prompt, refusal_or_None)``."""
        if self.guardrails is None:
            return user_prompt, None
        decision = self.guardrails.check_input(user_prompt)
        if decision.blocked:
            self.emit(
                state,
                "guardrail_triggered",
                f"Input blocked: {decision.reason}",
                stage="input",
                reason=decision.reason,
            )
            return user_prompt, f"Request blocked by guardrails: {decision.reason}"
        if decision.action == "redact" and decision.text:
            return decision.text, None
        return user_prompt, None

    def sanitize_output(self, state: Any, content: str) -> str:
        """Apply the output gate — redact secrets and PII before anyone sees them."""
        if self.guardrails is None or not content:
            return content
        decision = self.guardrails.check_output(content)
        if decision.action == "allow":
            return content
        self.emit(
            state,
            "guardrail_triggered",
            f"Output {decision.action}: {decision.reason}",
            stage="output",
            reason=decision.reason,
        )
        return (
            decision.text
            if decision.action == "redact"
            else f"Response withheld by guardrails: {decision.reason}"
        )

    def sanitize_tool_output(
        self, state: Any, tool_name: str, output: str
    ) -> tuple[str, bool]:
        """Sanitize a tool result. Returns ``(text, a_secret_was_redacted)``."""
        if self.guardrails is None or not output:
            return output, False
        sanitized = self.guardrails.check_tool_output(tool_name, output)
        if sanitized.action == "allow":
            return output, False
        self.emit(
            state,
            "guardrail_triggered",
            f"Tool output sanitized: {sanitized.reason}",
            stage="tool_output",
            tool=tool_name,
            reason=sanitized.reason,
        )
        return sanitized.text, "secret" in str(sanitized.reason or "").lower()

    def model_visible_tool_output(
        self,
        tool_result: Any,
        *,
        arguments: Any = None,
        seen: dict | None = None,
        limit_override: int | None = None,
    ) -> str:
        """Bound only the tool output copy sent back to the model.

        The canonical result remains complete for callers and traces. Head and
        tail retention keeps introductory context plus errors printed last.

        A tool called twice with the same arguments, returning byte-identical
        output, is sent back only once. The model already has that text in
        its context from the first call, and a message list is cumulative —
        every copy is re-sent on every subsequent turn, so the cost of a
        repeat is not the repeat, it is the repeat multiplied by the
        iterations that follow it. Observed on a real run: one MCP tool
        called four times with empty arguments returned the same 138,000
        characters each time, and a five-iteration turn spent 507,000 input
        tokens.

        Identity is required, not assumed: the tool still runs, and its
        output is compared. A tool whose answer changed says so in full.
        """
        raw_output = getattr(tool_result, "output", "") or ""
        if not isinstance(raw_output, str):
            # Block-shaped output (images) has no meaningful char budget and
            # stringifying it would feed the model "[{'type': 'image'…}]".
            return raw_output
        semantic_output = getattr(tool_result, "model_text", None)
        has_semantic_output = bool(
            isinstance(semantic_output, str) and semantic_output.strip()
        )
        output = semantic_output if has_semantic_output else raw_output
        name = str(getattr(tool_result, "name", "") or "")
        limit = (
            min(self.max_tool_output_chars, limit_override)
            if self.max_tool_output_chars > 0
            and limit_override is not None
            and limit_override > 0
            else limit_override
            if limit_override is not None
            else self.max_tool_output_chars
        )
        canonical_digest = hashlib.sha256(
            raw_output.encode("utf-8", "replace")
        ).hexdigest()
        persisted_path = ""
        if limit > 0 and len(raw_output) > limit:
            persisted_path = self._persist_tool_output(
                tool_result, output=raw_output, name=name, digest=canonical_digest
            )

        if seen is not None and len(output) >= _REPEAT_MIN_CHARS:
            key = (name, _arguments_key(arguments))
            if seen.get(key) == canonical_digest:
                metadata = getattr(tool_result, "metadata", None)
                if isinstance(metadata, dict):
                    metadata.update(
                        {
                            "repeat_of_earlier_call": True,
                            "omitted_output_chars": len(output),
                        }
                    )
                return (
                    f"[No new data. {name} was already called with exactly "
                    f"these arguments in this run and returned the same "
                    f"{len(output):,} characters, which are already in this "
                    f"conversation above.\n\n"
                    f"Calling it again unchanged will return this same "
                    f"message. Either answer from the result you already "
                    f"have, or call {name} with DIFFERENT arguments — a "
                    f"narrower query, a filter, or a specific id."
                    + (
                        f" The complete result is stored at {persisted_path}.]"
                        if persisted_path
                        else "]"
                    )
                )
            seen[key] = canonical_digest

        if has_semantic_output:
            metadata = getattr(tool_result, "metadata", None)
            if isinstance(metadata, dict):
                metadata.update(
                    {
                        "model_output_semantic": True,
                        "canonical_output_chars": len(raw_output),
                        "model_output_chars": len(output),
                    }
                )

        if limit <= 0 or len(output) <= limit:
            return output

        # Say what was removed and how to get it, not merely that something
        # was. "Shortened" leaves a model guessing whether it saw the
        # important part; a number and an instruction let it decide.
        omitted = len(output) - limit
        marker = (
            f"\n\n[... {omitted:,} of {len(output):,} characters omitted from "
            f"the middle. You are seeing the start and the end.\n"
            f"This tool returned more than fits in context. Do NOT call it "
            f"again unchanged — you will get this same extract. To see the "
            f"omitted part, use a narrower query, a filter, a page or a "
            f"specific id."
            + (
                f" The complete result is stored at {persisted_path}.]\n\n"
                if persisted_path
                else "]\n\n"
            )
        )
        # A tight budget still gets head and tail. The guidance is what is
        # dropped, not the data — an extract missing its end is the shape
        # that makes a model believe it saw the whole answer.
        if limit <= len(marker) + 32:
            marker = f"\n[... {omitted:,} of {len(output):,} chars omitted ...]\n"
        if limit <= len(marker) + 32:
            visible = output[:limit]
        else:
            content_budget = limit - len(marker)
            head_size = int(content_budget * 0.7)
            tail_size = content_budget - head_size
            visible = output[:head_size] + marker + output[-tail_size:]

        metadata = getattr(tool_result, "metadata", None)
        if isinstance(metadata, dict):
            metadata.update(
                {
                    "model_output_truncated": True,
                    "original_output_chars": len(output),
                    "model_output_chars": len(visible),
                    "omitted_output_chars": len(output) - len(visible),
                }
            )
        return visible

    def _persist_tool_output(
        self, tool_result: Any, *, output: str, name: str, digest: str
    ) -> str:
        """Persist a large sanitized result so truncation never loses access."""
        if not self.tool_output_dir:
            return ""
        from pathlib import Path

        safe_name = (
            "".join(
                char if char.isalnum() or char in "-_" else "_" for char in name
            ).strip("_")
            or "tool"
        )
        path = Path(self.tool_output_dir) / f"{safe_name}-{digest[:16]}.txt"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with path.open("x", encoding="utf-8", errors="replace") as file:
                    file.write(output)
            except FileExistsError:
                pass
        except OSError:
            return ""
        metadata = getattr(tool_result, "metadata", None)
        if isinstance(metadata, dict):
            metadata["persisted_output_path"] = str(path)
        return str(path)

    # ── the permission gate ──────────────────────────────────────────────

    def authorize(
        self, name: str, arguments: dict[str, Any], tool: Any
    ) -> PermissionResult | None:
        """Lockdown, then guardrail tool rules, then hooks and the engine.

        Order matters and is the security contract: lockdown outranks
        everything (no configuration set before a sensitive read may authorize
        an action after it), and a content-level guardrail deny beats any
        allow rule.
        """
        if self.lockdown.engaged:
            from shipit_agent.tools.contracts import contract_for

            if self.lockdown.blocks(name, read_only=contract_for(name, tool).read_only):
                return PermissionResult(
                    decision=PermissionDecision.DENY,
                    reason=self.lockdown.denial_reason(name),
                )

        if self.guardrails is not None:
            ceiling = getattr(self.guardrails, "max_tool_calls", 0)
            if ceiling and self._guarded_tool_calls >= ceiling:
                return PermissionResult(
                    decision=PermissionDecision.DENY,
                    reason=f"guardrail: tool-call ceiling ({ceiling}) reached",
                )
            guard = self.guardrails.check_tool(name, arguments)
            if guard is not None and not guard.allowed:
                return guard
            self._guarded_tool_calls += 1

        return authorize_tool(self.hooks, self.permissions, name, arguments, tool)

    def note_lockdown(
        self,
        state: Any,
        *,
        tool: str,
        arguments: dict[str, Any],
        output_metadata: dict[str, Any],
        redacted_secret: bool,
        iteration: int,
    ) -> None:
        """Evaluate a completed call for sensitivity; emit if it latched."""
        trigger = self.lockdown.observe(
            tool=tool,
            arguments=arguments,
            output_metadata=output_metadata,
            redacted_secret=redacted_secret,
        )
        if trigger is not None:
            self.emit(
                state,
                "lockdown_engaged",
                f"Lockdown: {trigger.reason}",
                reason=trigger.reason,
                tool=trigger.tool,
                source=trigger.source,
                iteration=iteration,
            )

    # ── the response ─────────────────────────────────────────────────────

    def heal(
        self, state: Any, response: LLMResponse, registry: Any, iteration: int
    ) -> None:
        """Promote tool calls a small model emitted as text, in place.

        The answer is searched first. If it yields nothing and the model
        produced *reasoning* but no answer and no calls, the reasoning is
        searched too: that shape means the model almost certainly wrote its
        call into its thinking, where nothing would otherwise find it.
        Reasoning heals the call only — the thinking text is left intact,
        since it was never going to be shown as the answer.
        """
        if not self.heal_tool_calls:
            return
        from shipit_agent.tool_healing import (
            heal_tool_calls,
            merge_split_calls,
            schemas_from_tools,
        )

        tools = list(registry.values())
        names = {tool.name for tool in tools}
        schemas = schemas_from_tools(tools)

        # A model can split one call across several native single-argument
        # invocations too, not only in prose. Reassemble those before they run;
        # the merge is a no-op unless the same tool was called with disjoint
        # keys. Text healing below is only for turns with NO structured call.
        if response.tool_calls:
            merged = merge_split_calls(list(response.tool_calls), schemas)
            if len(merged) != len(response.tool_calls):
                self.emit(
                    state,
                    "tool_call_healed",
                    f"Merged {len(response.tool_calls)} split call(s) into "
                    f"{len(merged)}",
                    tools=[c.name for c in merged],
                    iteration=iteration,
                    healed_from="split_merge",
                )
                response.tool_calls = merged
            return

        healed: list[Any] = []
        source = "content"
        if response.content:
            cleaned, healed = heal_tool_calls(response.content, names, schemas=schemas)
            if healed:
                response.content = cleaned
        if not healed and response.reasoning_content:
            _, healed = heal_tool_calls(
                response.reasoning_content, names, schemas=schemas
            )
            source = "reasoning"

        if healed:
            response.tool_calls = healed
            self.emit(
                state,
                "tool_call_healed",
                f"Promoted {len(healed)} text tool call(s)",
                tools=[c.name for c in healed],
                iteration=iteration,
                healed_from=source,
            )

    def should_nudge(
        self,
        response: LLMResponse,
        *,
        has_tools: bool,
        last: bool,
        tool_names: Sequence[str] = (),
    ) -> bool:
        """Is this an unparsed call shape, and may we re-prompt once?"""
        if not (self.heal_tool_calls and has_tools and not last):
            return False
        if self._nudges_used >= 1:
            return False
        raw_content = response.content or ""
        content = raw_content.strip()
        stalled = is_malformed_action_attempt(raw_content, allowed_names=tool_names)
        return stalled and content != self._last_nudged_text

    def record_nudge(self, response: LLMResponse) -> None:
        self._nudges_used += 1
        self._last_nudged_text = (response.content or "").strip()

    def should_force_text_recovery(
        self,
        response: LLMResponse,
        *,
        has_tools: bool,
        last: bool,
        tool_names: Sequence[str] = (),
    ) -> bool:
        """Stop advertising tools after a second malformed action attempt."""
        if not (self.heal_tool_calls and has_tools and not last):
            return False
        if self._nudges_used < 1:
            return False
        return is_malformed_action_attempt(
            response.content or "", allowed_names=tool_names
        )

    @staticmethod
    def malformed_attempt_context(response: LLMResponse) -> str:
        """Keep a failed text-form action useful without replaying its loop."""
        from shipit_agent.action_detection import is_degenerate_repetition

        content = response.content or ""
        if len(content) <= 2_048 and not is_degenerate_repetition(content):
            return content
        return (
            "[Malformed narrated tool attempt omitted: no structured tool call "
            "was emitted and the repeated prose was not executed.]"
        )

    def stable_final_content(self, state: Any, content: str) -> str:
        """Never expose a provider's degenerate repetition as a final answer."""
        from shipit_agent.action_detection import is_degenerate_repetition

        if not is_degenerate_repetition(content):
            return content
        self.metadata["incomplete_reason"] = "degenerate_repetition"
        observation = str(getattr(state, "last_observation", "") or "").strip()
        detail = f" Completed tool work: {observation}" if observation else ""
        self.emit(
            state,
            "model_output_recovered",
            "Stopped a repetitive model response",
            reason="degenerate_repetition",
        )
        return (
            "I stopped the response because the model became stuck repeating "
            "an attempted action; that repeated text was not executed."
            f"{detail} No additional result is verified. Please retry this request."
        )

    # Reprompt-on-failure, in the spirit of production tool-runners: name why
    # the attempt did not count (the tool name or its arguments were mistyped
    # or written as prose, so nothing ran) and tell the model exactly how to
    # recover. Kept as a cross-provider user message rather than a synthetic
    # tool-response: shipit's Message model does not carry a tool_call_id to
    # pair a fabricated failure result against, and an unpaired tool message is
    # rejected by strict providers (Bedrock-Anthropic). The wording gives the
    # same self-correction signal without that fragility.
    NUDGE_TEXT = (
        "You attempted a tool call, but it was not emitted as a structured "
        "call — the tool name or its arguments were likely mistyped or written "
        "as prose, so nothing ran. Re-issue it now as a real structured call "
        "with the exact tool name and correctly-typed arguments, or, if no tool "
        "is needed, give your final answer directly. Do not describe the call "
        "in text."
    )

    #: How many times a turn under ``require_tool_call`` (force-any-tool) may be
    #: re-prompted to emit the mandatory call before the runtime gives up and
    #: lets the model answer from what it has. Without a cap the forced-tool
    #: retry re-fires every iteration to ``max_iterations`` — the visible
    #: "Retrying required tool use" loop. Two attempts is enough for a model
    #: that merely stumbled; a model that will not call it never will.
    MAX_FORCE_ANY_RETRIES = 2

    #: How many times stop hooks may send one run back to work. A hook that
    #: never relents must not turn every answer into ``max_iterations`` steps.
    MAX_STOP_CONTINUATIONS = 3

    def apply_stop_hooks(
        self, state: Any, response: LLMResponse, iteration: int, shared_state: dict
    ) -> bool:
        """Ask the stop hooks whether the run may finish. True means keep going:
        the reason has been added to the conversation and an event emitted."""
        hooks = getattr(self, "hooks", None)
        if hooks is None or not getattr(hooks, "stop", None):
            return False
        if iteration >= self.max_iterations:
            return False
        used = int(shared_state.get("stop_continuations", 0) or 0)
        if used >= self.MAX_STOP_CONTINUATIONS:
            if not shared_state.get("stop_cap_reported"):
                shared_state["stop_cap_reported"] = True
                self.emit(
                    state,
                    "stop_unresolved",
                    "Stop hooks still objected; finishing after the continuation limit",
                    iteration=iteration,
                    continuations=used,
                )
            return False
        try:
            reason = hooks.run_stop(response.content or "")
        except Exception as exc:  # a broken hook must not break the run
            self.emit(
                state,
                "stop_hook_error",
                f"Stop hook failed: {type(exc).__name__}",
                iteration=iteration,
            )
            return False
        if not reason:
            return False
        shared_state["stop_continuations"] = used + 1
        if response.content:
            state.messages.append(Message(role="assistant", content=response.content))
        state.messages.append(
            Message(
                role="user",
                content=(
                    f"Not done yet: {reason}\nKeep working until this is resolved, "
                    "then give your answer."
                ),
                metadata={"internal": True, "kind": "stop_hook"},
            )
        )
        self.emit(
            state,
            "stop_blocked",
            f"Kept going: {reason}",
            reason=reason,
            iteration=iteration,
            continuation=used + 1,
        )
        return True

    # ── usage ────────────────────────────────────────────────────────────

    def track_usage(self, state: Any, response: LLMResponse, iteration: int) -> None:
        """Accumulate tokens and emit a running total for the live footer."""
        self._last_finish_reason = response.metadata.get("finish_reason")
        from shipit_agent.llms.usage import input_token_counts, has_complete_token_usage
        uncached, read, write, total_input = input_token_counts(response)
        self._total_uncached_input += uncached
        route = response.metadata.get("route") if isinstance(response.metadata, dict) else None
        self._bucket((route or {}).get("model") or getattr(self.llm, "model", None),
                     uncached, response.usage.get("completion_tokens", 0), read, write)
        self._total_context_input += total_input
        purpose = "compaction" if response.metadata.get("purpose") == "context_compaction" else "main"
        self._purpose_usage[purpose] += total_input + response.usage.get("completion_tokens", 0)
        self._completed_model_calls += 1
        self._usage_reports += int(bool(response.usage))
        self._complete_usage_reports += int(has_complete_token_usage(response))
        self._cache_counters_reported |= any(
            key in response.usage for key in ("cache_read_input_tokens", "cache_creation_input_tokens")
        )
        for key in (
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
        ):
            self._total_usage[key] += response.usage.get(key, 0)
        spent = total_input + response.usage.get("completion_tokens", 0)
        discarded = response.metadata.get("discarded_usage")
        if isinstance(discarded, dict):
            spent += self._count_discarded(discarded)
        session = self._session_runtime_state
        session["session_tokens"] = session.get("session_tokens", 0) + spent
        if not has_complete_token_usage(response):
            session["session_usage_complete"] = False
        self.emit(
            state,
            "usage_tick",
            "Usage updated",
            usage=dict(self._total_usage),
            iteration=iteration,
        )

    def _count_discarded(self, usage: dict[str, Any]) -> int:
        """Book a routed step's thrown-away call into totals and budgets.

        Deliberately not into calibration: that learns only from the call
        whose prompt it estimated, and this one was a different model.
        """
        from shipit_agent.llms.usage import input_token_counts

        counted = {key: int(value) for key, value in usage.items()
                   if isinstance(value, int) and not isinstance(value, bool)}
        uncached, read, write, total_input = input_token_counts(LLMResponse(usage=counted))
        tokens = total_input + counted.get("completion_tokens", 0)
        self._total_uncached_input += uncached
        self._bucket(usage.get("model"), uncached, counted.get("completion_tokens", 0), read, write)
        self._total_context_input += total_input
        self._purpose_usage["main"] += tokens
        self._discarded_tokens += tokens
        for key in ("prompt_tokens", "completion_tokens", "total_tokens",
                    "cache_read_input_tokens", "cache_creation_input_tokens"):
            self._total_usage[key] += counted.get(key, 0)
        return tokens

    def _bucket(self, model: Any, uncached: int, output: int, read: int, write: int) -> None:
        if not model:
            return
        bucket = self._usage_by_model.setdefault(
            str(model), {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0})
        bucket["input"] += uncached
        bucket["output"] += output
        bucket["cache_read"] += read
        bucket["cache_write"] += write

    def budget_stop_message(self) -> str:
        scope = "session" if str(self.metadata.get("incomplete_reason") or "").startswith(
            "session") else "task"
        policy = "session token budget" if scope == "session" else "task token budget policy"
        return (f"Stopped by the {policy}. Work is incomplete; "
                "completed tool results remain in the session.")

    def task_budget_reached(self, state: Any, iteration: int) -> bool:
        """Between steps: stop if the run's or the session's budget is spent."""
        return self._task_budget_hit(state, iteration) or self._session_budget_hit(
            state, iteration)

    def _session_budget_hit(self, state: Any, iteration: int) -> bool:
        limit = self.metadata.get("max_session_tokens")
        if limit is None:
            return False
        session = self._session_runtime_state
        if session.get("session_usage_complete", True) is False:
            self.metadata["incomplete_reason"] = "session_budget_usage_unavailable"
            self.emit(state, "budget_unavailable",
                      "Provider did not report complete usage; stopping the budgeted session",
                      limit=limit, iteration=iteration, scope="session")
            return True
        used = session.get("session_tokens", 0)
        if used < limit:
            return False
        self.metadata["incomplete_reason"] = "session_token_budget"
        self.emit(state, "budget_exhausted", "Session token budget reached", limit=limit,
                  used=used, iteration=iteration, enforcement="between_steps", scope="session")
        return True

    def _task_budget_hit(self, state: Any, iteration: int) -> bool:
        limit = self.metadata.get("max_task_tokens")
        used = self._total_context_input + self._total_usage.get("completion_tokens", 0)
        if limit is not None and self._complete_usage_reports < self._completed_model_calls:
            self.metadata["incomplete_reason"] = "task_budget_usage_unavailable"
            self.emit(state, "budget_unavailable", "Provider did not report complete usage; stopping budgeted work",
                      limit=limit, iteration=iteration)
            return True
        if limit is None or used < limit:
            return False
        self.metadata["incomplete_reason"] = "task_token_budget"
        self.emit(state, "budget_exhausted", "Task token budget reached",
                  limit=limit, used=used, iteration=iteration, enforcement="between_steps")
        return True

    def calibrate_from_completion(
        self, sent_messages: Sequence[Message], response: LLMResponse
    ) -> None:
        """Teach the token calibrator from one MAIN completion.

        ``sent_messages`` is the exact view that was sent — the compacted
        messages, not the full history — so the estimate matches what the
        provider actually tokenised. The estimate uses the SAME formula the
        compaction trigger does (messages + fixed prefix) so the learned factor
        is applied to the number it was measured against. ``actual`` respects
        each adapter's cache-counter semantics: native Anthropic separates
        cached input, whereas OpenAI and LiteLLM include it in prompt tokens.
        Call ONLY for real model steps — never the summary completion,
        whose prompt is a different shape.
        """
        from shipit_agent.compaction import count_messages

        from shipit_agent.llms.usage import input_token_counts
        actual = input_token_counts(response)[3]
        if actual <= 0:
            return
        # A router answers for several models; learn for the one that ran.
        route = response.metadata.get("route") if isinstance(response.metadata, dict) else None
        model = (route or {}).get("model") or getattr(self.llm, "model", None)
        estimated = count_messages(sent_messages, model) + self._fixed_prefix_tokens
        self.token_calibrator.observe(model, estimated, actual)

    # ── compaction ───────────────────────────────────────────────────────

    def compactor(self) -> Any:
        if self._compactor_instance is None:
            from shipit_agent.compaction import Compactor

            self._compactor_instance = Compactor(
                llm=self.llm,
                model=getattr(self.llm, "model", None),
                context_window_tokens=self.context_window_tokens,
                fixed_prefix_tokens=self._fixed_prefix_tokens,
                calibrator=self.token_calibrator,
            )
            self._session_runtime_state["compactor"] = self._compactor_instance
        return self._compactor_instance

    def account_request_overhead(self, tool_schemas: Sequence[Any]) -> None:
        """Include the current tool-schema payload in compaction decisions.

        Schemas are transmitted outside ``messages`` and can consume thousands
        of tokens. Calculate them on every cycle because deferred loading and
        the final tool-free synthesis step change the advertised set. A caller's
        explicit ``fixed_prefix_tokens`` remains an additive reserve.
        """
        import json

        from shipit_agent.compaction import content_tokens

        model = getattr(self.llm, "model", None)
        try:
            rendered = json.dumps(list(tool_schemas), sort_keys=True, default=str)
        except (TypeError, ValueError):
            rendered = repr(list(tool_schemas))
        schema_tokens = content_tokens(rendered, model) if tool_schemas else 0
        self._schema_prefix = rendered
        self._fixed_prefix_tokens = self._configured_fixed_prefix_tokens + schema_tokens
        if self._compactor_instance is not None:
            self._compactor_instance.fixed_prefix_tokens = self._fixed_prefix_tokens

    def fit_provider_request(
        self,
        state: Any,
        messages: Sequence[Message],
        *,
        iteration: int,
    ) -> list[Message]:
        """Final hard fit of the exact message view before provider dispatch."""
        from shipit_agent.context_fit import fit_messages

        compactor = self.compactor()
        budget = compactor.limits.input_budget

        def fits(candidate: Sequence[Message]) -> bool:
            return compactor.estimated_prompt_tokens(candidate) <= budget

        fitted, stats = fit_messages(messages, fits=fits)
        from shipit_agent.compaction import content_tokens
        import hashlib
        model = getattr(self.llm, "model", None)
        for message in fitted:
            category = "system" if message.role == "system" else "tool_results" if message.role == "tool" else "conversation"
            self._request_estimates[category] += content_tokens(message.content or "", model)
        self._request_estimates["schemas"] += max(0, self._fixed_prefix_tokens - self._configured_fixed_prefix_tokens)
        prefix = self._schema_prefix + repr([m.content for m in fitted if m.role == "system"])
        digest = hashlib.sha256(prefix.encode()).hexdigest()
        fingerprints = self._session_runtime_state.setdefault("request_prefixes", {})
        previous = fingerprints.pop(self.session_id, None)
        self._prefix_changes += int(previous is not None and previous != digest)
        fingerprints[self.session_id] = digest
        while len(fingerprints) > 32:
            fingerprints.pop(next(iter(fingerprints)))
        if stats["dropped_messages"] or stats["reduced_messages"]:
            self.emit(
                state,
                "context_compacted",
                "Final request fitted to the provider context window",
                mode="hard_fit",
                before=len(messages),
                after=len(fitted),
                budget_tokens=budget,
                estimated_tokens=compactor.estimated_prompt_tokens(fitted),
                iteration=iteration,
                **stats,
            )
        return fitted

    def compact(
        self,
        state: Any,
        messages: list[Message],
        iteration: int,
        shared_state: dict[str, Any] | None = None,
    ) -> list[Message]:
        """Compact if needed, emitting a notice. Returns what to send.

        The full history in ``state.messages`` never shrinks — compaction is
        a per-request view. The latest checkpoint is REUSED as long as its
        view still fits: without that reuse, every step past the threshold
        would write a brand-new summary (one extra completion per step,
        uncounted and identical). A fresh summary is only written when the
        replayed view itself outgrows the budget again.

        When a fresh summary IS written, the read-before-edit gate is reset:
        a file whose contents were just summarized out of context is no
        longer something the model can see, so editing it against a
        reconstructed ``old_text`` would be a silent staleness bug. Clearing
        the gate forces a cheap re-read (the file is often still in the hot
        tail) before the next edit is allowed.
        """
        if self.context_window_tokens < 0:
            return messages
        compactor = self.compactor()
        latest = compactor.latest()
        if latest is not None:
            view = latest.replay(messages)
            if not compactor.needs_compaction(view):
                return view
        elif not compactor.needs_compaction(messages):
            return messages
        self.emit(
            state,
            "context_compaction_started",
            "Context automatically compacting",
            before=len(messages),
            estimated_tokens=compactor.estimated_prompt_tokens(messages),
            budget_tokens=compactor.limits.input_budget,
            iteration=iteration,
        )
        checkpoint = compactor.compact(messages)
        if checkpoint is None:
            return latest.replay(messages) if latest is not None else messages
        self._reset_read_gate(shared_state)
        # The summary was a real completion — count its tokens.
        summary_usage = dict(getattr(compactor, "last_summary_usage", None) or {})
        if summary_usage:
            self.track_usage(state, LLMResponse(usage=summary_usage, metadata={
                **getattr(compactor, "last_summary_metadata", {}),
                "purpose": "context_compaction",
            }), iteration)
        replayed = checkpoint.replay(messages)
        self.emit(
            state,
            "context_compacted",
            "Older turns condensed to stay within the context window",
            before=len(messages),
            after=len(replayed),
            saved_tokens=checkpoint.saved_tokens,
            checkpoints=len(compactor.checkpoints),
            iteration=iteration,
        )
        return replayed

    def _build_run_summary(self, state: Any) -> dict[str, Any]:
        """A closing accounting of the run — iterations, tools, tokens, cost.

        Everything here was already tracked; this consolidates it into one
        artifact a UI can print as the run's final line. Cost is a best-effort
        estimate from the model's public pricing (``0`` / unknown when the
        model isn't in the table), never a billing figure.
        """
        usage = dict(self._total_usage)
        tool_results = list(getattr(state, "tool_results", []) or [])
        events = list(getattr(state, "events", []) or [])
        tool_calls = sum(1 for e in events if e.type == "tool_called")
        compactions = sum(1 for e in events if e.type == "context_compacted")
        iterations = max(
            (e.payload.get("iteration", 0) for e in events if e.type == "step_started"),
            default=0,
        )
        cost_usd: float | None = None
        model = getattr(self.llm, "model", None)
        if len(self._usage_by_model) > 1:
            # Several models served this run: price each at its own rate.
            try:
                from shipit_agent.costs.tracker import CostTracker

                tracker = CostTracker()
                cost_usd = round(sum(
                    tracker.calculate_cost(name, b["input"], b["output"],
                                           cache_read_tokens=b["cache_read"],
                                           cache_write_tokens=b["cache_write"])
                    for name, b in self._usage_by_model.items()), 6)
            except (KeyError, TypeError, ValueError):
                # A malformed pricing entry must not fail the run summary.
                cost_usd = None
        elif model:
            try:
                from shipit_agent.costs.tracker import CostTracker

                cost_usd = round(
                    CostTracker().calculate_cost(
                        str(model),
                        self._total_uncached_input,
                        usage.get("completion_tokens", 0),
                        cache_read_tokens=usage.get("cache_read_input_tokens", 0),
                        cache_write_tokens=usage.get("cache_creation_input_tokens", 0),
                    ),
                    6,
                )
            except Exception:
                cost_usd = None
        total = usage.get("total_tokens", 0)
        cache_read = max(0, int(usage.get("cache_read_input_tokens", 0) or 0))
        cache_creation = max(0, int(usage.get("cache_creation_input_tokens", 0) or 0))
        cache_eligible_input = self._total_context_input
        cache_hit_ratio = (
            round(cache_read / cache_eligible_input, 4) if cache_eligible_input else 0.0
        )
        cost_str = f", ${cost_usd:.4f}" if cost_usd else ""
        return {
            "headline": (
                f"Run finished: {iterations} iterations, {tool_calls} tool "
                f"calls, {total:,} tokens{cost_str}"
            ),
            "iterations": iterations,
            "tool_calls": tool_calls,
            "tool_results": len(tool_results),
            "compactions": compactions,
            "usage": usage,
            "usage_diagnostics": {
                "estimated_main_request_content_tokens": dict(self._request_estimates),
                "reported_tokens_by_purpose": dict(self._purpose_usage),
                "prefix_changes": self._prefix_changes,
                "cache_counters_reported": self._cache_counters_reported,
                "task_token_limit": self.metadata.get("max_task_tokens"),
                "session_token_limit": self.metadata.get("max_session_tokens"),
                "session_tokens_used": self._session_runtime_state.get("session_tokens", 0),
                "discarded_tokens": self._discarded_tokens,
                "tokens_by_model": {name: dict(b) for name, b in self._usage_by_model.items()},
                "budget_enforcement": "between_steps",
                "provider_usage_available": bool(self._usage_reports),
                "budget_usage_complete": self._complete_usage_reports == self._completed_model_calls,
                "llm_retry_events": sum(e.type == "llm_retry" for e in events),
            },
            "cache": {
                "read_input_tokens": cache_read,
                "creation_input_tokens": cache_creation,
                "eligible_input_tokens": cache_eligible_input,
                "hit_ratio": cache_hit_ratio,
            },
            "estimated_cost_usd": cost_usd,
            "gave_up": bool(self.metadata.get("gave_up")),
            "completion_status": (
                "incomplete" if self.metadata.get("incomplete_reason")
                or self.metadata.get("gave_up")
                or getattr(self, "_last_finish_reason", None) in {"length", "max_tokens", "content_filter"}
                else "finished"
            ),
            "finish_reason": getattr(self, "_last_finish_reason", None),
            "tool_discovery": self.discovery_checkpoint(),
            "incomplete_reason": self.metadata.get("incomplete_reason"),
            "failed_tool_results": sum(bool(r.is_error) for r in tool_results),
            "recovery_events": sum(e.type in {"llm_retry", "tool_call_healed", "model_output_recovered"} for e in events),
        }

    @staticmethod
    def _reset_read_gate(shared_state: dict[str, Any] | None) -> None:
        """Drop the read-before-edit record after a compaction.

        ``read_file`` records which paths were read (and their mtimes) so
        ``edit_file`` can refuse a write against contents the model never
        saw. After compaction those reads may be summarized away, so the
        record is stale — clearing it makes the next edit re-read first.

        The paths that WERE read are remembered so the loop can re-inject the
        most recent one as a fresh read (see ``regrounding_message``): after
        compaction the model should work from the code, not a prose summary
        of it.
        """
        if not isinstance(shared_state, dict):
            return
        shared_state["compaction_reread_hint"] = list(
            shared_state.get("read_files", [])
        )[-3:]
        shared_state["read_files"] = []
        shared_state["read_file_mtimes"] = {}

    @staticmethod
    def regrounding_messages(shared_state: dict[str, Any] | None) -> list[Message]:
        """Fresh reads of the files a just-fired compaction summarized away.

        Re-establish file state after compaction rather than leaving the
        model with a description of code. The most recently read
        files (up to 3) are re-read from disk and returned as tool messages,
        so the post-compaction context holds current contents, not prose.
        Consumes the hint so it fires once per compaction. Best-effort: an
        unreadable or vanished file is simply skipped.
        """
        if not isinstance(shared_state, dict):
            return []
        hints = shared_state.pop("compaction_reread_hint", None) or []
        messages: list[Message] = []
        read_files = list(shared_state.get("read_files", []))
        mtimes = dict(shared_state.get("read_file_mtimes", {}))
        for path_str in hints:
            try:
                from pathlib import Path

                path = Path(path_str)
                if not path.is_file():
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
                if len(text) > 40_000:
                    text = text[:40_000] + "\n…[truncated]"
                messages.append(
                    Message(
                        role="user",
                        content=(
                            f"[re-grounding after compaction] Current contents "
                            f"of {path.name}:\n{text}"
                        ),
                        metadata={
                            "regrounding": True,
                            "internal": True,
                            "path": path_str,
                        },
                    )
                )
                # Restore the read-gate for the re-read file so an edit can
                # follow without another explicit read.
                if path_str not in read_files:
                    read_files.append(path_str)
                try:
                    mtimes[path_str] = path.stat().st_mtime_ns
                except OSError:
                    pass
            except Exception:
                continue
        if messages:
            shared_state["read_files"] = read_files
            shared_state["read_file_mtimes"] = mtimes
        return messages

    # ── shared tool state ────────────────────────────────────────────────

    def _make_subagent_sink(self, state: Any) -> Any:
        """A callback children report through, so their work is visible.

        A child's events are re-emitted on the parent's stream wrapped in
        ``sub_agent_event``, carrying which child produced them. They are not
        re-emitted under their own types: a renderer must be able to tell the
        parent's work from a child's, or a nested read_file looks like the
        parent read a file.
        """

        def sink(event: Any, label: str, task: str) -> None:
            self.emit(
                state,
                "sub_agent_event",
                f"[{label}] {event.message}",
                agent=label,
                task=task,
                inner_type=event.type,
                inner=dict(event.payload),
            )

        return sink

    def note_artifacts(self, state: Any, tool_name: str, result: Any) -> None:
        """Emit a card for each file a tool left behind.

        A run that produces something — a page, a workbook, a document — has
        made a *thing*, and the thing is usually the point. Surfacing it as
        its own event is what lets a UI show "Q2 Kickoff Brief · Doc" instead
        of a path buried in tool output.

        Only paths a tool declared in its metadata are reported: scraping them
        out of free text would invent artifacts from any string with a slash.
        """
        # Reading a file does not produce one. `read_file` reports the path it
        # read, and treating that as an artifact turns every read into a card
        # for a file the user already had.
        from shipit_agent.tools.contracts import contract_for

        if contract_for(tool_name).read_only:
            return

        metadata = dict(getattr(result, "metadata", None) or {})
        for path in _declared_paths(metadata):
            self.emit(
                state,
                "artifact_created",
                f"Artifact: {path.name}",
                tool=tool_name,
                path=str(path),
                title=metadata.get("title") or path.stem.replace("_", " ").title(),
                kind=_artifact_kind(path),
            )

    def note_connection_request(
        self, state: Any, tool_name: str, metadata: Any
    ) -> None:
        """Surface a connection the agent asked for as its own event.

        A missing connection is a decision for the *user*, exactly like an
        approval — so it gets an event a UI can draw a card from rather than
        living only inside one tool result's text. Shared by both loops, for
        the usual reason: every past divergence between them was a bug.
        """
        data = dict(metadata or {})
        if not data.get("requested") or not data.get("connection_id"):
            return
        self.emit(
            state,
            "connection_requested",
            f"Connection needed: {data.get('title') or data['connection_id']}",
            tool=tool_name,
            connection_id=data["connection_id"],
            title=data.get("title") or data["connection_id"],
            reason=data.get("reason", ""),
            auth=data.get("auth", "unknown"),
        )

    def build_shared_state(self, registry: Any, state: Any = None) -> dict[str, Any]:
        """What every tool can see. Identical in both loops, by construction."""
        from shipit_agent.connections import ConnectionRegistry
        from shipit_agent.tools.helpers import describe_tool_capability
        from shipit_agent.tools.connections.connections_tool import (
            REGISTRY_STATE_KEY as CONNECTIONS_KEY,
        )
        from shipit_agent.tools.sub_agent.sub_agent_tool import (
            DEPTH_STATE_KEY,
            EVENT_SINK_KEY,
            PARENT_STATE_KEY,
        )

        self.connections = ConnectionRegistry(
            credential_store=self.credential_store,
            tools=registry.values(),
            mcps=self.mcps,
        )
        resolved_connections = self.connections.all()
        return {
            "available_tools": [
                describe_tool_capability(
                    tool,
                    connections=resolved_connections,
                )
                for tool in registry.values()
            ],
            "memory_store": self.memory_store,
            "credential_store": self.credential_store,
            CONNECTIONS_KEY: self.connections,
            # Publishing the control plane is what makes delegation
            # non-escalating: a child is built from the parent's own
            # permissions, approvals and guardrails, never fresh ones.
            PARENT_STATE_KEY: {
                "tools": list(registry.values()),
                "permissions": self.permissions,
                "approvals": self.approvals,
                "guardrails": self.guardrails,
                "project_root": self.metadata.get("project_root", "."),
            },
            DEPTH_STATE_KEY: self.metadata.get(DEPTH_STATE_KEY, 0),
            EVENT_SINK_KEY: self._make_subagent_sink(state),
            "artifact_workspace_root": self.metadata.get(
                "artifact_workspace_root", ".shipit_workspace/artifacts"
            ),
            "workspace_root": self.metadata.get("workspace_root", ".shipit_workspace"),
        }

    # ── finishing ────────────────────────────────────────────────────────

    def surface_give_up(self, tool_results: list[Any]) -> None:
        """Promote a declared stop from a tool result to run metadata."""
        gave_up = next((r for r in tool_results if r.metadata.get("gave_up")), None)
        if gave_up is not None:
            self.metadata["gave_up"] = True
            self.metadata["give_up_reason"] = gave_up.metadata.get("give_up_reason", "")
            self.metadata["give_up_needs"] = gave_up.metadata.get("give_up_needs", [])

    def close_mcps(self) -> None:
        """Close every attached MCP transport, swallowing close errors.

        Must run even when the loop raises, or a failed run leaks live
        subprocesses and sockets.
        """
        for mcp in self.mcps:
            close = getattr(mcp, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
