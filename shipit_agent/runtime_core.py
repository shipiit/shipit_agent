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
import re

import threading
from typing import Any

from shipit_agent.llms.base import LLMResponse
from shipit_agent.models import Message
from shipit_agent.permissions import (
    PermissionDecision,
    PermissionResult,
    authorize_tool,
)

__all__ = ["RuntimeCore", "INTENT_MARKERS", "is_intent_without_action"]

# Short, action-narrating text with no substance — the stall shape. Kept as a
# heuristic only because not every model will call `give_up`; a model that
# does is always preferred.
INTENT_MARKERS = (
    "let me",
    "i will",
    "i'll",
    "i am going to",
    "i'm going to",
    "first, i",
    "next, i",
    "now i",
    "going to use",
    "going to call",
    "let's use",
)


#: A sentence ends at one of these followed by whitespace or the end.
_SENTENCE_END = re.compile(r"[.!?](?:\s|$)")


def _sentence_count(text: str) -> int:
    return len([part for part in _SENTENCE_END.split(text) if part.strip()])


def is_intent_without_action(text: str | None) -> bool:
    """Did the model narrate an action and then not take one?

    A stall is a **bare announcement**: the model said it was about to act,
    said nothing else, and stopped. That shape is what the nudge exists to
    recover, and it is the shape this recognises — by structure, not by
    matching more phrases.

    Two things disqualify a response, both structural:

    - **It ends in a question.** A model asking the user something has
      finished its turn on purpose. Nudging there asks it to justify a
      failure that did not happen.
    - **It says more than one thing.** An announcement surrounded by several
      sentences of substance is a complete reply that happens to contain a
      turn of phrase, not a model that stopped short.

    Both come from one observed failure. A plain greeting — *"Not much, just
    standing by and ready to work. How can I help you today? If you need me
    to look into a specific threat actor ... just let me know."* — matched on
    "let me" inside "let me know". The runtime nudged; the model replied *"I
    apologize; I didn't have a task to perform in my previous response, so no
    tool was necessary"*; and both halves were concatenated into what the
    user read.

    Adding "let me know" to a list of exceptions would have fixed that
    sentence and nothing else — the next phrasing would need another entry.
    Multi-sentence replies and questions are the general case that greeting
    belonged to.
    """
    stripped = (text or "").strip().lower()
    if not stripped:
        return False
    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    tail = lines[-1]
    announced_plan = any(marker in stripped for marker in INTENT_MARKERS)
    next_action_tail = tail.startswith(("first,", "next,", "now ", "starting "))
    if announced_plan and next_action_tail and not tail.endswith("?"):
        return True
    if len(stripped) > 300:
        return False
    if stripped.endswith("?"):
        return False
    if _sentence_count(stripped) > 1:
        return False
    return any(marker in stripped for marker in INTENT_MARKERS)


def _collapse_repeated_lines(text: str) -> tuple[str, int]:
    """Bound exact line repetition from a degenerate model completion.

    Open-weight models can repeat the same reasoning fragment until their
    output limit. Keeping that text makes the next request larger and exposes
    internal marker noise to the user. Two copies are retained so ordinary
    prose and deliberately repeated formatting are not rewritten; only the
    third and later exact non-empty lines are removed.
    """
    if not text:
        return text, 0
    removed_chars = 0

    def _bound_character_run(match: re.Match[str]) -> str:
        nonlocal removed_chars
        removed_chars += len(match.group(0)) - 2
        return match.group(1) * 2

    text = re.sub(r"([^\s])\1{63,}", _bound_character_run, text)

    def _bound_periodic_token(match: re.Match[str]) -> str:
        nonlocal removed_chars
        value = match.group(0)
        period = (value + value).find(value, 1)
        if period <= 0 or period >= len(value) or len(value) // period < 5:
            return value
        bounded = value[:period] * 2
        removed_chars += len(value) - len(bounded)
        return bounded

    # Markup corruption often arrives as one whitespace-free periodic token.
    # Detect its actual period rather than enumerating HTML/XML fragments.
    text = re.sub(r"\S{128,}", _bound_periodic_token, text)

    # Collapse adjacent repeated token sequences (including malformed markup)
    # without knowing their content. This catches shapes such as a repeated
    # HTML fragment or a multi-token phrase on one line.
    tokens = re.findall(r"\S+\s*", text)
    if len(tokens) >= 5:
        compacted_tokens: list[str] = []
        index = 0
        while index < len(tokens):
            matched = False
            max_width = min(12, (len(tokens) - index) // 5)
            for width in range(1, max_width + 1):
                unit = tokens[index : index + width]
                if any(
                    tokens[index + repeat * width : index + (repeat + 1) * width]
                    != unit
                    for repeat in range(1, 5)
                ):
                    continue
                repeats = 5
                while (
                    index + (repeats + 1) * width <= len(tokens)
                    and tokens[index + repeats * width : index + (repeats + 1) * width]
                    == unit
                ):
                    repeats += 1
                compacted_tokens.extend(unit)
                compacted_tokens.extend(unit)
                removed_chars += sum(
                    len(token)
                    for token in tokens[index + 2 * width : index + repeats * width]
                )
                index += repeats * width
                matched = True
                break
            if not matched:
                compacted_tokens.append(tokens[index])
                index += 1
        text = "".join(compacted_tokens)
    # Degenerate generations are often one giant line of repeated sentences.
    # Bound exact sentence recurrence before the line pass. This is based on
    # output structure, not provider, language, tool name, or known phrases.
    sentence_counts: dict[str, int] = {}
    for match in re.finditer(r"[^.!?\n]+[.!?](?:\s+|$)", text):
        key = " ".join(match.group(0).split()).casefold()
        sentence_counts[key] = sentence_counts.get(key, 0) + 1
    sentence_seen: dict[str, int] = {}

    def _bound_sentence(match: re.Match[str]) -> str:
        nonlocal removed_chars
        value = match.group(0)
        key = " ".join(value.split()).casefold()
        sentence_seen[key] = sentence_seen.get(key, 0) + 1
        if sentence_counts.get(key, 0) >= 5 and sentence_seen[key] > 2:
            removed_chars += len(value)
            return ""
        return value

    text = re.sub(r"[^.!?\n]+[.!?](?:\s+|$)", _bound_sentence, text)

    seen: dict[str, int] = {}
    kept: list[str] = []
    removed = 0
    blank_run = 0
    for line in text.splitlines(keepends=True):
        key = line.strip()
        if not key:
            blank_run += 1
            if blank_run > 2:
                removed += 1
                continue
        else:
            blank_run = 0
            seen[key] = seen.get(key, 0) + 1
            if seen[key] > 2:
                removed += 1
                continue
        kept.append(line)
    return "".join(kept).strip(), removed + removed_chars


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

#: Below this, the stub costs more than the payload it replaces.
_EVICT_MIN_CHARS = 1_000

_EVICTED_NOTICE = (
    "[This tool call completed in an earlier turn; its results are no longer "
    "available. The call and its arguments are above — call it again if you "
    "need the data.]"
)


def evict_prior_tool_outputs(
    messages: list[Message], *, min_chars: int = _EVICT_MIN_CHARS
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
            and len(message.content or "") >= min_chars
        ):
            evicted.append(
                Message(
                    role="tool",
                    name=message.name,
                    content=_EVICTED_NOTICE,
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


def _parameters_of(schema: Any) -> dict[str, Any]:
    """Return a parameters object from supported function-schema shapes."""
    if not isinstance(schema, dict):
        return {}
    if isinstance(schema.get("parameters"), dict):
        return schema["parameters"]
    function = schema.get("function")
    if isinstance(function, dict) and isinstance(function.get("parameters"), dict):
        return function["parameters"]
    if isinstance(schema.get("properties"), dict):
        return schema
    return {}


def _missing_required(arguments: dict[str, Any], schema: Any) -> list[str]:
    """Return missing or empty schema-required properties in schema order."""
    required = _parameters_of(schema).get("required")
    if not isinstance(required, list):
        return []
    missing: list[str] = []
    for key in required:
        if not isinstance(key, str):
            continue
        value = arguments.get(key)
        if key not in arguments or value is None:
            missing.append(key)
        elif isinstance(value, (str, list, dict, tuple, set)) and not value:
            missing.append(key)
    return missing



def _bounded_key(key: Any) -> str:
    """A garbage argument name, short enough to quote back at the model."""
    text = " ".join(str(key).split())
    return text if len(text) <= 40 else text[:40].rstrip() + "…"


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
        self.max_tool_output_chars = int(options.get("max_tool_output_chars", 0) or 0)
        self.max_tool_output_group_chars = int(
            options.get("max_tool_output_group_chars", 0) or 0
        )
        self.tool_output_dir = str(options.get("tool_output_dir") or "")
        self.reminder = options.get("reminder") or None
        self.evict_prior_tool_outputs = bool(
            options.get("evict_prior_tool_outputs", True)
        )
        self.repeated_tool_failure_limit = max(
            1, int(options.get("repeated_tool_failure_limit", 2) or 2)
        )
        self.transport_circuit_breaker = bool(
            options.get("transport_circuit_breaker", True)
        )
        self.reasoning_markup_tags = tuple(
            options.get("reasoning_markup_tags") or ()
        )
        self.pathological_stream_min_chars = max(
            0, int(options.get("pathological_stream_min_chars", 2048) or 0)
        )
        self.pathological_stream_max_ratio = min(
            1.0,
            max(
                0.0,
                float(options.get("pathological_stream_max_ratio", 0.25) or 0.0),
            ),
        )

        self._total_usage: dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        }
        from shipit_agent.llms.base import prompt_cache_info

        self._prompt_cache = prompt_cache_info(getattr(self, "llm", None))
        self._prompt_cache_usage_reported = False
        self._cancel_event = threading.Event()
        self._guarded_tool_calls = 0
        self._nudges_used = 0
        self._last_nudged_text = ""
        self._requested_tool_nudges = 0
        self._discovery_nudges = 0
        self._stream_abort_nudges = 0
        self._tool_circuit_lock = threading.Lock()
        self._compactor_instance: Any = None
        self.connections: Any = None

    @staticmethod
    def _tool_call_key(tool_call: Any) -> str:
        name = str(getattr(tool_call, "name", "") or "")
        arguments = getattr(tool_call, "arguments", None) or {}
        return f"{name}:{_arguments_key(arguments)}"

    def record_tool_failure(self, state: Any, tool_call: Any) -> None:
        failures = getattr(state, "failed_tool_calls", None)
        if isinstance(failures, dict):
            key = self._tool_call_key(tool_call)
            failures[key] = int(failures.get(key, 0) or 0) + 1

    def record_tool_outcome(
        self, state: Any, tool_call: Any, tool_result: Any
    ) -> None:
        metadata = dict(getattr(tool_result, "metadata", None) or {})
        failed = (
            bool(metadata.get("error"))
            or metadata.get("ok") is False
            or bool(metadata.get("timed_out"))
            or (
                metadata.get("exit_code") is not None
                and metadata.get("exit_code") != 0
            )
        )
        if failed:
            self.record_tool_failure(state, tool_call)
        if not self.transport_circuit_breaker:
            return
        name = str(getattr(tool_call, "name", "") or "")
        unreachable = getattr(state, "unreachable_tools", None)
        reachable = getattr(state, "reachable_tools", None)
        if not isinstance(unreachable, dict) or not isinstance(reachable, set):
            return
        with self._tool_circuit_lock:
            if not failed:
                reachable.add(name)
                unreachable.pop(name, None)
                return
            summary = _transport_failure_summary(tool_result)
            if summary is not None and name not in reachable:
                unreachable.setdefault(name, summary)
                metadata["transport_circuit_opened"] = True
                metadata["transport_failure"] = summary
                tool_result.metadata = metadata

    def block_unreachable_tool(
        self,
        state: Any,
        *,
        tool_call: Any,
        tool_call_record: dict[str, Any],
        iteration: int,
    ) -> Message | None:
        """Block a tool proven unreachable earlier in this run."""
        if not self.transport_circuit_breaker:
            return None
        name = str(getattr(tool_call, "name", "tool") or "tool")
        unreachable = getattr(state, "unreachable_tools", None)
        if not isinstance(unreachable, dict):
            return None
        with self._tool_circuit_lock:
            reason = unreachable.get(name)
        if reason is None:
            return None
        content = (
            f"Tool '{name}' was not run because its endpoint is unreachable "
            f"this turn ({reason}). Use another source or report the outage; "
            "changing the query will not repair the connection."
        )
        self.emit(
            state,
            "tool_circuit_blocked",
            f"Unreachable tool blocked: {name}",
            tool=name,
            call_id=tool_call_record.get("id"),
            error="transport_circuit_open",
            reason=reason,
            iteration=iteration,
        )
        return Message(
            role="tool",
            name=name,
            content=content,
            metadata={
                "tool_call_id": tool_call_record.get("id"),
                "error": "transport_circuit_open",
                "reason": reason,
            },
        )

    def discovery_only_nudge(
        self, state: Any, *, user_prompt: str, last: bool
    ) -> str | None:
        """Continue once when discovery found capabilities but none ran."""
        if last or self._discovery_nudges >= 1:
            return None
        # Tool discovery itself is a valid answer to catalog/recommendation
        # questions. Only task-oriented turns should be pushed to execution.
        normalized = " ".join(user_prompt.lower().split())
        if re.search(
            r"\b(which|what|list|show|find|recommend)\b.{0,40}"
            r"\b(tools?|capabilit(?:y|ies))\b",
            normalized,
        ):
            return None
        results = list(getattr(state, "tool_results", None) or [])
        if not results:
            return None
        discovery = [
            result
            for result in results
            if bool((getattr(result, "metadata", None) or {}).get("discovery_only"))
        ]
        substantive = [result for result in results if result not in discovery]
        found = any(
            bool((getattr(result, "metadata", None) or {}).get("matches"))
            for result in discovery
        )
        if not discovery or substantive or not found:
            return None
        self._discovery_nudges += 1
        return (
            "Discovery only identified available capabilities; it did not "
            "complete the user's task. Invoke the best discovered capability "
            "now. If it cannot run, state the concrete blocker."
        )

    def stream_abort_nudge(self, response: Any, *, last: bool) -> str | None:
        if last or self._stream_abort_nudges >= 1:
            return None
        metadata = dict(getattr(response, "metadata", None) or {})
        if metadata.get("stream_abort_reason") not in {
            "pathological_tool_input",
            "pathological_output",
        }:
            return None
        self._stream_abort_nudges += 1
        return (
            "The previous model stream was stopped because it became "
            "pathologically repetitive. Retry once with one concise public "
            "update and one valid structured tool call."
        )

    def block_repeated_failure(
        self,
        state: Any,
        *,
        tool_call: Any,
        tool_call_record: dict[str, Any],
        iteration: int,
    ) -> Message | None:
        failures = getattr(state, "failed_tool_calls", None)
        if not isinstance(failures, dict):
            return None
        count = int(failures.get(self._tool_call_key(tool_call), 0) or 0)
        if count < self.repeated_tool_failure_limit:
            return None

        name = str(getattr(tool_call, "name", "tool") or "tool")
        content = (
            f"Tool '{name}' was not run because this exact call already failed "
            f"{count} times. Do not repeat it unchanged. Correct the arguments, "
            "choose a different tool, or finish with the evidence available."
        )
        self.emit(
            state,
            "tool_failed",
            f"Repeated failed tool call blocked: {name}",
            tool=name,
            call_id=tool_call_record.get("id"),
            error="repeated_failure_blocked",
            failure_count=count,
            arguments=dict(getattr(tool_call, "arguments", None) or {}),
            iteration=iteration,
        )
        return Message(
            role="tool",
            name=name,
            content=content,
            metadata={
                "tool_call_id": tool_call_record.get("id"),
                "error": "repeated_failure_blocked",
                "failure_count": count,
            },
        )

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
        from shipit_agent.tool_healing import coerce_argument_values

        arguments = coerce_argument_values(arguments, schema)
        tool_call.arguments = arguments
        repaired = repair_argument_names(arguments, schema)
        if repaired != arguments:
            tool_call.arguments = repaired
            arguments = repaired
        name = getattr(tool, "name", "tool")
        declared = ", ".join(
            f"'{key}'" for key in (schema.get('properties') or {})
        )
        absent = call_carries_nothing(arguments, schema)
        if absent:
            names = ", ".join(f"'{key}'" for key in absent)
            # "No arguments" is only true when the call was literally empty.
            # Observed live: a model's own reasoning was parsed into argument
            # keys, so the call arrived carrying "might not work, i'll try…"
            # and "query:null}} browing…" — none of them parameters. Telling
            # it that it "passed no arguments" is then plainly contradicted by
            # what it just wrote, and it retries the same shape. Naming the
            # keys it actually sent is what lets it see the mistake.
            if arguments:
                junk = ", ".join(
                    f"'{_bounded_key(key)}'" for key in list(arguments)[:4]
                )
                return (
                    f"Error: {name} was not run. None of the arguments you "
                    f"sent are its parameters — you sent {junk}. Its "
                    f"parameters are {declared or 'none'}. Send a tool call "
                    f"whose arguments are exactly those names, with {names} "
                    "set to a value taken from the request; do not put "
                    "sentences or reasoning in the argument names."
                )
            return (
                f"Error: {name} was called with no arguments. It was not "
                f"run. Call it again and pass {names} using values grounded "
                "in the request or prior tool results."
            )
        missing = _missing_required(arguments, schema)
        if missing:
            names = ", ".join(f"'{key}'" for key in missing)
            supplied = ", ".join(f"'{key}'" for key in sorted(arguments)) or "nothing"
            return (
                f"Error: {name} was called without {names}, which its schema "
                f"declares required. It was not run. You supplied {supplied}. "
                "Call it again with every required argument present."
            )
        return None

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
        from shipit_agent.prompts.reminders import build_reminder

        max_iterations = int(getattr(self, "max_iterations", 0) or 0)
        last_step = iteration == max_iterations and max_iterations > 1
        step_schemas = [] if last_step else list(tool_schemas)

        runtime_nudge = bool(
            messages and messages[-1].metadata.get("runtime_nudge")
        )
        reminder = None if runtime_nudge else build_reminder(
            ran_tools=ran_tools,
            out_of_steps=last_step,
            custom=self.reminder,
        )
        if reminder and tool_schemas:
            messages = [*messages, Message(role="user", content=reminder)]
        return messages, step_schemas

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
        output = str(getattr(tool_result, "output", "") or "")
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
        digest = hashlib.sha256(output.encode("utf-8", "replace")).hexdigest()
        persisted_path = ""
        if limit > 0 and len(output) > limit:
            persisted_path = self._persist_tool_output(
                tool_result, output=output, name=name, digest=digest
            )

        if seen is not None and len(output) >= _REPEAT_MIN_CHARS:
            key = (name, _arguments_key(arguments))
            if seen.get(key) == digest:
                metadata = getattr(tool_result, "metadata", None)
                if isinstance(metadata, dict):
                    metadata.update({
                        "repeat_of_earlier_call": True,
                        "omitted_output_chars": len(output),
                    })
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
            seen[key] = digest

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

        safe_name = "".join(
            char if char.isalnum() or char in "-_" else "_" for char in name
        ).strip("_") or "tool"
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
        if not self.heal_tool_calls or response.tool_calls:
            return
        from shipit_agent.tool_healing import heal_tool_calls, schemas_from_tools

        tools = list(registry.values())
        names = {tool.name for tool in tools}
        schemas = schemas_from_tools(tools)

        healed: list[Any] = []
        source = "content"
        if response.content:
            cleaned, healed = heal_tool_calls(
                response.content, names, schemas=schemas
            )
            if healed:
                response.content = cleaned
        if not healed and response.reasoning_content and not (response.content or "").strip():
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

    def sanitize_response(
        self, state: Any, response: LLMResponse, iteration: int
    ) -> None:
        """Compact pathological repeated output before it enters history."""
        from shipit_agent.reasoning_markup import split_reasoning_markup

        raw = response.content or ""
        visible, extracted_reasoning, malformed_reasoning = split_reasoning_markup(
            raw, self.reasoning_markup_tags
        )
        cleaned, removed = _collapse_repeated_lines(visible)
        raw_reasoning = response.reasoning_content or ""
        if extracted_reasoning:
            raw_reasoning = "\n".join(
                part for part in (raw_reasoning, extracted_reasoning) if part
            )
        cleaned_reasoning, removed_reasoning = _collapse_repeated_lines(raw_reasoning)
        removed_arguments = 0
        for tool_call in response.tool_calls:
            compacted_arguments: dict[str, Any] = {}
            for name, value in dict(tool_call.arguments or {}).items():
                if isinstance(value, str):
                    compacted, argument_removed = _collapse_repeated_lines(value)
                    # Preserve byte-significant tool input (file newlines,
                    # indentation, query whitespace) when no pathology was
                    # found. Response prose can be stripped; tool arguments
                    # cannot.
                    compacted_arguments[name] = (
                        compacted if argument_removed else value
                    )
                    removed_arguments += argument_removed
                else:
                    compacted_arguments[name] = value
            tool_call.arguments = compacted_arguments
        filtered_reasoning_chars = max(0, len(raw) - len(visible))
        pathological = (
            removed >= 3
            or removed_reasoning >= 3
            or removed_arguments >= 3
            or malformed_reasoning
            or filtered_reasoning_chars > 0
        )
        if visible != raw or removed:
            response.content = cleaned
        if extracted_reasoning or removed_reasoning:
            response.reasoning_content = cleaned_reasoning
        if pathological:
            response.metadata["pathological_repetition"] = True
            self.emit(
                state,
                "model_output_compacted",
                "Compacted pathological repeated model output",
                iteration=iteration,
                removed_lines=removed + removed_reasoning,
                removed_argument_fragments=removed_arguments,
                filtered_reasoning_chars=filtered_reasoning_chars,
                original_chars=len(raw) + len(raw_reasoning),
                compacted_chars=(
                    len(response.content or "") + len(response.reasoning_content or "")
                ),
            )

    def missing_explicitly_requested_tools(
        self, user_prompt: str, registry: Any, state: Any
    ) -> list[str]:
        """Registered tool names the user explicitly requested but have not run."""
        prompt = str(user_prompt or "")
        completed = {
            result.name
            for result in getattr(state, "tool_results", [])
            if not (
                result.metadata.get("error")
                or result.metadata.get("ok") is False
                or result.metadata.get("timed_out")
                or (
                    result.metadata.get("exit_code") is not None
                    and result.metadata.get("exit_code") != 0
                )
            )
        }
        completed.update(
            str(result.metadata.get("delegated_tool"))
            for result in getattr(state, "tool_results", [])
            if result.metadata.get("delegated_tool")
            and not result.metadata.get("error")
            and result.metadata.get("ok") is not False
        )
        missing: list[str] = []
        for tool in registry.values():
            name = str(getattr(tool, "name", "") or "")
            if not name or name in completed:
                continue
            match = re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", prompt, re.I)
            if match is None:
                continue
            prefix = prompt[max(0, match.start() - 40) : match.start()].lower()
            if re.search(
                r"(?:do\s+not|don't|never|without|avoid)\s+(?:using\s+)?$",
                prefix,
            ):
                continue
            missing.append(name)
        return missing

    def requested_tool_nudge(
        self, user_prompt: str, registry: Any, state: Any, *, last: bool
    ) -> str | None:
        if last or self._requested_tool_nudges >= 2:
            return None
        missing = self.missing_explicitly_requested_tools(user_prompt, registry, state)
        if not missing:
            return None
        self._requested_tool_nudges += 1
        names = ", ".join(f"`{name}`" for name in missing)
        return (
            "The user explicitly requested available tool(s) that have not "
            f"completed successfully: {names}. Do not answer yet. Emit one "
            "structured call to a missing tool now, using arguments grounded "
            "in the user request and prior tool results. Do not print tool "
            "syntax or repeat an unchanged read."
        )

    def unmet_requirements(
        self, user_prompt: str, registry: Any, state: Any
    ) -> list[str]:
        """Return explicitly named tools or MCP servers not used successfully."""
        missing = self.missing_explicitly_requested_tools(
            user_prompt, registry, state
        )
        prompt = str(user_prompt or "")
        successful_servers = {
            str(result.metadata.get("server"))
            for result in getattr(state, "tool_results", [])
            if result.metadata.get("server")
            and not result.metadata.get("error")
            and result.metadata.get("ok") is not False
        }
        for server in getattr(self, "mcps", []) or []:
            name = str(getattr(server, "name", "") or "")
            if not name or name in successful_servers or name in missing:
                continue
            if re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", prompt, re.I):
                missing.append(name)
        return missing

    def should_nudge(
        self, response: LLMResponse, *, has_tools: bool, last: bool
    ) -> bool:
        """Is this the stall shape, and may we re-prompt once?"""
        if not (self.heal_tool_calls and has_tools and not last):
            return False
        pathological = bool(response.metadata.get("pathological_repetition"))
        limit = 2 if pathological else 1
        if self._nudges_used >= limit:
            return False
        content = (response.content or "").strip()
        if pathological:
            return True
        return (
            is_intent_without_action(content)
            and content != self._last_nudged_text
        )

    def record_nudge(self, response: LLMResponse) -> None:
        self._nudges_used += 1
        self._last_nudged_text = (response.content or "").strip()

    NUDGE_TEXT = (
        "You described an action but did not call any tool with a valid "
        "structured tool call. "
        "Do not narrate or print tool syntax. Return one structured function "
        "call now, or give your final answer directly if no tool is needed."
    )

    # ── usage ────────────────────────────────────────────────────────────

    def track_usage(self, state: Any, response: LLMResponse, iteration: int) -> None:
        """Accumulate tokens and emit a running total for the live footer."""
        self._prompt_cache_usage_reported = self._prompt_cache_usage_reported or any(
            key in response.usage
            for key in ("cache_read_input_tokens", "cache_creation_input_tokens")
        )
        for key in (
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
        ):
            self._total_usage[key] += response.usage.get(key, 0)
        from shipit_agent.llms.prompt_cache import prompt_cache_status

        self.emit(
            state,
            "usage_tick",
            "Usage updated",
            usage=dict(self._total_usage),
            prompt_cache=prompt_cache_status(
                self._prompt_cache,
                read_tokens=self._total_usage["cache_read_input_tokens"],
                write_tokens=self._total_usage["cache_creation_input_tokens"],
                usage_reported=self._prompt_cache_usage_reported,
            ),
            iteration=iteration,
        )

    # ── compaction ───────────────────────────────────────────────────────

    def compactor(self) -> Any:
        if self._compactor_instance is None:
            from shipit_agent.compaction import Compactor

            self._compactor_instance = Compactor(
                llm=self.llm,
                model=getattr(self.llm, "model", None),
                context_window_tokens=self.context_window_tokens,
            )
        return self._compactor_instance

    def compact(
        self, state: Any, messages: list[Message], iteration: int
    ) -> list[Message]:
        """Compact if needed, emitting a notice. Returns what to send."""
        if not self.context_window_tokens:
            return messages
        checkpoint = self.compactor().compact(messages)
        if checkpoint is None:
            return messages
        replayed = checkpoint.replay(messages)
        self.emit(
            state,
            "context_compacted",
            "Older turns condensed to stay within the context window",
            before=len(messages),
            after=len(replayed),
            saved_tokens=checkpoint.saved_tokens,
            checkpoints=len(self.compactor().checkpoints),
            iteration=iteration,
        )
        return replayed

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
        available_tools = [
            describe_tool_capability(
                tool,
                connections=resolved_connections,
            )
            for tool in registry.values()
        ]
        shared_state: dict[str, Any] = {}

        def discover_deferred_tools(query: str = "") -> dict[str, Any]:
            pending = len(getattr(registry, "deferred_mcps", []))
            if not pending:
                return {"tools": available_tools, "discovered": 0, "failures": []}
            if state is not None:
                self.emit(
                    state,
                    "mcp_discovery_started",
                    "Discovering MCP capabilities on demand",
                    server_count=pending,
                )
            query_lower = str(query or "").lower()
            explicit_servers = {
                mcp.name
                for mcp in getattr(registry, "deferred_mcps", [])
                if mcp.name and mcp.name.lower() in query_lower
            }
            discovered, failures = registry.discover_deferred_mcps(
                explicit_servers or None
            )
            capabilities = [
                describe_tool_capability(tool, connections=resolved_connections)
                for tool in discovered
            ]
            available_tools.extend(capabilities)
            parent = shared_state.get(PARENT_STATE_KEY)
            if isinstance(parent, dict) and isinstance(parent.get("tools"), list):
                parent["tools"].extend(discovered)

            # Explicit code mode can compose hidden tools through env.*. Add
            # newly discovered MCP tools to its live binding table without
            # rebuilding or enlarging the model-visible schema list.
            from shipit_agent.tools.describe_binding.describe_binding_tool import (
                BINDINGS_STATE_KEY,
            )

            bindings = shared_state.get(BINDINGS_STATE_KEY)
            if isinstance(bindings, dict) and discovered:
                from shipit_agent.codemode import build_bindings
                from shipit_agent.codemode.catalog import load_catalog

                bindings.update(
                    build_bindings(
                        discovered,
                        catalogs={
                            getattr(tool, "name", ""): load_catalog(tool)
                            for tool in discovered
                        },
                    )
                )
            schemas = registry.schemas()
            self.metadata["registered_tool_count"] = len(schemas)
            self.metadata["registered_tool_schema_chars"] = len(
                json.dumps(schemas, sort_keys=True, default=str)
            )
            self.metadata["hidden_tool_count"] = max(
                0,
                len(schemas) - int(self.metadata.get("exposed_tool_count", 0)),
            )
            self.metadata["deferred_mcp_count"] = len(
                getattr(registry, "deferred_mcps", [])
            )
            self.metadata["discovered_mcp_tool_count"] = (
                int(self.metadata.get("discovered_mcp_tool_count", 0))
                + len(discovered)
            )
            if state is not None:
                self.emit(
                    state,
                    "mcp_discovery_completed",
                    "MCP capability discovery completed",
                    discovered=len(discovered),
                    failures=failures,
                )
            return {
                "tools": available_tools,
                "discovered": len(discovered),
                "failures": failures,
            }

        self.metadata["deferred_mcp_count"] = len(
            getattr(registry, "deferred_mcps", [])
        )
        shared_state.update({
            "available_tools": available_tools,
            "discover_deferred_tools": discover_deferred_tools,
            "deferred_mcp_servers": [
                mcp.name for mcp in getattr(registry, "deferred_mcps", [])
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
        })
        return shared_state

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
# Only failures proving that the tool endpoint itself is unreachable open the
# turn-scoped circuit. Authentication, invalid queries, and downstream service
# errors remain retryable with corrected inputs.
_CONNECTIVITY_ERROR_MARKERS = (
    "connection refused",
    "connect timeout",
    "connecttimeouterror",
    "connection timed out",
    "max retries exceeded",
    "name or service not known",
    "temporary failure in name resolution",
    "no route to host",
    "network is unreachable",
)
_DOWNSTREAM_CONNECTIVITY_MARKERS = (
    "datasource",
    "data source",
    "upstream",
    "backend",
    "target connection",
    "peer connection",
)


def _transport_failure_summary(tool_result: Any) -> str | None:
    metadata = dict(getattr(tool_result, "metadata", None) or {})
    values = [
        metadata.get("error"),
        metadata.get("exception"),
        getattr(tool_result, "output", ""),
    ]
    text = " ".join(str(value) for value in values if value).strip()
    lowered = text.lower()
    if not any(marker in lowered for marker in _CONNECTIVITY_ERROR_MARKERS):
        return None
    if any(marker in lowered for marker in _DOWNSTREAM_CONNECTIVITY_MARKERS):
        return None
    one_line = " ".join(text.split())
    return one_line if len(one_line) <= 160 else one_line[:160] + "..."
