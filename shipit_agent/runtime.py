from __future__ import annotations

import copy
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator
from uuid import uuid4

from shipit_agent.construction import build_tool_schemas, construct_tool_registry
from shipit_agent.integrations import CredentialStore
from shipit_agent.llms.base import LLM, LLMResponse, accepts_text_delta_callback
from shipit_agent.mcp import MCPServer
from shipit_agent.models import AgentEvent, Message, ToolResult
from shipit_agent.permissions import (
    PermissionEngine,
    PermissionResult,
    authorize_tool,
)
from shipit_agent.policies import RetryPolicy, RouterPolicy
from shipit_agent.registry import ToolRegistry
from shipit_agent.stores import (
    InMemoryMemoryStore,
    InMemorySessionStore,
    MemoryFact,
    MemoryStore,
    SessionRecord,
    SessionStore,
)
from shipit_agent.tool_runner import ToolRunner
from shipit_agent.tools import Tool, ToolContext
from shipit_agent.tools.helpers import build_tools_prompt
from shipit_agent.tracing import InMemoryTraceStore, TraceStore


@dataclass(slots=True)
class RuntimeState:
    messages: list[Message] = field(default_factory=list)
    events: list[AgentEvent] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)


# Keys in the runtime's shared_state that hold shared *service* objects (not
# per-tool data). They must be passed by reference, never deep-copied, when
# isolating state for concurrent tool execution.
_SHARED_SERVICE_STATE_KEYS = frozenset(
    {"memory_store", "credential_store"}
)


def _isolated_tool_state(shared_state: dict[str, Any]) -> dict[str, Any]:
    """Return a per-tool copy of ``shared_state`` for safe concurrent writes.

    Service objects (memory/credential stores) are shared by reference; plain
    data is deep-copied so two tools running in parallel can't corrupt each
    other's reads/writes (e.g. both doing ``state.setdefault("artifacts", [])
    .append(...)``). Copies are merged back via :func:`_merge_tool_state`.
    """
    isolated: dict[str, Any] = {}
    for key, value in shared_state.items():
        if key in _SHARED_SERVICE_STATE_KEYS:
            isolated[key] = value
            continue
        try:
            isolated[key] = copy.deepcopy(value)
        except Exception:
            isolated[key] = value
    return isolated


def _merge_tool_state(target: dict[str, Any], child: dict[str, Any]) -> None:
    """Merge a finished tool's isolated state back into the canonical state.

    Lists are extended with items the child added (de-duplicated); dicts are
    shallow-merged; scalars are last-write-wins. Called in original tool order
    so the merge is deterministic.
    """
    for key, value in child.items():
        if key in _SHARED_SERVICE_STATE_KEYS:
            continue
        if key not in target:
            target[key] = value
        elif isinstance(value, list) and isinstance(target.get(key), list):
            existing = target[key]
            for item in value:
                if item not in existing:
                    existing.append(item)
        elif isinstance(value, dict) and isinstance(target.get(key), dict):
            target[key].update(value)
        else:
            target[key] = value


class AgentRuntime:
    def __init__(
        self,
        *,
        llm: LLM,
        prompt: str,
        tools: list[Tool] | None = None,
        mcps: list[MCPServer] | None = None,
        metadata: dict[str, Any] | None = None,
        history_messages: list[Message] | None = None,
        memory_store: MemoryStore | None = None,
        session_store: SessionStore | None = None,
        session_id: str | None = None,
        max_iterations: int = 4,
        retry_policy: RetryPolicy | None = None,
        router_policy: RouterPolicy | None = None,
        credential_store: CredentialStore | None = None,
        trace_store: TraceStore | None = None,
        trace_id: str | None = None,
        parallel_tool_execution: bool = False,
        hooks: Any | None = None,
        context_window_tokens: int = 0,
        replan_interval: int = 0,
        permissions: PermissionEngine | None = None,
        guardrails: Any | None = None,
    ) -> None:
        self.llm = llm
        self.prompt = prompt
        self.tools = list(tools or [])
        self.mcps = list(mcps or [])
        self.metadata = dict(metadata or {})
        self.history_messages = list(history_messages or [])
        self.memory_store = memory_store or InMemoryMemoryStore()
        self.session_store = session_store or InMemorySessionStore()
        self.session_id = session_id or str(uuid4())
        self.max_iterations = max_iterations
        self.retry_policy = retry_policy or RetryPolicy()
        self.router_policy = router_policy or RouterPolicy()
        self.credential_store = credential_store
        self.trace_store = trace_store or InMemoryTraceStore()
        self.trace_id = trace_id or self.session_id
        self.parallel_tool_execution = parallel_tool_execution
        self.hooks = hooks
        self.context_window_tokens = context_window_tokens
        self.replan_interval = replan_interval
        self.permissions = permissions
        self.guardrails = guardrails
        # Detect once whether this LLM adapter accepts the inline-streaming
        # ``text_delta_callback`` kwarg. Adapters on the older protocol
        # signature don't — passing it unconditionally raises TypeError.
        self._llm_streams_text = accepts_text_delta_callback(self.llm.complete)
        self._total_usage: dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
        self._event_subscriber: Callable[[AgentEvent], None] | None = None
        # Serializes event emission so parallel tool threads don't interleave
        # writes to a (possibly non-atomic) trace store.
        self._emit_lock = threading.Lock()
        # Cooperative cancellation — checked between iterations and before
        # each tool execution. Set from any thread via cancel().
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        """Request cancellation of the in-flight run (thread-safe).

        The loop stops at the next checkpoint — before the next LLM call or
        tool execution — and returns a normal result with whatever was
        produced so far, marked ``metadata["cancelled"] = True``.
        """
        self._cancel_event.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def registry(self) -> ToolRegistry:
        return construct_tool_registry(tools=self.tools, mcps=self.mcps)

    def build_tool_schemas(self) -> list[dict[str, Any]]:
        return build_tool_schemas(self.registry())

    def emit(
        self, state: RuntimeState, event_type: str, message: str, **payload: Any
    ) -> None:
        event = AgentEvent(type=event_type, message=message, payload=payload)
        with self._emit_lock:
            state.events.append(event)
            if self._event_subscriber is not None:
                try:
                    self._event_subscriber(event)
                except Exception:
                    pass
            self.trace_store.append_event(
                self.trace_id,
                event,
                metadata={
                    "session_id": self.session_id,
                    "agent_name": self.metadata.get("agent_name"),
                    "agent_description": self.metadata.get("agent_description"),
                },
            )

    def _run_planner_if_needed(
        self,
        *,
        state: RuntimeState,
        registry: ToolRegistry,
        user_prompt: str,
        base_prompt: str,
        shared_state: dict[str, Any],
        tool_runner: ToolRunner,
    ) -> None:
        planner = registry.get("plan_task")
        if (
            planner is None
            or not self.router_policy.auto_plan
            or not self.router_policy.should_plan(user_prompt)
        ):
            return
        self.emit(state, "planning_started", "Planner started", prompt=user_prompt)
        context = ToolContext(
            prompt=user_prompt,
            system_prompt=base_prompt,
            metadata=dict(self.metadata),
            state=shared_state,
            session_id=self.session_id,
        )
        tool_result = tool_runner.run_tool_call(
            tool_call=type(
                "PlannerCall",
                (),
                {"name": planner.name, "arguments": {"goal": user_prompt}},
            )(),
            context=context,
        )
        state.tool_results.append(tool_result)
        # IMPORTANT: do NOT append this as role="tool". The planner runs before
        # the first assistant turn, so there is no matching `tool_use` block to
        # pair with. Bedrock's Converse API rejects unpaired toolResult blocks
        # with "number of toolResult blocks exceeds number of toolUse blocks of
        # previous turn". Inject it as a regular user-role context message
        # instead — no pairing required, and the LLM still sees the plan.
        state.messages.append(
            Message(
                role="user",
                content=f"[Planner output]\n{tool_result.output}",
                metadata={"source": "planner", "planner_tool": planner.name},
            )
        )
        self.emit(
            state, "planning_completed", "Planner completed", output=tool_result.output
        )

    def _authorize_tool(
        self, name: str, arguments: dict[str, Any], tool: Any
    ) -> PermissionResult | None:
        # Guardrail tool rules run FIRST — a content-level deny (e.g. rm -rf /
        # in bash args) wins over any allow rule in the permission engine.
        if self.guardrails is not None:
            guard = self.guardrails.check_tool(name, arguments)
            if guard is not None and not guard.allowed:
                return guard
        return authorize_tool(self.hooks, self.permissions, name, arguments, tool)

    def _execute_single_tool(
        self,
        *,
        state: RuntimeState,
        registry: ToolRegistry,
        tool_runner: ToolRunner,
        tool_call: Any,
        tool_call_record: dict[str, Any],
        context: ToolContext,
        iteration: int,
    ) -> tuple[ToolResult | None, Message]:
        """Execute a single tool call and return (tool_result, message).

        Returns (None, error_message) for hallucinated tools and for calls
        blocked by the permission engine / a hook.
        """
        tool = registry.get(tool_call.name)
        if tool is None:
            error_output = (
                f"Error: tool '{tool_call.name}' is not registered. "
                f"Choose a different tool from the available list."
            )
            self.emit(
                state,
                "tool_failed",
                f"Tool failed: {tool_call.name}",
                error="tool_not_registered",
                iteration=iteration,
            )
            msg = Message(
                role="tool",
                name=tool_call.name,
                content=error_output,
                metadata={
                    "tool_call_id": tool_call_record["id"],
                    "error": "tool_not_registered",
                },
            )
            return None, msg

        # ── Permission gate: blocking hooks + rule-based permission engine ──
        decision = self._authorize_tool(tool_call.name, tool_call.arguments, tool)
        if decision is not None and not decision.allowed:
            reason = decision.reason or "not permitted"
            error_kind = (
                "permission_denied" if decision.denied else "permission_required"
            )
            self.emit(
                state,
                "tool_denied",
                f"Tool blocked: {tool_call.name}",
                reason=reason,
                decision=decision.decision.value,
                iteration=iteration,
            )
            content = (
                f"Tool '{tool_call.name}' was NOT run — {reason}"
                if decision.denied
                else f"Tool '{tool_call.name}' requires human approval — {reason}"
            )
            msg = Message(
                role="tool",
                name=tool_call.name,
                content=content,
                metadata={
                    "tool_call_id": tool_call_record["id"],
                    "error": error_kind,
                    "decision": decision.decision.value,
                },
            )
            return None, msg
        if decision is not None and decision.updated_arguments is not None:
            # A hook/rule rewrote the arguments — run with the rewritten call.
            tool_call = type(
                "RewrittenToolCall",
                (),
                {
                    "name": tool_call.name,
                    "arguments": dict(decision.updated_arguments),
                },
            )()

        self.emit(
            state,
            "tool_called",
            f"Tool called: {tool_call.name}",
            tool=tool_call.name,
            call_id=tool_call_record["id"],
            arguments=tool_call.arguments,
            iteration=iteration,
        )
        started_at = time.perf_counter()
        attempt = 0
        while True:
            try:
                tool_result = tool_runner.run_tool_call(tool_call, context)
                break
            except self.retry_policy.retry_on_exceptions as exc:
                if attempt >= self.retry_policy.max_tool_retries:
                    self.emit(
                        state,
                        "tool_failed",
                        f"Tool failed: {tool_call.name}",
                        tool=tool_call.name,
                        call_id=tool_call_record["id"],
                        error=str(exc),
                        iteration=iteration,
                        duration_ms=round(
                            (time.perf_counter() - started_at) * 1000, 1
                        ),
                    )
                    error_output = f"Error running tool '{tool_call.name}': {exc}"
                    tool_result = ToolResult(
                        name=tool_call.name,
                        output=error_output,
                        metadata={"error": str(exc)},
                    )
                    break
                attempt += 1
                self.emit(
                    state,
                    "tool_retry",
                    f"Retrying tool: {tool_call.name}",
                    tool=tool_call.name,
                    call_id=tool_call_record["id"],
                    attempt=attempt,
                    error=str(exc),
                    iteration=iteration,
                )

        if self.hooks:
            self.hooks.run_after_tool(tool_call.name, tool_result)

        msg = Message(
            role="tool",
            name=tool_call.name,
            content=tool_result.output,
            metadata={
                **dict(tool_result.metadata),
                "tool_call_id": tool_call_record["id"],
            },
        )
        self.emit(
            state,
            "tool_completed",
            f"Tool completed: {tool_call.name}",
            tool=tool_call.name,
            call_id=tool_call_record["id"],
            output=tool_result.output,
            iteration=iteration,
            duration_ms=round((time.perf_counter() - started_at) * 1000, 1),
        )
        if tool_result.metadata.get("interactive"):
            self.emit(
                state,
                "interactive_request",
                f"Interactive request from {tool_call.name}",
                kind=tool_result.metadata.get("kind"),
                payload=dict(tool_result.metadata),
            )
        return tool_result, msg

    def _execute_tool_calls(
        self,
        *,
        state: RuntimeState,
        registry: ToolRegistry,
        tool_runner: ToolRunner,
        tool_calls: list[Any],
        tool_call_records: list[dict[str, Any]],
        user_prompt: str,
        base_prompt: str,
        shared_state: dict[str, Any],
        iteration: int,
    ) -> list[ToolResult]:
        """Execute tool calls — in parallel if enabled, otherwise sequentially."""
        results: list[ToolResult] = []

        def _make_context() -> ToolContext:
            return ToolContext(
                prompt=user_prompt,
                system_prompt=base_prompt,
                metadata=dict(self.metadata),
                state=shared_state,
                session_id=self.session_id,
            )

        if self.parallel_tool_execution and len(tool_calls) > 1:
            # Run all tool calls concurrently, then append results in
            # original order so the message sequence stays deterministic.
            # Each tool gets its OWN isolated copy of shared_state so concurrent
            # mutations can't corrupt each other; copies are merged back in
            # original order afterwards.
            isolated_states: list[dict[str, Any]] = [
                _isolated_tool_state(shared_state) for _ in tool_calls
            ]
            futures_map: dict[Any, int] = {}
            with ThreadPoolExecutor(max_workers=len(tool_calls)) as pool:
                for idx, tc in enumerate(tool_calls):
                    future = pool.submit(
                        self._execute_single_tool,
                        state=state,
                        registry=registry,
                        tool_runner=tool_runner,
                        tool_call=tc,
                        tool_call_record=tool_call_records[idx],
                        context=ToolContext(
                            prompt=user_prompt,
                            system_prompt=base_prompt,
                            metadata=dict(self.metadata),
                            state=isolated_states[idx],
                            session_id=self.session_id,
                        ),
                        iteration=iteration,
                    )
                    futures_map[future] = idx

                ordered: dict[int, tuple[ToolResult | None, Message]] = {}
                for future in as_completed(futures_map):
                    idx = futures_map[future]
                    ordered[idx] = future.result()

            for idx in range(len(tool_calls)):
                _merge_tool_state(shared_state, isolated_states[idx])
                tool_result, msg = ordered[idx]
                if tool_result is not None:
                    state.tool_results.append(tool_result)
                    results.append(tool_result)
                state.messages.append(msg)
        else:
            # Sequential execution (default)
            for idx, tc in enumerate(tool_calls):
                if self._cancel_event.is_set():
                    # Cancelled mid-batch: answer the remaining tool calls
                    # with a synthetic result so message pairing stays valid.
                    state.messages.append(
                        Message(
                            role="tool",
                            name=tc.name,
                            content="[cancelled before execution]",
                            metadata={
                                "tool_call_id": tool_call_records[idx]["id"],
                                "cancelled": True,
                            },
                        )
                    )
                    continue
                tool_result, msg = self._execute_single_tool(
                    state=state,
                    registry=registry,
                    tool_runner=tool_runner,
                    tool_call=tc,
                    tool_call_record=tool_call_records[idx],
                    context=_make_context(),
                    iteration=iteration,
                )
                if tool_result is not None:
                    state.tool_results.append(tool_result)
                    results.append(tool_result)
                state.messages.append(msg)

        return results

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Rough token estimate: ~4 chars per token for English text."""
        return len(text) // 4 if text else 0

    def _compact_messages(
        self, messages: list[Message]
    ) -> tuple[list[Message], bool]:
        """Summarize older turns to free context space.

        Keeps system messages and the last 4 exchange messages intact;
        everything older is condensed into one summary message (written by
        the LLM when possible). Returns ``(messages, did_compact)``.
        """
        if not self.context_window_tokens:
            return messages, False

        total_chars = sum(len(m.content or "") for m in messages)
        estimated_tokens = total_chars // 4
        threshold = int(self.context_window_tokens * 0.75)

        if estimated_tokens < threshold:
            return messages, False

        # Separate system/user messages from tool exchanges
        keep_head: list[Message] = []
        exchanges: list[Message] = []
        for m in messages:
            if m.role in ("system",):
                keep_head.append(m)
            else:
                exchanges.append(m)

        if len(exchanges) <= 4:
            return messages, False

        # Compact older exchanges, keep last 4 messages intact
        old = exchanges[:-4]
        recent = exchanges[-4:]

        summary_text = self._summarize_for_compaction(old)
        if summary_text:
            compact_msg = Message(
                role="user",
                content=summary_text,
                metadata={"compacted": True},
            )
            return keep_head + [compact_msg] + recent, True

        return messages, False

    def _summarize_for_compaction(self, old: list[Message]) -> str:
        """Condense old turns — with the LLM when possible, mechanically otherwise.

        The model-written summary preserves decisions, facts, file paths, and
        open threads far better than truncation. Any failure (or a missing
        LLM) falls back to the mechanical head-truncation summary so
        compaction never takes the run down.
        """
        transcript_lines: list[str] = []
        for m in old:
            text = (m.content or "").strip()
            if not text:
                continue
            label = f"tool {m.name}" if m.role == "tool" else m.role
            transcript_lines.append(f"[{label}]: {text[:2000]}")
        if not transcript_lines:
            return ""

        try:
            response = self.llm.complete(
                messages=[
                    Message(
                        role="user",
                        content=(
                            "Summarize this earlier portion of an agent "
                            "conversation so the agent can continue seamlessly. "
                            "Preserve: decisions made, key facts and numbers, "
                            "file paths, tool results that matter, and any "
                            "unfinished threads. Be dense; max ~300 words.\n\n"
                            + "\n".join(transcript_lines)
                        ),
                    )
                ],
                tools=[],
                system_prompt="You compress conversation history without losing load-bearing details.",
                metadata={"purpose": "context_compaction"},
            )
            summary = (getattr(response, "content", "") or "").strip()
            if summary:
                return (
                    "Earlier conversation (summarized to save context):\n"
                    + summary
                )
        except Exception:
            pass  # any LLM failure → mechanical fallback below

        mechanical = [line[:200] for line in transcript_lines]
        return (
            "Earlier conversation (condensed to save context):\n"
            + "\n".join(mechanical)
        )

    def _track_usage(self, response: LLMResponse) -> None:
        """Accumulate token usage across iterations."""
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            self._total_usage[key] += response.usage.get(key, 0)

    def _complete_with_retry(
        self,
        *,
        state: RuntimeState,
        messages: list[Message],
        tools: list[dict[str, Any]],
        base_prompt: str,
    ) -> LLMResponse:
        # When the LLM adapter supports streaming via ``text_delta_callback``,
        # emit each text chunk as a ``text_delta`` event so the SSE adapter
        # downstream can forward tokens inline as they arrive. The callback
        # runs on the same thread that called complete(), so emit() is safe.
        def _on_text_delta(chunk: str) -> None:
            if not chunk:
                return
            self.emit(state, "text_delta", "", chunk=chunk)

        complete_kwargs: dict[str, Any] = dict(
            messages=messages,
            tools=tools,
            system_prompt=base_prompt,
            metadata=dict(self.metadata),
        )
        # Only pass the streaming callback to adapters that accept it; older
        # custom adapters keep working unchanged (no inline streaming).
        if self._llm_streams_text:
            complete_kwargs["text_delta_callback"] = _on_text_delta

        attempt = 0
        while True:
            try:
                return self.llm.complete(**complete_kwargs)
            except self.retry_policy.retry_on_exceptions as exc:
                if attempt >= self.retry_policy.max_llm_retries:
                    raise
                attempt += 1
                self.emit(
                    state,
                    "llm_retry",
                    "Retrying LLM completion",
                    attempt=attempt,
                    error=str(exc),
                )

    def _close_mcps(self) -> None:
        """Close every attached MCP transport, swallowing close errors.

        Must run even when the agent loop raises, otherwise a failed run
        leaks live MCP subprocesses / sockets.
        """
        for mcp in self.mcps:
            close = getattr(mcp, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass

    def run(self, user_prompt: str) -> tuple[RuntimeState, LLMResponse]:
        # Guarantee MCP cleanup even if registry construction (which opens MCP
        # transports) or the agent loop raises.
        try:
            return self._run_inner(user_prompt)
        finally:
            self._close_mcps()

    def _run_inner(self, user_prompt: str) -> tuple[RuntimeState, LLMResponse]:
        state = RuntimeState()
        shared_state: dict[str, Any] = {}

        # ── Guardrails: input gate — blocked prompts never reach the LLM ──
        if self.guardrails is not None:
            decision = self.guardrails.check_input(user_prompt)
            if decision.blocked:
                self.emit(
                    state,
                    "guardrail_triggered",
                    f"Input blocked: {decision.reason}",
                    stage="input",
                    reason=decision.reason,
                )
                refusal = (
                    "Request blocked by guardrails: " + decision.reason
                )
                self.emit(
                    state,
                    "run_completed",
                    "Run blocked by guardrails",
                    output=refusal,
                    content=refusal,
                    format="markdown",
                    usage={},
                    cancelled=False,
                    guardrail_blocked=True,
                )
                return state, LLMResponse(content=refusal)
            if decision.action == "redact" and decision.text:
                user_prompt = decision.text
        registry = self.registry()
        tool_prompt = build_tools_prompt(registry.values())
        base_prompt = (
            self.prompt if not tool_prompt else f"{self.prompt}\n\n{tool_prompt}"
        )
        existing_session = self.session_store.load(self.session_id)
        if existing_session:
            prior_messages = existing_session.messages
        elif self.history_messages:
            prior_messages = self.history_messages
        else:
            prior_messages = []
        # Inject exactly one fresh system message at the front, then the prior
        # turns with any *previously persisted* system messages stripped out.
        # Multi-turn sessions (AgentChatSession reuses session_id + store)
        # reload the saved conversation every turn; without this strip a new
        # system message stacks on top of the old one each turn — unbounded
        # growth and a malformed mid-conversation system block that several
        # providers reject.
        state.messages.append(
            Message(role="system", content=base_prompt, metadata=dict(self.metadata))
        )
        state.messages.extend(m for m in prior_messages if m.role != "system")
        state.messages.append(Message(role="user", content=user_prompt))

        self.emit(state, "run_started", "Agent run started", prompt=user_prompt)

        for mcp in self.mcps:
            self.emit(
                state,
                "mcp_attached",
                f"MCP server attached: {mcp.name}",
                server=mcp.name,
            )

        tool_schemas = registry.schemas()
        shared_state["available_tools"] = [
            {
                "name": tool.name,
                "description": tool.description,
                "prompt_instructions": getattr(tool, "prompt_instructions", ""),
            }
            for tool in registry.values()
        ]
        shared_state["memory_store"] = self.memory_store
        shared_state["credential_store"] = self.credential_store
        shared_state["artifact_workspace_root"] = self.metadata.get(
            "artifact_workspace_root", ".shipit_workspace/artifacts"
        )
        shared_state["workspace_root"] = self.metadata.get(
            "workspace_root", ".shipit_workspace"
        )
        tool_runner = ToolRunner(registry)
        self._run_planner_if_needed(
            state=state,
            registry=registry,
            user_prompt=user_prompt,
            base_prompt=base_prompt,
            shared_state=shared_state,
            tool_runner=tool_runner,
        )

        response = LLMResponse(content="")
        # id() of the response object whose content has already been appended
        # as an assistant message inside the loop, so the trailing append
        # below doesn't write the same text twice.
        appended_response_id: int | None = None
        for iteration in range(1, self.max_iterations + 1):
            if self._cancel_event.is_set():
                self.emit(
                    state,
                    "run_cancelled",
                    "Run cancelled by caller",
                    iteration=iteration,
                )
                if not response.content:
                    response = LLMResponse(content="[cancelled]")
                break
            if self.hooks:
                self.hooks.run_before_llm(list(state.messages), tool_schemas)

            # Compact messages if approaching context window limit
            compacted_messages, did_compact = self._compact_messages(
                list(state.messages)
            )
            if did_compact:
                self.emit(
                    state,
                    "context_compacted",
                    "Older turns condensed to stay within the context window",
                    before=len(state.messages),
                    after=len(compacted_messages),
                    iteration=iteration,
                )

            self.emit(
                state,
                "step_started",
                "LLM completion started",
                tool_count=len(tool_schemas),
                iteration=iteration,
            )
            response = self._complete_with_retry(
                state=state,
                messages=compacted_messages,
                tools=tool_schemas,
                base_prompt=base_prompt,
            )
            self._track_usage(response)

            if self.hooks:
                self.hooks.run_after_llm(response)

            if response.reasoning_content:
                self.emit(
                    state,
                    "reasoning_started",
                    "Model reasoning started",
                    iteration=iteration,
                )
                self.emit(
                    state,
                    "reasoning_completed",
                    "Model reasoning completed",
                    iteration=iteration,
                    content=response.reasoning_content,
                )

            if not response.tool_calls:
                break

            tool_call_records = [
                {
                    "id": f"call_{iteration}_{index}",
                    "name": tool_call.name,
                    "arguments": dict(tool_call.arguments),
                }
                for index, tool_call in enumerate(response.tool_calls, start=1)
            ]
            state.messages.append(
                Message(
                    role="assistant",
                    content=response.content,
                    metadata={
                        **dict(response.metadata),
                        "tool_calls": tool_call_records,
                    },
                )
            )
            appended_response_id = id(response)

            self._execute_tool_calls(
                state=state,
                registry=registry,
                tool_runner=tool_runner,
                tool_calls=response.tool_calls,
                tool_call_records=tool_call_records,
                user_prompt=user_prompt,
                base_prompt=base_prompt,
                shared_state=shared_state,
                iteration=iteration,
            )

            # Mid-run re-planning: if replan_interval is set and we've
            # completed that many iterations, run the planner again to
            # re-evaluate progress and correct drift.
            if (
                self.replan_interval > 0
                and iteration % self.replan_interval == 0
                and iteration < self.max_iterations
            ):
                self._run_planner_if_needed(
                    state=state,
                    registry=registry,
                    user_prompt=user_prompt,
                    base_prompt=base_prompt,
                    shared_state=shared_state,
                    tool_runner=tool_runner,
                )

        # If the loop exited because we hit `max_iterations` while the
        # model was still calling tools, the last response has no prose
        # content — the caller would see an empty final answer. Give the
        # model ONE more turn with `tools=[]` so it's forced to write a
        # natural-language summary of what it learned.
        hit_iteration_cap = bool(response.tool_calls) and not response.content
        if hit_iteration_cap:
            self.emit(
                state,
                "step_started",
                "Final summarization turn (iteration cap reached)",
                tool_count=0,
                iteration=self.max_iterations + 1,
            )
            try:
                # Inject a nudge so the model knows it must produce a text
                # answer now (no more tools). Without this, some models
                # (especially via Bedrock) return empty content.
                summary_messages = list(state.messages) + [
                    Message(
                        role="user",
                        content=(
                            "You have reached the tool-call limit. "
                            "Based on everything above, write your final "
                            "answer now. Do not call any tools."
                        ),
                    )
                ]
                summary = self._complete_with_retry(
                    state=state,
                    messages=summary_messages,
                    tools=[],  # force text-only completion
                    base_prompt=base_prompt,
                )
                # The summary turn is a real LLM call — account for its tokens
                # and fire the after-LLM hook, same as in-loop completions.
                self._track_usage(summary)
                if self.hooks:
                    self.hooks.run_after_llm(summary)
                if summary.content:
                    response = summary
            except Exception:
                # Don't let summarization failures mask the whole run.
                pass

        # Append the final answer unless this exact response was already
        # written inside the loop (model narrated alongside a tool call on the
        # last iteration) — otherwise the text would be duplicated.
        if response.content and id(response) != appended_response_id:
            state.messages.append(
                Message(
                    role="assistant",
                    content=response.content,
                    metadata=dict(response.metadata),
                )
            )

        for tool_result in state.tool_results:
            # Only persist tool results that opt-in via persist=True metadata.
            # This prevents memory pollution from noisy tool outputs (e.g.
            # web search results). Tools that produce important facts should
            # set metadata={"persist": True} in their ToolOutput.
            if not tool_result.metadata.get("persist", False):
                continue
            self.memory_store.add(
                MemoryFact(
                    content=f"{tool_result.name}: {tool_result.output}",
                    category="tool_result",
                    metadata=dict(tool_result.metadata),
                )
            )
        self.session_store.save(
            SessionRecord(session_id=self.session_id, messages=list(state.messages))
        )
        # Expose the final answer as both `output` (legacy) and `content`
        # (explicit markdown string) so consumers can render it directly.
        # ── Guardrails: output gate — redact secrets/PII before anyone sees it ──
        if self.guardrails is not None and response.content:
            out_decision = self.guardrails.check_output(response.content)
            if out_decision.action != "allow":
                self.emit(
                    state,
                    "guardrail_triggered",
                    f"Output {out_decision.action}: {out_decision.reason}",
                    stage="output",
                    reason=out_decision.reason,
                )
                response.content = (
                    out_decision.text
                    if out_decision.action == "redact"
                    else f"Response withheld by guardrails: {out_decision.reason}"
                )

        self.emit(
            state,
            "run_completed",
            "Agent run completed",
            output=response.content,
            content=response.content,
            format="markdown",
            usage=dict(self._total_usage),
            cancelled=self._cancel_event.is_set(),
        )
        # MCP transports are closed by run()'s finally (covers the error path
        # too) — don't close here.
        return state, response

    def stream(self, user_prompt: str) -> Iterator[AgentEvent]:
        """Run the agent in a background thread and yield events as they're emitted."""
        event_queue: queue.Queue[AgentEvent | object] = queue.Queue()
        sentinel = object()
        error_box: dict[str, BaseException] = {}

        def _subscriber(event: AgentEvent) -> None:
            event_queue.put(event)

        def _worker() -> None:
            try:
                self.run(user_prompt)
            except BaseException as exc:  # noqa: BLE001
                error_box["error"] = exc
            finally:
                event_queue.put(sentinel)

        self._event_subscriber = _subscriber
        worker = threading.Thread(
            target=_worker, name="shipit-agent-stream", daemon=True
        )
        worker.start()
        try:
            while True:
                item = event_queue.get()
                if item is sentinel:
                    break
                yield item  # type: ignore[misc]
        finally:
            worker.join()
            self._event_subscriber = None
            if "error" in error_box:
                raise error_box["error"]
