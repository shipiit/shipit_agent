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
from shipit_agent.llms.base import (
    LLM,
    LLMResponse,
    accepts_text_delta_callback,
    accepts_tool_input_callback,
)
from shipit_agent.mcp import MCPServer
from shipit_agent.models import AgentEvent, Message, ToolResult
from shipit_agent.narrate.verbs import summarize
from shipit_agent.permissions import (
    PermissionEngine,
)
from shipit_agent.policies import RetryPolicy, RouterPolicy
from shipit_agent.registry import ToolRegistry
from shipit_agent.runtime_core import RuntimeCore
from shipit_agent.stores import (
    InMemoryMemoryStore,
    InMemorySessionStore,
    MemoryFact,
    MemoryStore,
    SessionRecord,
    SessionStore,
)
from shipit_agent.tool_runner import ToolRunner
from shipit_agent.tools import Tool, ToolContext, ToolOutputChunk
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
_SHARED_SERVICE_STATE_KEYS = frozenset({"memory_store", "credential_store"})


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


_INTENT_MARKERS = (
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


def _is_intent_without_action(text: str | None) -> bool:
    """Short, action-narrating text with no substance — the stall shape."""
    stripped = (text or "").strip().lower()
    if not stripped or len(stripped) > 300:
        return False
    return any(marker in stripped for marker in _INTENT_MARKERS)


def _join_clauses(parts: list[str]) -> str:
    """``a``, ``a and b``, ``a, b and c`` — an English list, not a dump."""
    parts = [part for part in parts if part]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def _arguments_by_name(tool_calls: list[Any] | None) -> dict[str, dict]:
    """Arguments per tool name, so a result can name what it acted on.

    Keyed by name rather than zipped by position: a call that was denied
    or failed to execute produces no result, and a positional pairing
    would then attribute every later result to the wrong call.
    """
    found: dict[str, dict] = {}
    for call in tool_calls or []:
        name = getattr(call, "name", "")
        if name and name not in found:
            found[name] = dict(getattr(call, "arguments", None) or {})
    return found


def _result_failed(result: ToolResult) -> bool:
    """Whether a tool reported failure, by either convention it uses."""
    metadata = result.metadata or {}
    return bool(metadata.get("error")) or metadata.get("ok") is False


class AgentRuntime(RuntimeCore):
    def __init__(
        self,
        *,
        llm: LLM,
        decision_llm: LLM | None = None,
        progress_summaries: bool = True,
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
        max_tool_concurrency: int | None = None,
        hooks: Any | None = None,
        context_window_tokens: int = 0,
        max_tool_output_chars: int = 0,
        replan_interval: int = 0,
        permissions: PermissionEngine | None = None,
        guardrails: Any | None = None,
        heal_tool_calls: bool = True,
        approvals: Any | None = None,
        code_mode: bool = False,
        lockdown: Any = None,
    ) -> None:
        self.llm = llm
        # Retained for compatibility only. Progress narration is composed
        # from the run's own tool calls and results, so nothing here is
        # ever called — turning narration on no longer doubles the model
        # calls a run makes.
        self.decision_llm = decision_llm
        self.progress_summaries = progress_summaries
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
        if max_tool_concurrency is not None and max_tool_concurrency < 1:
            raise ValueError("max_tool_concurrency must be positive or None")
        self.max_tool_concurrency = max_tool_concurrency
        self.hooks = hooks
        self.context_window_tokens = context_window_tokens
        self.replan_interval = replan_interval
        self.permissions = permissions
        # Everything shared with AsyncAgentRuntime — guardrails, lockdown,
        # approvals, healing, usage, compaction, cancellation — lives in
        # RuntimeCore so the two loops cannot drift apart again.
        self._init_core(
            guardrails=guardrails,
            heal_tool_calls=heal_tool_calls,
            approvals=approvals,
            code_mode=code_mode,
            lockdown=lockdown,
            context_window_tokens=context_window_tokens,
            max_tool_output_chars=max_tool_output_chars,
        )
        # Detect once whether this LLM adapter accepts the inline-streaming
        # ``text_delta_callback`` kwarg. Adapters on the older protocol
        # signature don't — passing it unconditionally raises TypeError.
        self._llm_streams_text = accepts_text_delta_callback(self.llm.complete)
        # Only Anthropic surfaces partial tool arguments today; everywhere
        # else arguments arrive whole, exactly as before.
        self._llm_streams_tool_input = accepts_tool_input_callback(self.llm.complete)
        self._event_subscriber: Callable[[AgentEvent], None] | None = None
        # Serializes event emission so parallel tool threads don't interleave
        # writes to a (possibly non-atomic) trace store.
        self._emit_lock = threading.Lock()

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

    def _install_code_mode(
        self,
        *,
        state: RuntimeState,
        registry: ToolRegistry,
        tool_runner: ToolRunner,
        shared_state: dict[str, Any],
        user_prompt: str,
        base_prompt: str,
    ) -> str:
        """Publish `env` bindings and the gated invoker; return the prompt section.

        The invoker is the whole security story: it routes a binding call back
        through :meth:`_execute_single_tool`, so a call made from sandboxed
        code gets the identical permission check, guardrails, approval queue,
        retries and transcript events as the equivalent tool call. There is no
        second, weaker path.
        """
        from shipit_agent.codemode import CORE_TOOLS, binding_index, build_bindings
        from shipit_agent.codemode.catalog import load_catalog
        from shipit_agent.tools.describe_binding.describe_binding_tool import (
            BINDINGS_STATE_KEY,
        )
        from shipit_agent.tools.execute_code.execute_code_tool import (
            INVOKER_STATE_KEY,
        )

        bound_tools = [
            tool
            for tool in registry.values()
            if getattr(tool, "name", "") not in CORE_TOOLS
        ]
        if not bound_tools:
            return ""

        catalogs = {
            getattr(tool, "name", ""): load_catalog(tool) for tool in bound_tools
        }
        bindings = build_bindings(bound_tools, catalogs=catalogs)

        # Each env call is a real tool call. Give it its own id sequence so the
        # transcript can tell them apart from the model's direct calls.
        counter = {"n": 0}

        def _invoke(
            binding_name: str, method: str, kwargs: dict[str, Any]
        ) -> tuple[str, dict[str, Any]]:
            binding = bindings.get(binding_name)
            if binding is None:
                raise KeyError(f"no binding named {binding_name!r}")
            if method not in binding.methods:
                raise AttributeError(f"env.{binding_name} has no method {method!r}")

            arguments = dict(kwargs)
            # A single-method binding wraps a tool with no action enum, so the
            # method name is ours, not the tool's — don't pass it through.
            if method != "call":
                arguments["action"] = method

            counter["n"] += 1
            record = {"id": f"env_{counter['n']}", "name": binding.tool_name}
            call = type(
                "EnvToolCall", (), {"name": binding.tool_name, "arguments": arguments}
            )()
            result, message = self._execute_single_tool(
                state=state,
                registry=registry,
                tool_runner=tool_runner,
                tool_call=call,
                tool_call_record=record,
                context=ToolContext(
                    prompt=user_prompt,
                    system_prompt=base_prompt,
                    metadata=dict(self.metadata),
                    state=shared_state,
                    session_id=self.session_id,
                ),
                iteration=0,
            )
            if result is None:
                # Denied, or queued for approval. The message carries the
                # reason; hand it to the sandbox as an exception so the code
                # sees a failure rather than a silent empty string.
                raise PermissionError(message.content)
            return result.output, dict(result.metadata)

        shared_state[BINDINGS_STATE_KEY] = bindings
        shared_state[INVOKER_STATE_KEY] = _invoke
        return binding_index(bindings)

    def _defer_tool_call(
        self,
        *,
        state: RuntimeState,
        tool: Any,
        tool_call: Any,
        tool_call_record: dict[str, Any],
        context: ToolContext,
        iteration: int,
    ) -> tuple[ToolResult | None, Message] | None:
        """Queue an action for later approval; ``None`` falls through to the gate.

        The decision itself lives in :func:`shipit_agent.approvals.gate.defer_tool_call`
        so this runtime and the async one can never disagree about it.
        """
        from shipit_agent.approvals.gate import defer_tool_call

        deferred_call = tool_call
        runner = ToolRunner(self.registry())

        def _apply() -> ToolResult:
            return runner.run_tool_call(deferred_call, context)

        outcome = defer_tool_call(
            approvals=self.approvals,
            tool=tool,
            tool_call=tool_call,
            call_id=tool_call_record["id"],
            apply_fn=_apply,
        )
        if not outcome.handled:
            return None

        action = outcome.action
        if outcome.result is not None:
            outcome.message.content = self.model_visible_tool_output(outcome.result)
        self.emit(
            state,
            "tool_completed" if outcome.applied else "action_queued",
            f"{'Applied' if outcome.applied else 'Queued for approval'}: {tool_call.name}",
            tool=tool_call.name,
            call_id=tool_call_record["id"],
            action_id=action.id,
            title=action.title,
            tag=action.tag,
            auto_approved=action.auto_approved,
            iteration=iteration,
        )
        return outcome.result, outcome.message

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
        group_id: str | None = None,
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
        decision = self.authorize(tool_call.name, tool_call.arguments, tool)

        # An ASK on a deferrable action goes to the approval queue instead of
        # stopping the run: the agent is told it's queued and keeps working,
        # and the human decides later. Tools whose result the agent reasons
        # over declare `await_decision` and still block — see
        # shipit_agent.tools.contracts.
        if (
            decision is not None
            and decision.needs_approval
            and self.approvals is not None
        ):
            queued = self._defer_tool_call(
                state=state,
                tool=tool,
                tool_call=tool_call,
                tool_call_record=tool_call_record,
                context=context,
                iteration=iteration,
            )
            if queued is not None:
                return queued

        if decision is not None and not decision.allowed:
            reason = decision.reason or "not permitted"
            error_kind = (
                "permission_denied" if decision.denied else "permission_required"
            )
            self.emit(
                state,
                "tool_denied",
                f"Tool blocked: {tool_call.name}",
                # Renderers pair outcomes to calls by (tool, call_id); the gate
                # can fire before `tool_called`, so both must be on the payload.
                tool=tool_call.name,
                call_id=tool_call_record["id"],
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
            group_id=group_id,
            arguments=tool_call.arguments,
            iteration=iteration,
        )
        started_at = time.perf_counter()
        attempt = 0
        output_sequence = 0

        def _publish_output(chunk: ToolOutputChunk) -> None:
            nonlocal output_sequence
            output_sequence += 1
            self.emit(
                state,
                "tool_output_delta",
                f"Tool output: {tool_call.name}",
                tool=tool_call.name,
                call_id=tool_call_record["id"],
                group_id=group_id,
                chunk=chunk.text,
                chunk_metadata=dict(chunk.metadata),
                sequence=output_sequence,
                attempt=attempt + 1,
                iteration=iteration,
            )

        while True:
            self.emit(
                state,
                "tool_output_started",
                f"Tool output started: {tool_call.name}",
                tool=tool_call.name,
                call_id=tool_call_record["id"],
                group_id=group_id,
                attempt=attempt + 1,
                buffered=self.guardrails is not None,
                iteration=iteration,
            )
            try:
                tool_result = tool_runner.run_tool_call(
                    tool_call,
                    context,
                    None if self.guardrails is not None else _publish_output,
                )
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
                        duration_ms=round((time.perf_counter() - started_at) * 1000, 1),
                    )
                    error_output = f"Error running tool '{tool_call.name}': {exc}"
                    tool_result = ToolResult(
                        name=tool_call.name,
                        output=error_output,
                        metadata={"error": str(exc)},
                    )
                    if self.guardrails is None:
                        _publish_output(
                            ToolOutputChunk(error_output, {"error": str(exc)})
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
            tool_result = self.hooks.run_after_tool(tool_call.name, tool_result)

        # Guardrails: sanitize the tool output (indirect prompt-injection
        # neutralized, secrets redacted) BEFORE the model reads it.
        redacted_secret = False
        if self.guardrails is not None and tool_result.output:
            sanitized = self.guardrails.check_tool_output(
                tool_call.name, tool_result.output
            )
            if sanitized.action != "allow":
                self.emit(
                    state,
                    "guardrail_triggered",
                    f"Tool output sanitized: {sanitized.reason}",
                    stage="tool_output",
                    tool=tool_call.name,
                    reason=sanitized.reason,
                )
                redacted_secret = "secret" in str(sanitized.reason or "").lower()
                tool_result.output = sanitized.text

        # A guardrail must inspect the complete output before any part reaches
        # a client. Publish the sanitized value as one safe chunk afterwards.
        if self.guardrails is not None and tool_result.output:
            _publish_output(ToolOutputChunk(tool_result.output, {"buffered": True}))

        model_output = self.model_visible_tool_output(tool_result)
        msg = Message(
            role="tool",
            name=tool_call.name,
            content=model_output,
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
            group_id=group_id,
            output=tool_result.output,
            iteration=iteration,
            duration_ms=round((time.perf_counter() - started_at) * 1000, 1),
        )
        self.note_connection_request(state, tool_call.name, tool_result.metadata)
        self.note_artifacts(state, tool_call.name, tool_result)
        # Did this read latch the run into lockdown?
        trigger = self.lockdown.observe(
            tool=tool_call.name,
            arguments=dict(tool_call.arguments),
            output_metadata=dict(tool_result.metadata),
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
        group_id: str | None = None,
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
            worker_count = min(
                len(tool_calls), self.max_tool_concurrency or len(tool_calls)
            )
            with ThreadPoolExecutor(max_workers=worker_count) as pool:
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
                        group_id=group_id,
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
                    group_id=group_id,
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

    def _generate_decision_summary(
        self,
        *,
        state: RuntimeState,
        response: LLMResponse,
        user_prompt: str,
        iteration: int,
    ) -> str:
        """Say what the agent is about to do, from the calls it chose.

        Composed rather than generated. The calls and their arguments are
        already known here, so asking a model to describe them is paying
        for a paraphrase of data we are holding — and waiting on a network
        round trip before the user can be told what is happening.
        """
        del state, user_prompt, iteration  # narration reads the response alone
        if not self.progress_summaries:
            return ""
        calls = list(response.tool_calls or [])
        if not calls:
            return "Preparing the final answer."
        labels = [
            summarize(call.name, dict(call.arguments or {})).present_label()
            for call in calls
        ]
        return _join_clauses(labels) + "."

    def _generate_observation_summary(
        self,
        *,
        state: RuntimeState,
        tool_results: list[ToolResult],
        user_prompt: str,
        iteration: int,
        tool_calls: list[Any] | None = None,
    ) -> str:
        """Say what just happened, from the results themselves.

        The originating calls are passed in so a result can be narrated
        with its subject — "Read guests.csv" rather than "Read". A
        ``ToolResult`` carries no arguments, and an observation that has
        forgotten what it acted on is barely worth emitting.

        A failure is named rather than folded into the sentence: "it
        failed" is the part a watcher is waiting for, and a summary that
        buries it reads as progress.
        """
        del state, user_prompt, iteration  # narration reads the results alone
        if not tool_results or not self.progress_summaries:
            return ""
        arguments = _arguments_by_name(tool_calls)
        clauses: list[str] = []
        for result in tool_results:
            label = summarize(
                result.name, arguments.get(result.name, {})
            ).past_label()
            if _result_failed(result):
                clauses.append(f"{label} — failed")
            else:
                clauses.append(label)
        return _join_clauses(clauses) + "."

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

        # Stream the one interesting argument of a tool call as the model
        # writes it — the file body, the code, the command — so a renderer can
        # show it appearing instead of nothing until the call is complete.
        parsers: dict[str, Any] = {}
        emitted: dict[str, int] = {}

        def _on_tool_input(call_id: str, tool_name: str, fragment: str) -> None:
            from shipit_agent.narrate.json_stream import (
                StreamingToolInputParser,
                streaming_field_for,
            )

            parser = parsers.get(call_id)
            if parser is None:
                field = streaming_field_for(tool_name)
                if field is None:
                    parsers[call_id] = False  # nothing worth streaming here
                    return
                parser = parsers[call_id] = StreamingToolInputParser(field)
                emitted[call_id] = 0
                self.emit(
                    state,
                    "tool_input_started",
                    f"Writing {tool_name} input",
                    tool=tool_name,
                    call_id=call_id,
                    field=field,
                )
            if parser is False:
                return

            parser.append(fragment)
            if parser.has_error:
                parsers[call_id] = False
                return
            value = parser.streaming_value
            new = value[emitted[call_id] :]
            if new:
                emitted[call_id] = len(value)
                self.emit(
                    state,
                    "tool_input_delta",
                    "",
                    tool=tool_name,
                    call_id=call_id,
                    delta=new,
                )

        complete_kwargs: dict[str, Any] = dict(
            messages=messages,
            tools=tools,
            system_prompt=base_prompt,
            metadata=dict(self.metadata),
        )
        if self._llm_streams_tool_input:
            complete_kwargs["tool_input_callback"] = _on_tool_input
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

    def run(self, user_prompt: str) -> tuple[RuntimeState, LLMResponse]:
        # Guarantee MCP cleanup even if registry construction (which opens MCP
        # transports) or the agent loop raises.
        try:
            return self._run_inner(user_prompt)
        finally:
            self.close_mcps()

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
                refusal = "Request blocked by guardrails: " + decision.reason
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
        # Build the capability control plane before the system prompt so the
        # model sees the same connection/MCP metadata that tools can search.
        shared_state.update(self.build_shared_state(registry, state))
        tool_prompt = build_tools_prompt(
            registry.values(), connections=self.connections.all()
        )
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
        # Built by RuntimeCore, so both loops publish identical tool state —
        # including the sub-agent control plane and the event sink.
        tool_runner = ToolRunner(registry)

        # Code mode: publish `env` and swap the tool schemas the model sees.
        # Must happen before the first completion, since it changes both the
        # system prompt and the advertised tool list.
        if self.code_mode:
            index = self._install_code_mode(
                state=state,
                registry=registry,
                tool_runner=tool_runner,
                shared_state=shared_state,
                user_prompt=user_prompt,
                base_prompt=base_prompt,
            )
            if index:
                from shipit_agent.codemode import CORE_TOOLS

                def _is_core(name: Any) -> bool:
                    return name in CORE_TOOLS

                # Rebuild the system prompt rather than appending to it: the
                # per-tool instructions block describes every registered tool,
                # and leaving all 50 in there would undo most of the saving
                # the schema filter just made.
                core_tools = [
                    tool
                    for tool in registry.values()
                    if _is_core(getattr(tool, "name", ""))
                ]
                core_prompt = build_tools_prompt(
                    core_tools, connections=self.connections.all()
                )
                base_prompt = "\n\n".join(
                    part for part in (self.prompt, core_prompt, index) if part
                )
                state.messages[0] = Message(
                    role="system", content=base_prompt, metadata=dict(self.metadata)
                )
                tool_schemas = [
                    schema
                    for schema in tool_schemas
                    if _is_core((schema.get("function") or {}).get("name"))
                ]

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

            compacted_messages = self.compact(state, list(state.messages), iteration)

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
            self.track_usage(state, response, iteration)

            # Self-healing: small models often emit the tool call as TEXT.
            # Promote declared-tool calls out of the content (response-side
            # only; the promoted span is removed, everything else kept).
            if self.heal_tool_calls and not response.tool_calls and response.content:
                from shipit_agent.tool_healing import heal_tool_calls

                cleaned, healed = heal_tool_calls(
                    response.content,
                    {tool.name for tool in registry.values()},
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

            if response.tool_calls:
                decision_summary = self._generate_decision_summary(
                    state=state,
                    response=response,
                    user_prompt=user_prompt,
                    iteration=iteration,
                )
                if decision_summary:
                    self.emit(
                        state,
                        "agent_decision",
                        "Agent decision",
                        summary=decision_summary,
                        next_action="call_tools",
                        tools=[
                            {
                                "name": call.name,
                                "arguments": dict(call.arguments),
                            }
                            for call in response.tool_calls
                        ],
                        iteration=iteration,
                        generated_by_model=True,
                    )

            if not response.tool_calls:
                # Nudge-on-stall: the model narrated an action ("Let me
                # search…") but called nothing. One tightly-gated re-prompt —
                # short intent-shaped text only, capped, never repeated for
                # identical text — recovers the turn instead of ending it.
                if (
                    self.heal_tool_calls
                    and tool_schemas
                    and iteration < self.max_iterations
                    and self._nudges_used < 1
                    and _is_intent_without_action(response.content)
                    and (response.content or "").strip() != self._last_nudged_text
                ):
                    self._nudges_used += 1
                    self._last_nudged_text = (response.content or "").strip()
                    state.messages.append(
                        Message(role="assistant", content=response.content)
                    )
                    state.messages.append(
                        Message(
                            role="user",
                            content=(
                                "You described an action but did not call any "
                                "tool. Call the tool now, or give your final "
                                "answer directly."
                            ),
                        )
                    )
                    appended_response_id = id(response)
                    self.emit(
                        state,
                        "tool_call_healed",
                        "Nudged: intent without action",
                        nudge=True,
                        iteration=iteration,
                    )
                    continue

                final_decision = self._generate_decision_summary(
                    state=state,
                    response=response,
                    user_prompt=user_prompt,
                    iteration=iteration,
                )
                if final_decision:
                    self.emit(
                        state,
                        "agent_decision",
                        "Agent decision",
                        summary=final_decision,
                        next_action="finish",
                        tools=[],
                        iteration=iteration,
                        generated_by_model=True,
                    )
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

            group_id = f"tool_group_{iteration}"
            self.emit(
                state,
                "tool_group_started",
                "Tool group started",
                group_id=group_id,
                iteration=iteration,
                tool_count=len(tool_call_records),
                tools=[
                    {"name": record["name"], "call_id": record["id"]}
                    for record in tool_call_records
                ],
            )

            iteration_results = self._execute_tool_calls(
                state=state,
                registry=registry,
                tool_runner=tool_runner,
                tool_calls=response.tool_calls,
                tool_call_records=tool_call_records,
                user_prompt=user_prompt,
                base_prompt=base_prompt,
                shared_state=shared_state,
                iteration=iteration,
                group_id=group_id,
            )

            observation_summary = self._generate_observation_summary(
                state=state,
                tool_results=iteration_results,
                user_prompt=user_prompt,
                iteration=iteration,
                tool_calls=response.tool_calls,
            )
            self.emit(
                state,
                "tool_group_completed",
                "Tool group completed",
                group_id=group_id,
                iteration=iteration,
                tool_count=len(tool_call_records),
                completed_count=len(iteration_results),
                summary=observation_summary,
            )
            if observation_summary:
                self.emit(
                    state,
                    "agent_observation",
                    "Agent reviewed tool results",
                    summary=observation_summary,
                    iteration=iteration,
                    next_action="evaluate_results",
                    generated_by_model=True,
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
                self.track_usage(state, summary, self.max_iterations + 1)
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

        # A declared stop (the `give_up` tool) is a first-class outcome, not a
        # buried tool result — surface it so callers and autopilot loops can
        # branch on it instead of pattern-matching prose.
        gave_up = next(
            (r for r in state.tool_results if r.metadata.get("gave_up")), None
        )
        if gave_up is not None:
            self.metadata["gave_up"] = True
            self.metadata["give_up_reason"] = gave_up.metadata.get("give_up_reason", "")
            self.metadata["give_up_needs"] = gave_up.metadata.get("give_up_needs", [])

        self.emit(
            state,
            "final_answer",
            "Final answer generated",
            content=response.content,
            format="markdown",
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
