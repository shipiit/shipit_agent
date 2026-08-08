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


def is_intent_without_action(text: str | None) -> bool:
    """Did the model narrate an action and then not take one?"""
    stripped = (text or "").strip().lower()
    if not stripped or len(stripped) > 300:
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

    def model_visible_tool_output(self, tool_result: Any) -> str:
        """Bound only the tool output copy sent back to the model.

        The canonical result remains complete for callers and traces. Head and
        tail retention keeps introductory context plus errors printed last.
        """
        output = str(getattr(tool_result, "output", "") or "")
        limit = self.max_tool_output_chars
        if limit <= 0 or len(output) <= limit:
            return output

        marker = (
            "\n\n[Tool output shortened for model context. Use a narrower "
            "query or range to inspect omitted content.]\n\n"
        )
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
        """Promote tool calls a small model emitted as text, in place."""
        if not (self.heal_tool_calls and not response.tool_calls and response.content):
            return
        from shipit_agent.tool_healing import heal_tool_calls

        cleaned, healed = heal_tool_calls(
            response.content, {tool.name for tool in registry.values()}
        )
        if healed:
            response.tool_calls = healed
            response.content = cleaned
            self.emit(
                state,
                "tool_call_healed",
                f"Promoted {len(healed)} text tool call(s)",
                tools=[c.name for c in healed],
                iteration=iteration,
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
