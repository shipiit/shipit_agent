from __future__ import annotations

import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Iterator
from uuid import uuid4

from shipit_agent.construction import build_tool_schemas, construct_tool_registry
from shipit_agent.integrations import CredentialStore
from shipit_agent.llms.base import (
    LLM,
    LLMResponse,
    accepts_kwarg,
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
from shipit_agent.runtime_core import (
    RuntimeCore,
    _declared_paths,
    evict_prior_tool_outputs,
)
from shipit_agent.runtime_narration import (
    _arguments_by_name,
    _bounded,
    _describe_result,
    _first_sentences,
    _join_clauses,
    _looks_like_prose,
    _result_failed,
)
from shipit_agent.runtime_state import (
    RuntimeState,
    _isolated_tool_state,
    _merge_tool_state,
)
from shipit_agent.session_lock import session_run_lock
from shipit_agent.stores import (
    InMemoryMemoryStore,
    InMemorySessionStore,
    MemoryFact,
    MemoryStore,
    SessionRecord,
    SessionStore,
)
from shipit_agent.tool_runner import ToolRunner, safe_tool_event_metadata
from shipit_agent.tools import Tool, ToolContext, ToolOutputChunk
from shipit_agent.tools.helpers import build_tools_prompt
from shipit_agent.tracing import InMemoryTraceStore, TraceStore


class AgentRuntime(RuntimeCore):
    def __init__(
        self,
        *,
        llm: LLM,
        decision_llm: LLM | None = None,
        progress_summaries: bool = True,
        #: Standing guidance repeated at the end of the context each step.
        reminder: str | None = None,
        #: Replace earlier turns' tool payloads with a short notice.
        evict_prior_tool_outputs: bool = True,
        prompt: str,
        tools: list[Tool] | None = None,
        mcps: list[MCPServer] | None = None,
        required_tools: list[str] | None = None,
        require_tool_call: bool = False,
        max_required_tool_text_chars: int = 2_048,
        max_completion_text_chars: int = 0,
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
        fixed_prefix_tokens: int = 0,
        max_tool_output_chars: int = 0,
        max_tool_output_group_chars: int = 0,
        tool_output_dir: str | None = None,
        replan_interval: int = 0,
        permissions: PermissionEngine | None = None,
        guardrails: Any | None = None,
        heal_tool_calls: bool = True,
        approvals: Any | None = None,
        code_mode: bool = False,
        deferred_tools: Any = False,
        lockdown: Any = None,
        verify_before_stop: bool = False,
        #: A provider ``response_format`` dict (from ``output_schema``). Applied
        #: only on tool-less completions — the final answer / synthesis turn —
        #: where JSON-mode is safe; a mid-loop step still needs to call tools.
        response_format: dict[str, Any] | None = None,
        session_runtime_state: dict[str, Any] | None = None,
        close_mcps_on_finish: bool = True,
        stream_queue_maxsize: int = 256,
        cancel_on_stream_close: bool = True,
        stream_join_timeout: float = 2.0,
    ) -> None:
        self.llm = llm
        self.response_format = response_format
        self.close_mcps_on_finish = close_mcps_on_finish
        self.stream_queue_maxsize = max(1, int(stream_queue_maxsize))
        self.cancel_on_stream_close = bool(cancel_on_stream_close)
        self.stream_join_timeout = max(0.0, float(stream_join_timeout))
        # Retained for compatibility only. Progress narration is composed
        # from the run's own tool calls and results, so nothing here is
        # ever called — turning narration on no longer doubles the model
        # calls a run makes.
        self.decision_llm = decision_llm
        self.progress_summaries = progress_summaries
        self.prompt = prompt
        self.tools = list(tools or [])
        self.mcps = list(mcps or [])
        self.required_tools = list(required_tools or [])
        self.require_tool_call = bool(require_tool_call)
        self.max_required_tool_text_chars = max(
            0, int(max_required_tool_text_chars or 0)
        )
        self.max_completion_text_chars = max(
            0, int(max_completion_text_chars or 0)
        )
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
            deferred_tools=deferred_tools,
            lockdown=lockdown,
            context_window_tokens=context_window_tokens,
            fixed_prefix_tokens=fixed_prefix_tokens,
            max_tool_output_chars=max_tool_output_chars,
            max_tool_output_group_chars=max_tool_output_group_chars,
            tool_output_dir=tool_output_dir,
            reminder=reminder,
            evict_prior_tool_outputs=evict_prior_tool_outputs,
            verify_before_stop=verify_before_stop,
            session_runtime_state=session_runtime_state,
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
        self.run_id = str(uuid4())
        self._event_sequence = 0

    def registry(self) -> ToolRegistry:
        return construct_tool_registry(tools=self.tools, mcps=self.mcps)

    def build_tool_schemas(self) -> list[dict[str, Any]]:
        return build_tool_schemas(self.registry())

    def emit(
        self, state: RuntimeState, event_type: str, message: str, **payload: Any
    ) -> None:
        with self._emit_lock:
            self._event_sequence += 1
            payload.setdefault("run_id", self.run_id)
            payload.setdefault("session_id", self.session_id)
            payload.setdefault("sequence", self._event_sequence)
            if "call_id" in payload:
                payload.setdefault("tool_call_id", payload["call_id"])
            event = AgentEvent(type=event_type, message=message, payload=payload)
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
                metadata={
                    "source": "planner", "planner_tool": planner.name,
                    "internal": True,
                },
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
        model_output_limit: int | None = None,
    ) -> tuple[ToolResult | None, Message]:
        """Execute a single tool call and return (tool_result, message).

        Returns (None, error_message) for hallucinated tools and for calls
        blocked by the permission engine / a hook.
        """
        # Defined up front so the recording line below can never NameError on an
        # early-return path that skipped the duplicate gate.
        signature: tuple[str, str] | None = None
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

        # ── Argument gate ────────────────────────────────────────────────
        # A structured call arrives already parsed, so the healing path never
        # inspects it — but a weak model produces broken arguments there too.
        # Repair what is recoverable; refuse what is not, and say which
        # argument is missing so the next step can supply it. Running a search
        # with no query returns the whole corpus, and an answer written from
        # that is about everything except the question.
        argument_error = self.check_arguments(tool, tool_call)
        if argument_error:
            self.emit(
                state,
                "tool_arguments_rejected",
                f"Tool call missing arguments: {tool_call.name}",
                tool=tool_call.name,
                arguments=dict(tool_call.arguments or {}),
                iteration=iteration,
            )
            return None, Message(
                role="tool",
                name=tool_call.name,
                content=argument_error,
                metadata={
                    "tool_call_id": tool_call_record["id"],
                    "error": "missing_required_arguments",
                },
            )

        # ── Duplicate-call gate ─────────────────────────────────────────────
        # A weak model re-issues a read it already ran this turn — the
        # dithering that made one benchmark run 10 tool calls where 3 sufficed
        # (3× the tokens, 5× the latency). For a READ-ONLY tool whose exact
        # (name, arguments) already executed this run, skip the re-execution
        # entirely and point the model at the result it already has. Scoped to
        # read-only so a deliberate re-run of a mutating tool (a poll, a retry)
        # is never suppressed; the first identical read still runs in full.
        signature = self.readonly_call_signature(tool, tool_call)
        if signature is not None and signature in state.executed_readonly_calls:
            self.emit(
                state,
                "tool_skipped_duplicate",
                f"Skipped repeat call: {tool_call.name}",
                tool=tool_call.name,
                iteration=iteration,
            )
            note = (
                f"[Already ran: {tool_call.name} was called with these exact "
                f"arguments earlier in this turn. Its result is already above "
                f"in this conversation — reuse it. This call was NOT run again. "
                f"Do not repeat it; answer from the result you have, or call "
                f"{tool_call.name} with different arguments.]"
            )
            return None, Message(
                role="tool",
                name=tool_call.name,
                content=note,
                metadata={
                    "tool_call_id": tool_call_record["id"],
                    "duplicate_suppressed": True,
                },
            )

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
                # A denial is FINAL — say so, or the model reads "not run" as a
                # transient failure and retries the same call, re-prompting the
                # human on every loop. Tell it to stop (reference-K.2 style).
                f"Tool '{tool_call.name}' was DENIED by a human and was NOT run "
                f"— {reason}. This decision is final: do NOT retry it, rephrase "
                "it, or pursue the same goal another way. Silence is not consent. "
                "Stop and tell the user the action was declined."
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
                chunk_metadata=safe_tool_event_metadata(chunk.metadata),
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

        model_output = self.model_visible_tool_output(
            tool_result,
            arguments=tool_call.arguments,
            seen=state.seen_tool_outputs,
            limit_override=model_output_limit,
        )
        tool_result.tool_call_id = tool_call_record["id"]
        msg = Message(
            role="tool",
            name=tool_call.name,
            content=model_output,
            tool_call_id=tool_call_record["id"],
            metadata={
                **dict(tool_result.metadata),
            },
        )
        # Record a successful read-only call so an identical repeat this run is
        # skipped by the duplicate gate above instead of re-executed.
        if signature is not None:
            state.executed_readonly_calls.add(signature)
        # Feed the verify-on-stop gate: an edit (a non-read-only tool that
        # touched a verifiable path) dirties the workspace; a verify command's
        # exit code records pass/fail. `signature is not None` == read-only.
        if state.verify_gate is not None:
            md = dict(tool_result.metadata or {})
            arguments = getattr(tool_call, "arguments", None) or {}
            state.verify_gate.note_tool(
                read_only=signature is not None,
                paths=[str(p) for p in _declared_paths(md)],
                command=str(md.get("command") or arguments.get("command") or ""),
                exit_code=md.get("exit_code"),
                output=tool_result.output if isinstance(tool_result.output, str) else "",
                ok=md.get("ok"),
            )
        self.emit(
            state,
            "tool_completed",
            f"Tool completed: {tool_call.name}",
            tool=tool_call.name,
            call_id=tool_call_record["id"],
            group_id=group_id,
            output=tool_result.output,
            output_chars=len(tool_result.output),
            model_output_chars=len(model_output),
            model_output_reduced=model_output != tool_result.output,
            metadata=safe_tool_event_metadata(tool_result.metadata),
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
        group_output_limit = None
        if (
            self.max_tool_output_chars > 0
            and self.max_tool_output_group_chars > 0
            and tool_calls
        ):
            group_output_limit = max(
                1, self.max_tool_output_group_chars // len(tool_calls)
            )

        def _make_context() -> ToolContext:
            return ToolContext(
                prompt=user_prompt,
                system_prompt=base_prompt,
                metadata=dict(self.metadata),
                state=shared_state,
                session_id=self.session_id,
            )

        # Only read-only calls may run concurrently. Writes/sends/mutations
        # keep their order — two edit_file calls to the same path racing
        # across isolated state copies would silently lose one. When every
        # call in the group reads, the whole group parallelizes (the common
        # fan-out: several greps/reads at once); a mixed group runs serially
        # to preserve write ordering.
        read_flags = self.read_only_calls(tool_calls, registry)
        group_is_parallel_safe = all(read_flags)
        if (
            self.parallel_tool_execution
            and len(tool_calls) > 1
            and group_is_parallel_safe
        ):
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
                        model_output_limit=group_output_limit,
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
                if tool_result is not None:
                    vision = self.vision_followup(tool_result, tool_calls[idx].name)
                    if vision is not None:
                        state.messages.append(vision)
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
                    model_output_limit=group_output_limit,
                )
                if tool_result is not None:
                    state.tool_results.append(tool_result)
                    results.append(tool_result)
                state.messages.append(msg)
                if tool_result is not None:
                    # A tool that returned an image gets it in front of the
                    # model's eyes on the next step, as a user-turn block —
                    # the bridge computer_use always assumed existed.
                    vision = self.vision_followup(tool_result, tc.name)
                    if vision is not None:
                        state.messages.append(vision)

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
        """Say what the agent is about to do.

        **The model's own words come first.** A model that calls a tool
        usually says why in the same response — "I have what I need, I'll
        build the PDF now" — and that sentence is better than any label
        this function could compose, was already paid for, and improves on
        its own as the model does. Discarding it to write "Running
        read_file" is throwing away the best sentence available and
        replacing it with a worse one.

        When it said nothing, a configured ``decision_llm`` is asked to write
        the line instead. That is the case this exists for: a small model
        spends its whole completion on the tool call — 14 to 16 tokens,
        measured — so there is no sentence to prefer, and "Searching echo."
        is all a composed label can honestly say. A second model that can see
        the request and the call writes what a person actually wants to read.

        With no ``decision_llm`` configured nothing extra is called and the
        composed label stands. Three sources, in descending order of how much
        they know, and the run costs an extra completion only if you asked
        for one.
        """
        if not self.progress_summaries:
            return ""

        spoken = _first_sentences(response.content)
        if _looks_like_prose(spoken):
            return spoken

        calls = list(response.tool_calls or [])
        if not calls:
            return ""

        narrated = self._narrate_with_decision_model(
            state=state,
            prompt=self._decision_prompt(response, user_prompt, state),
            purpose="agent_decision_summary",
            iteration=iteration,
        )
        if _looks_like_prose(narrated):
            return narrated

        actions = [
            summarize(call.name, dict(call.arguments or {})).present_label()
            for call in calls
        ]
        return _join_clauses(actions) + "."

    def _decision_prompt(
        self, response: LLMResponse, user_prompt: str, state: RuntimeState
    ) -> str:
        """The three short things needed to write one line — and nothing else.

        The earlier version of this fed the model the last ten messages at
        1,400 characters each: up to 14,000 characters of conversation, per
        narrated step, on top of a second call for the observation. That was
        roughly 8,000 tokens an iteration — enough to double the cost of a
        turn to caption it — and it is why the whole mechanism was removed.

        Almost none of it was needed. To write "Content module has all 23
        sections. Now let me build the PDF generator" you need what was asked,
        what the last step found, and what is about to run. The last step's
        finding is already summarised in ``last_observation`` — a sentence the
        runtime composed for free — so the conversation itself never has to be
        sent.

        That is about 550 characters, against 14,000. The tool payloads, which
        are the expensive part, are never included at all: this line describes
        an intention, and the results are not known yet anyway.
        """
        actions = "\n".join(
            f"- {call.name}({_bounded(dict(call.arguments or {}), 250)})"
            for call in (response.tool_calls or [])
        )
        last = _bounded(getattr(state, "last_observation", "") or "", 250)
        return f"""Write one short line for a person watching an agent work.

They asked: {_bounded(user_prompt, 250)}

Last step: {last or "nothing yet — this is the first step"}

About to run:
{actions}

Two or three sentences, 35-60 words, first person, present tense. Say what
you are about to do and what you are looking for, and connect it to what the
last step turned up. Name the specific thing you are acting on. Do not invent
results and do not say what the tool will return.""".strip()

    def _narrate_with_decision_model(
        self,
        *,
        state: RuntimeState,
        prompt: str,
        purpose: str,
        iteration: int,
    ) -> str:
        """Ask the decision model for one line of public narration.

        **Only runs when a ``decision_llm`` was explicitly passed.** With none
        configured this is never reached, and a run makes exactly as many
        model calls as it did before — narration falls back to a composed
        label, which costs nothing.

        That gate is the whole design. An earlier version defaulted to the
        main model and narrated every step whether or not anyone had asked
        for it, which is an extra completion per iteration for a line of UI
        text. Opt in and it is a real second model; opt out and it does not
        exist.

        Runs without tools and without streaming, and never interrupts the
        agent: a failure emits a diagnostic and returns empty, so the caller
        falls through to the composed label.
        """
        if self.decision_llm is None or not self.progress_summaries:
            return ""
        try:
            result = self.decision_llm.complete(
                messages=[Message(role="user", content=prompt)],
                tools=[],
                system_prompt=(
                    "You narrate an agent's work for the person watching it, "
                    "in the agent's own voice — first person, present tense, "
                    "plain language. Two or three sentences. Say what you are "
                    "doing, what it follows from, and what you expect it to "
                    "settle. Be specific: name the thing being acted on. "
                    "Never a bare label, never a heading, never markdown, "
                    "never backticks. Use only what you are shown — do not "
                    "invent results, do not claim to have found anything you "
                    "have not been told, and do not reveal private reasoning."
                ),
                metadata={
                    **dict(self.metadata),
                    "purpose": purpose,
                    "iteration": iteration,
                },
            )
            # Narration is a real model call — its tokens count. Without this
            # the run's usage total (and any Budget watching it) under-reports
            # by one completion per narrated step.
            usage = getattr(result, "usage", None)
            if usage:
                self.track_usage(state, result, iteration)
            return _first_sentences(getattr(result, "content", ""))
        except Exception as exc:                              # noqa: BLE001
            self.emit(
                state,
                "progress_summary_failed",
                "Progress summary generation failed",
                purpose=purpose,
                iteration=iteration,
                error=str(exc),
            )
            return ""

    def _observation_prompt(
        self, tool_results: list[ToolResult], user_prompt: str
    ) -> str:
        """What the decision model is shown to describe a finished step.

        Unlike the decision prompt, this one has to see something of the
        result — an observation that cannot look at what came back can only
        restate the tool's name, which is the failure being fixed.

        So each result contributes a bounded head, not its body. 500
        characters is enough to say "fifteen entries, mostly victim alerts"
        and nowhere near enough to re-send a corpus. The full result is
        already in the conversation for the agent itself; this copy exists
        only to write one paragraph about it.
        """
        rendered = "\n\n".join(
            f"{result.name} -> "
            + ("FAILED: " if _result_failed(result) else "")
            + (_bounded(result.output, 500) or "[no output]")
            for result in tool_results
        )
        return f"""Write a short progress note for a person watching an agent work.

They asked: {_bounded(user_prompt, 200)}

What just came back:
{rendered}

Two or three sentences, 35-60 words, first person, past tense. Say what you
found, how much of it there is, and whether it answers what was asked. If a
call failed, lead with that. Describe only what is shown above — do not add
detail you were not given and do not say what you will do next."""

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

        Always composed, never a model call. Narration spends its one
        completion per step on the DECISION line — the forward-looking one a
        watcher can act on; the observation is assembled from the results'
        own names, arguments and declared metadata, which is factual and
        free. (An earlier version narrated both, doubling the per-step
        narration cost for a line that mostly restated tool output.)
        """
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
                # What came back, when the tool chose to say. Silence here
                # means the tool declared nothing, not that nothing happened.
                detail = _describe_result(result)
                clauses.append(f"{label} — {detail}" if detail else label)
        return _join_clauses(clauses) + "."

    def _complete_with_retry(
        self,
        *,
        state: RuntimeState,
        messages: list[Message],
        tools: list[dict[str, Any]],
        base_prompt: str,
        require_tool_call: bool = False,
    ) -> LLMResponse:
        from shipit_agent.action_detection import RepetitionGuard

        repetition_guard = RepetitionGuard()
        provisional_chars = 0
        # Tool schemas being available does not mean this completion will call
        # one. Native structured providers can produce the final answer while
        # those schemas remain advertised, so gating on ``not tools`` silently
        # disables token streaming for normal agent answers.
        expose_text_deltas = self.guardrails is None

        # When the LLM adapter supports streaming via ``text_delta_callback``,
        # emit each text chunk as a ``text_delta`` event so the SSE adapter
        # downstream can forward tokens inline as they arrive. The callback
        # runs on the same thread that called complete(), so emit() is safe.
        def _on_text_delta(chunk: str) -> bool | None:
            nonlocal provisional_chars
            if not chunk:
                return
            provisional_chars += len(chunk)
            if repetition_guard.add(chunk):
                return False
            if (
                require_tool_call
                and self.max_required_tool_text_chars
                and provisional_chars >= self.max_required_tool_text_chars
            ):
                return False
            if (
                self.max_completion_text_chars
                and provisional_chars >= self.max_completion_text_chars
            ):
                return False
            if expose_text_deltas:
                self.emit(state, "text_delta", "", chunk=chunk)
            return None

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
        from shipit_agent.llms.base import accepts_explicit_kwarg
        if require_tool_call and accepts_explicit_kwarg(
            self.llm.complete, "require_tool_call"
        ):
            complete_kwargs["require_tool_call"] = True
        # Only pass the streaming callback to adapters that accept it; older
        # custom adapters keep working unchanged (no inline streaming).
        # A completion offered tools may end with a tool call. Its text is
        # step narration, not part of the final answer; streaming it through
        # the answer channel produced one visible "[Executing Tool Calls]"
        # block per iteration. Only the forced text/final completion streams
        # answer deltas. Tool-step prose is surfaced once as agent_decision.
        if self._llm_streams_text:
            complete_kwargs["text_delta_callback"] = _on_text_delta
        # Per-request timeout, only for adapters that can honour it. A hung
        # connection without one hangs the run — cancel() can't interrupt a
        # blocked complete() call.
        if self.retry_policy.request_timeout is not None and accepts_kwarg(
            self.llm.complete, "timeout"
        ):
            complete_kwargs["timeout"] = self.retry_policy.request_timeout
        # Native structured output — but only when this completion sends no
        # tools. JSON-mode suppresses tool calls, so applying it mid-loop
        # would stop the model acting; on the final/synthesis turn (tools
        # empty) it is exactly right, and it guarantees parseable JSON where
        # the provider supports it (the prompt+parse path stays the fallback).
        if (
            self.response_format
            and not tools
            and accepts_kwarg(self.llm.complete, "response_format")
        ):
            complete_kwargs["response_format"] = self.response_format

        attempt = 0
        while True:
            try:
                return self.llm.complete(**complete_kwargs)
            except self.retry_policy.retry_on_exceptions as exc:
                if attempt >= self.retry_policy.max_llm_retries:
                    raise
                attempt += 1
                # A failed attempt may have streamed partial output; reset the
                # tool-input parsers so the retry starts from clean state
                # instead of appending fragments onto a dead parse.
                parsers.clear()
                emitted.clear()
                delay = self.retry_policy.llm_retry_delay(attempt)
                self.emit(
                    state,
                    "llm_retry",
                    "Retrying LLM completion",
                    attempt=attempt,
                    error=str(exc),
                    delay=round(delay, 3),
                )
                if delay > 0:
                    time.sleep(delay)

    def run(
        self,
        user_prompt: str,
        *,
        user_content: list[dict[str, Any]] | None = None,
    ) -> tuple[RuntimeState, LLMResponse]:
        # Guarantee MCP cleanup even if registry construction (which opens MCP
        # transports) or the agent loop raises.
        #
        # ``user_content`` is the multimodal form of the same turn: content
        # blocks (text + images/documents) that become the user message,
        # while ``user_prompt`` stays the plain text used for guardrails,
        # planning, tool context and events.
        with session_run_lock(self.session_store, self.session_id):
            try:
                return self._run_inner(user_prompt, user_content=user_content)
            finally:
                if self.close_mcps_on_finish:
                    self.close_mcps()

    def _run_inner(
        self,
        user_prompt: str,
        *,
        user_content: list[dict[str, Any]] | None = None,
    ) -> tuple[RuntimeState, LLMResponse]:
        state = RuntimeState()
        shared_state: dict[str, Any] = {}

        # Verify-on-stop gate for this run (opt-in). The ledger lives under the
        # project's .shipit dir when there's a workspace, else in memory.
        if self.verify_before_stop:
            from pathlib import Path

            from shipit_agent.verify import VerifyGate

            root = VerifyGate.project_root_from_output_dir(self.tool_output_dir)
            db = (
                str(Path(root) / ".shipit" / "verify.db")
                if root not in ("", ".")
                else ":memory:"
            )
            try:
                state.verify_gate = VerifyGate(
                    session_id=self.session_id, root=root, db_path=db
                )
            except Exception:  # noqa: BLE001 — a broken gate must never break a run
                state.verify_gate = None

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
        initially_required = self.initial_required_tool_names(user_prompt, registry)
        if initially_required:
            shared_state["forced_tool_names"] = initially_required
        elif self.require_tool_call and list(registry.values()):
            shared_state["force_any_tool"] = True
        tool_prompt = build_tools_prompt(
            registry.values(), connections=self.connections.all(), mcps=self.mcps,
            supports_parallel_tool_calls=self.model_supports_parallel_tool_calls(),
        )
        base_prompt = (
            self.prompt if not tool_prompt else f"{self.prompt}\n\n{tool_prompt}"
        )
        existing_session = self.session_store.load(self.session_id)
        if existing_session:
            self.token_calibrator.restore(
                existing_session.metadata.get("token_calibration")
            )
            stored_checkpoint = existing_session.metadata.get(
                "compaction_checkpoint"
            )
            if (
                self.context_window_tokens >= 0
                and isinstance(stored_checkpoint, dict)
                and not self.compactor().latest()
            ):
                from shipit_agent.compaction import CompactionCheckpoint

                checkpoint = CompactionCheckpoint.from_dict(stored_checkpoint)
                if checkpoint.summary and checkpoint.compacted_to <= len(
                    existing_session.messages
                ):
                    self.compactor().checkpoints.append(checkpoint)
            prior_messages = existing_session.messages
        elif self.history_messages:
            prior_messages = self.history_messages
        else:
            prior_messages = []
        # Prior turns are re-sent in full on every request of this turn. Their
        # tool payloads have already been read and written into the answers
        # below them, so what they buy now is nothing and what they cost is
        # their whole length, every step. The calls and arguments stay — those
        # are what stop the model searching for the same thing twice.
        #
        # Eviction is a per-REQUEST view only. The originals are kept aside
        # and written back at save time — persisting the stubs would destroy
        # on disk what an earlier turn retrieved, for every future reader of
        # this session (replay, audit, the next turn's own eviction pass).
        original_prior = [m for m in prior_messages if m.role != "system"]
        if self.evict_prior_tool_outputs:
            prior_messages = evict_prior_tool_outputs(list(prior_messages))
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
        state.messages.append(
            Message(role="user", content=user_content or user_prompt)
        )

        self.emit(state, "run_started", "Agent run started", prompt=user_prompt)

        selected_skills = self.metadata.get("selected_skills", [])
        if isinstance(selected_skills, list) and selected_skills:
            skill_ids = [
                str(skill.get("id", ""))
                for skill in selected_skills
                if isinstance(skill, dict) and skill.get("id")
            ]
            self.emit(
                state,
                "skills_selected",
                "Skills selected: " + ", ".join(skill_ids),
                skills=[dict(skill) for skill in selected_skills if isinstance(skill, dict)],
                skill_ids=skill_ids,
                injected_tools=list(self.metadata.get("used_skill_tools", [])),
                count=len(skill_ids),
            )

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
                    core_tools, connections=self.connections.all(),
                    supports_parallel_tool_calls=self.model_supports_parallel_tool_calls(),
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

        # Deferred tool loading: advertise core schemas only; everything else
        # is a name in the index until tool_search (or a direct call) loads
        # it. Mirrors the code-mode rebuild above — code mode wins if both
        # are on (setup_deferral returns "" in that case).
        deferral_index = self.setup_deferral(registry, shared_state)
        if deferral_index:
            from shipit_agent.deferral import DEFERRED_NAMES_KEY

            deferred_names = shared_state.get(DEFERRED_NAMES_KEY) or set()
            resident_tools = [
                tool
                for tool in registry.values()
                if getattr(tool, "name", "") not in deferred_names
            ]
            resident_prompt = build_tools_prompt(
                resident_tools, connections=self.connections.all(), mcps=self.mcps,
                supports_parallel_tool_calls=self.model_supports_parallel_tool_calls(),
            )
            base_prompt = "\n\n".join(
                part
                for part in (self.prompt, resident_prompt, deferral_index)
                if part
            )
            state.messages[0] = Message(
                role="system", content=base_prompt, metadata=dict(self.metadata)
            )

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
            # Deferred loading grows the advertised set mid-run, so the
            # selection is re-evaluated every step (a no-op when off).
            force_text = bool(
                shared_state.pop("force_text_after_duplicate", False)
                or shared_state.pop("force_text_after_malformed", False)
            )
            forced_names = set(shared_state.get("forced_tool_names") or ())
            force_any_tool = bool(shared_state.get("force_any_tool"))
            active_schemas = (
                [] if force_text
                else self.select_step_schemas(tool_schemas, shared_state)
            )
            if forced_names:
                active_schemas = [
                    schema for schema in active_schemas
                    if str((schema.get("function") or {}).get("name", ""))
                    in forced_names
                ]
            # The final cycle is schema-free. Account for exactly what this
            # cycle will advertise before deciding whether history still fits.
            schemas_for_budget = (
                []
                if iteration == self.max_iterations and self.max_iterations > 1
                else active_schemas
            )
            self.account_request_overhead(schemas_for_budget)
            if self.hooks:
                self.hooks.run_before_llm(list(state.messages), active_schemas)

            compacted_messages = self.compact(
                state, list(state.messages), iteration, shared_state
            )
            # Re-ground after a fresh compaction: append current contents of
            # the files it summarized away, so the model works from the code
            # (persisted into state.messages, so it survives to later steps).
            regrounding = self.regrounding_messages(shared_state)
            if regrounding:
                state.messages.extend(regrounding)
                compacted_messages = [*compacted_messages, *regrounding]

            compacted_messages = self.label_user_turns(compacted_messages)

            # Placed last, after the whole conversation, because that is where
            # a model attends most reliably. Appended to this per-call copy —
            # never to state.messages — so it is rebuilt each step and cannot
            # stack up across the run.
            compacted_messages, step_schemas = self.step_request(
                messages=compacted_messages,
                tool_schemas=active_schemas,
                iteration=iteration,
                ran_tools=bool(state.tool_results),
            )
            if forced_names or force_any_tool:
                compacted_messages.append(Message(
                    role="user",
                    content=(
                        ("Execute the required registered tool now: "
                         + ", ".join(sorted(forced_names))
                         if forced_names else
                         "Execute the most appropriate available tool now")
                        + ". Emit the structured call, not prose or a simulated result."
                    ),
                    metadata={"internal": True, "kind": "required_tool"},
                ))

            self.emit(
                state,
                "step_started",
                "LLM completion started",
                tool_count=len(step_schemas),
                iteration=iteration,
            )
            response = self._complete_with_retry(
                state=state,
                messages=compacted_messages,
                tools=step_schemas,
                base_prompt=base_prompt,
                require_tool_call=bool(
                    (forced_names or force_any_tool) and step_schemas
                ),
            )
            self.track_usage(state, response, iteration)
            # Learn this model's real tokens-per-char from the view we just
            # sent, so the compaction trigger is calibrated, not guessed.
            self.calibrate_from_completion(compacted_messages, response)

            # Self-healing: small models often emit the tool call as TEXT.
            # Promote declared-tool calls out of the content (response-side
            # only; the promoted span is removed, everything else kept).
            # Arguments are checked against each tool's own schema, and the
            # reasoning channel is searched when the model wrote its call
            # into its thinking instead of its answer.
            self.heal(state, response, registry, iteration)

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
                        decision_summary,
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
                        generated_by_model=bool(response.content),
                        summary_source=(
                            "model_text" if response.content else "tool_call"
                        ),
                    )

            if not response.tool_calls:
                if force_any_tool and iteration < self.max_iterations:
                    state.messages.append(Message(
                        role="assistant",
                        content="[Unverified response discarded: no required tool executed.]",
                    ))
                    state.messages.append(Message(
                        role="user",
                        content=(
                            "A registered tool must execute before answering. "
                            "Call the best available tool now; do not simulate its result."
                        ),
                        metadata={"internal": True, "kind": "required_tool_retry"},
                    ))
                    self.emit(
                        state, "tool_call_healed", "Retrying required tool use",
                        nudge=True, iteration=iteration,
                    )
                    continue
                executed = {result.name for result in state.tool_results}
                missing_required = sorted(forced_names - executed)
                missing_requested = self.missing_requested_tools(
                    user_prompt, registry, state.tool_results
                )
                missing_requested = sorted(set(missing_requested) | set(missing_required))
                if missing_requested and iteration < self.max_iterations:
                    self.record_requested_tool_nudge(missing_requested)
                    shared_state["forced_tool_names"] = set(missing_requested)
                    state.messages.append(Message(
                        role="assistant",
                        content="[Unverified response discarded: no requested tool executed.]",
                    ))
                    state.messages.append(Message(
                        role="user",
                        content=(
                            "The requested registered tool did not execute. Call "
                            + ", ".join(missing_requested)
                            + " now; do not simulate or invent its result."
                        ),
                        metadata={"internal": True, "kind": "requested_tool_retry"},
                    ))
                    appended_response_id = id(response)
                    self.emit(
                        state,
                        "tool_call_healed",
                        "Retrying an explicitly requested tool",
                        tools=missing_requested,
                        nudge=True,
                        iteration=iteration,
                    )
                    continue
                # A syntactically attempted call that healing could not safely
                # promote gets one bounded retry. Plain prose is never
                # classified by wording and always ends the turn normally.
                if self.should_nudge(
                    response,
                    has_tools=bool(tool_schemas),
                    last=iteration >= self.max_iterations,
                    tool_names=tuple(tool.name for tool in registry.values()),
                ):
                    self.record_nudge(response)
                    state.messages.append(
                        Message(
                            role="assistant",
                            content=self.malformed_attempt_context(response),
                        )
                    )
                    state.messages.append(
                        Message(
                            role="user", content=self.NUDGE_TEXT,
                            metadata={"internal": True, "kind": "tool_call_retry"},
                        )
                    )
                    appended_response_id = id(response)
                    self.emit(
                        state,
                        "tool_call_healed",
                        "Nudged: malformed tool call",
                        nudge=True,
                        iteration=iteration,
                    )
                    continue
                if self.should_force_text_recovery(
                    response,
                    has_tools=bool(tool_schemas),
                    last=iteration >= self.max_iterations,
                    tool_names=tuple(tool.name for tool in registry.values()),
                ):
                    shared_state["force_text_after_malformed"] = True
                    state.messages.append(
                        Message(
                            role="assistant",
                            content=self.malformed_attempt_context(response),
                        )
                    )
                    state.messages.append(
                        Message(
                            role="user",
                            content=(
                                "The structured action failed twice. Do not call or "
                                "describe any tool now. Answer the original request "
                                "concisely from completed results already above, and "
                                "state what could not be verified."
                            ),
                            metadata={
                                "internal": True,
                                "kind": "text_only_recovery",
                            },
                        )
                    )
                    self.emit(
                        state,
                        "tool_call_healed",
                        "Switching to text-only recovery after repeated malformed calls",
                        recovery="text_only",
                        iteration=iteration,
                    )
                    continue

                # Verify-on-stop: the model is about to finish, but if this turn
                # edited code and there's no fresh passing test evidence, send it
                # back to run the tests instead of letting it claim "done".
                if state.verify_gate is not None:
                    if iteration < self.max_iterations:
                        verify_nudge = state.verify_gate.stop_nudge()
                        if verify_nudge:
                            if response.content:
                                state.messages.append(
                                    Message(role="assistant", content=response.content)
                                )
                                appended_response_id = id(response)
                            state.messages.append(
                                Message(
                                    role="user", content=verify_nudge,
                                    metadata={"internal": True, "kind": "verify_retry"},
                                )
                            )
                            self.emit(
                                state,
                                "verify_required",
                                "Edited code without passing verification — running tests",
                                iteration=iteration,
                            )
                            continue
                    elif state.verify_gate.would_nudge():
                        # No steps left to run the tests, but the turn edited code
                        # with no passing evidence — surface it rather than let a
                        # silent unverified "done" through (the ledger's whole point).
                        self.emit(
                            state,
                            "verify_skipped",
                            "Edited code but ran out of steps before verification passed",
                            iteration=iteration,
                        )

                break

            tool_call_records = self.assign_tool_call_ids(
                response.tool_calls, state.messages, iteration
            )
            state.messages.append(
                Message(
                    role="assistant",
                    content=response.content,
                    tool_calls=list(response.tool_calls),
                    metadata={
                        **dict(response.metadata),
                        **(
                            {"reasoning_content": response.reasoning_content}
                            if response.reasoning_content
                            else {}
                        ),
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
            if iteration_results:
                shared_state.pop("force_any_tool", None)
            if forced_names:
                remaining_forced = forced_names - {
                    result.name for result in iteration_results
                }
                if remaining_forced:
                    shared_state["forced_tool_names"] = remaining_forced
                else:
                    shared_state.pop("forced_tool_names", None)

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
                # Kept so the next decision line can say what this step found
                # without the conversation being sent to narrate it.
                state.last_observation = observation_summary
                self.emit(
                    state,
                    "agent_observation",
                    observation_summary,
                    summary=observation_summary,
                    iteration=iteration,
                    next_action="evaluate_results",
                    generated_by_model=False,
                )

            if self.force_text_after_duplicate_batch(
                state.messages, tool_call_records
            ):
                shared_state["force_text_after_duplicate"] = True

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

        response.content = self.stable_final_content(state, response.content)

        # Append the final answer unless this exact response was already
        # written inside the loop (model narrated alongside a tool call on the
        # last iteration) — otherwise the text would be duplicated.
        if response.content and id(response) != appended_response_id:
            state.messages.append(
                Message(
                    role="assistant",
                    content=response.content,
                    metadata={
                        **dict(response.metadata),
                        **(
                            {"reasoning_content": response.reasoning_content}
                            if response.reasoning_content
                            else {}
                        ),
                    },
                )
            )

        raw_final_content = response.content
        response.content = self.sanitize_output(state, response.content)
        if response.content != raw_final_content:
            for message in reversed(state.messages):
                if message.role == "assistant" and message.content == raw_final_content:
                    message.content = response.content
                    break

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
        # Reassemble with the ORIGINAL prior turns (see eviction note above):
        # [fresh system] + [unevicted prior] + [everything this run added].
        persisted_messages = [
            state.messages[0],
            *original_prior,
            *state.messages[1 + len(original_prior) :],
        ]
        session_metadata = dict(existing_session.metadata) if existing_session else {}
        session_metadata["token_calibration"] = self.token_calibrator.to_dict()
        latest_checkpoint = (
            self.compactor().latest() if self.context_window_tokens >= 0 else None
        )
        if latest_checkpoint is not None:
            session_metadata["compaction_checkpoint"] = latest_checkpoint.to_dict()
        self.session_store.save(
            SessionRecord(
                session_id=self.session_id,
                messages=persisted_messages,
                metadata=session_metadata,
            )
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
        # A tidy closing accounting: iterations, tool calls, compactions,
        # and token/cost usage. The data was all tracked; this surfaces it
        # as one closing artifact at end of turn.
        summary = self._build_run_summary(state)
        self.emit(state, "run_summary", summary["headline"], **summary)
        self.emit(
            state,
            "run_completed",
            "Agent run completed",
            output=response.content,
            content=response.content,
            format="markdown",
            usage=dict(self._total_usage),
            summary=summary,
            cancelled=self._cancel_event.is_set(),
        )
        # MCP transports are closed by run()'s finally (covers the error path
        # too) — don't close here.
        return state, response

    def stream(
        self,
        user_prompt: str,
        *,
        user_content: list[dict[str, Any]] | None = None,
    ) -> Iterator[AgentEvent]:
        """Run the agent in a background thread and yield events as they're emitted.

        ``user_content`` carries the multimodal form of the turn (image /
        document / text blocks) exactly as :meth:`run` accepts it, so a
        streaming caller can attach images and files too.
        """
        event_queue: queue.Queue[AgentEvent | object] = queue.Queue(
            maxsize=self.stream_queue_maxsize
        )
        sentinel = object()
        completed = threading.Event()

        def _subscriber(event: AgentEvent) -> None:
            while not self.cancelled:
                try:
                    event_queue.put(event, timeout=0.1)
                    return
                except queue.Full:
                    continue

        def _worker() -> None:
            try:
                self.run(user_prompt, user_content=user_content)
            except BaseException as exc:  # noqa: BLE001
                _subscriber(
                    AgentEvent(
                        type="run_failed",
                        message="Agent run failed",
                        payload={
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                            "retryable": isinstance(exc, ConnectionError),
                        },
                    )
                )
            finally:
                completed.set()
                while True:
                    try:
                        event_queue.put(sentinel, timeout=0.1)
                        break
                    except queue.Full:
                        if self.cancelled:
                            break

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
            if not completed.is_set() and self.cancel_on_stream_close:
                self.cancel()
            worker.join(timeout=self.stream_join_timeout)
            self._event_subscriber = None
