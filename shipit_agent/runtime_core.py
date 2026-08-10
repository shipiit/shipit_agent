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
    if not stripped or len(stripped) > 300:
        return False
    if stripped.endswith("?"):
        return False
    if _sentence_count(stripped) > 1:
        return False
    return any(marker in stripped for marker in INTENT_MARKERS)


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

        self._total_usage: dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        }
        self._cancel_event = threading.Event()
        self._guarded_tool_calls = 0
        self._nudges_used = 0
        self._last_nudged_text = ""
        self._compactor_instance: Any = None
        self.connections: Any = None

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
        absent = call_carries_nothing(arguments, schema)
        if not absent:
            return None
        names = ", ".join(f"'{name}'" for name in absent)
        return (
            f"Error: {getattr(tool, 'name', 'tool')} was called with no "
            f"arguments. It was not run. Call it again and pass {names} — a "
            f"value taken from the user's question, not an empty string. "
            f"With nothing to go on this tool returns everything it has, "
            f"which is not what was asked for."
        )

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

        reminder = build_reminder(
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

    def should_nudge(
        self, response: LLMResponse, *, has_tools: bool, last: bool
    ) -> bool:
        """Is this the stall shape, and may we re-prompt once?"""
        if not (self.heal_tool_calls and has_tools and not last):
            return False
        if self._nudges_used >= 1:
            return False
        content = (response.content or "").strip()
        return is_intent_without_action(content) and content != self._last_nudged_text

    def record_nudge(self, response: LLMResponse) -> None:
        self._nudges_used += 1
        self._last_nudged_text = (response.content or "").strip()

    NUDGE_TEXT = (
        "You described an action but did not call any tool. Call the tool now, "
        "or give your final answer directly."
    )

    # ── usage ────────────────────────────────────────────────────────────

    def track_usage(self, state: Any, response: LLMResponse, iteration: int) -> None:
        """Accumulate tokens and emit a running total for the live footer."""
        for key in (
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
        ):
            self._total_usage[key] += response.usage.get(key, 0)
        self.emit(
            state,
            "usage_tick",
            "Usage updated",
            usage=dict(self._total_usage),
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
