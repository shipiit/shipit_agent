from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Callable
from uuid import uuid4

from shipit_agent.construction import construct_tool_registry
from shipit_agent.integrations import CredentialStore
from shipit_agent.llms.base import LLM, LLMResponse
from shipit_agent.mcp import MCPServer
from shipit_agent.models import AgentEvent, Message, ToolResult
from shipit_agent.permissions import PermissionEngine
from shipit_agent.policies import RetryPolicy, RouterPolicy
from shipit_agent.registry import ToolRegistry
from shipit_agent.runtime_core import RuntimeCore, evict_prior_tool_outputs
from shipit_agent.runtime_state import (
    RuntimeState,
    _isolated_tool_state,
    _merge_tool_state,
)
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


class AsyncAgentRuntime(RuntimeCore):
    """Async version of AgentRuntime for use with asyncio/FastAPI/Starlette.

    Mirrors the synchronous AgentRuntime but uses ``await`` for LLM calls
    and tool execution, making it suitable for async web frameworks.

    Example::

        runtime = AsyncAgentRuntime(llm=llm, prompt="You are helpful.")
        state, response = await runtime.run("Hello!")

        async for event in runtime.stream("Hello!"):
            print(event.type, event.message)
    """

    def __init__(
        self,
        *,
        llm: LLM,
        prompt: str,
        tools: list[Tool] | None = None,
        mcps: list[MCPServer] | None = None,
        required_tools: list[str] | None = None,
        max_required_tool_text_chars: int = 2_048,
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
        approvals: Any | None = None,
        guardrails: Any | None = None,
        heal_tool_calls: bool = True,
        reminder: str | None = None,
        evict_prior_tool_outputs: bool = True,
        lockdown: Any = None,
        code_mode: bool = False,
        deferred_tools: Any = False,
    ) -> None:
        self.llm = llm
        self.prompt = prompt
        self.tools = list(tools or [])
        self.mcps = list(mcps or [])
        self.required_tools = list(required_tools or [])
        self.max_required_tool_text_chars = max(
            0, int(max_required_tool_text_chars or 0)
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
        # Everything shared with AgentRuntime — guardrails, lockdown,
        # approvals, healing, usage, compaction — comes from RuntimeCore, so
        # the two loops cannot drift apart again.
        self._init_core(
            approvals=approvals,
            guardrails=guardrails,
            heal_tool_calls=heal_tool_calls,
            lockdown=lockdown,
            code_mode=code_mode,
            deferred_tools=deferred_tools,
            context_window_tokens=context_window_tokens,
            fixed_prefix_tokens=fixed_prefix_tokens,
            max_tool_output_chars=max_tool_output_chars,
            max_tool_output_group_chars=max_tool_output_group_chars,
            tool_output_dir=tool_output_dir,
            reminder=reminder,
            evict_prior_tool_outputs=evict_prior_tool_outputs,
        )
        self._event_subscriber: Callable[[AgentEvent], None] | None = None

    def registry(self) -> ToolRegistry:
        return construct_tool_registry(tools=self.tools, mcps=self.mcps)

    def emit(
        self, state: RuntimeState, event_type: str, message: str, **payload: Any
    ) -> None:
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

    async def _complete_async(
        self, *, messages: list[Message], tools: list[dict[str, Any]], base_prompt: str,
        require_tool_call: bool = False,
    ) -> LLMResponse:
        """Run the synchronous LLM.complete in a thread to avoid blocking."""
        from shipit_agent.llms.base import accepts_kwarg

        complete_kwargs: dict[str, Any] = dict(
            messages=messages,
            tools=tools,
            system_prompt=base_prompt,
            metadata=dict(self.metadata),
        )
        from shipit_agent.llms.base import accepts_explicit_kwarg
        if require_tool_call and accepts_explicit_kwarg(
            self.llm.complete, "require_tool_call"
        ):
            complete_kwargs["require_tool_call"] = True
        # Per-request timeout, only for adapters that can honour it — same
        # decision as the sync loop.
        if self.retry_policy.request_timeout is not None and accepts_kwarg(
            self.llm.complete, "timeout"
        ):
            complete_kwargs["timeout"] = self.retry_policy.request_timeout
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.llm.complete(**complete_kwargs),
        )

    async def _complete_with_retry(
        self,
        *,
        state: RuntimeState,
        messages: list[Message],
        tools: list[dict[str, Any]],
        base_prompt: str,
        require_tool_call: bool = False,
    ) -> LLMResponse:
        attempt = 0
        while True:
            try:
                return await self._complete_async(
                    messages=messages, tools=tools, base_prompt=base_prompt,
                    require_tool_call=require_tool_call,
                )
            except self.retry_policy.retry_on_exceptions as exc:
                if attempt >= self.retry_policy.max_llm_retries:
                    raise
                attempt += 1
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
                    await asyncio.sleep(delay)

    async def _run_tool_async(
        self,
        tool_runner: ToolRunner,
        tool_call: Any,
        context: ToolContext,
        output_callback: Callable[[ToolOutputChunk], None] | None = None,
    ) -> ToolResult:
        """Run a tool call in a thread executor."""
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: tool_runner.run_tool_call(tool_call, context, output_callback),
        )
        # Thread-safe output callbacks are queued onto this event loop. Let
        # them drain before the canonical tool_completed event is emitted.
        await asyncio.sleep(0)
        return result

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
        """Mirror of AgentRuntime._defer_tool_call — same shared decision."""
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

    async def _execute_single_tool(
        self,
        *,
        state: RuntimeState,
        registry: ToolRegistry,
        tool_runner: ToolRunner,
        tool_call: Any,
        tool_call_record: dict[str, Any],
        context: ToolContext,
        iteration: int,
        model_output_limit: int | None = None,
    ) -> tuple[ToolResult | None, Message]:
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
        # Mirrors runtime.py: repair recoverable argument names, refuse a
        # call whose required arguments are all absent, and say which one is
        # missing so the next step can supply it.
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

        # ── Duplicate-call gate (see the sync runtime for the rationale) ────
        # Skip an exact repeat of a READ-ONLY call already run this turn — the
        # dithering fix. Mutating tools are never suppressed.
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
        if (
            decision is not None
            and decision.needs_approval
            and getattr(self, "approvals", None) is not None
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
                # Mirrors runtime.py — renderers pair outcomes to calls by
                # (tool, call_id), and the gate can fire before `tool_called`.
                tool=tool_call.name,
                call_id=tool_call_record["id"],
                reason=reason,
                decision=decision.decision.value,
                iteration=iteration,
            )
            content = (
                # A denial is FINAL — say so, or the model retries the same call
                # and re-prompts the human on every loop (reference-K.2 style).
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
        attempt = 0
        output_sequence = 0
        loop = asyncio.get_running_loop()

        def _publish_output(chunk: ToolOutputChunk) -> None:
            nonlocal output_sequence
            output_sequence += 1
            sequence = output_sequence
            attempt_number = attempt + 1

            def _emit_chunk() -> None:
                self.emit(
                    state,
                    "tool_output_delta",
                    f"Tool output: {tool_call.name}",
                    tool=tool_call.name,
                    call_id=tool_call_record["id"],
                    chunk=chunk.text,
                    chunk_metadata=safe_tool_event_metadata(chunk.metadata),
                    sequence=sequence,
                    attempt=attempt_number,
                    iteration=iteration,
                )

            loop.call_soon_threadsafe(_emit_chunk)

        while True:
            self.emit(
                state,
                "tool_output_started",
                f"Tool output started: {tool_call.name}",
                tool=tool_call.name,
                call_id=tool_call_record["id"],
                attempt=attempt + 1,
                buffered=self.guardrails is not None,
                iteration=iteration,
            )
            try:
                tool_result = await self._run_tool_async(
                    tool_runner,
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
                        error=str(exc),
                        iteration=iteration,
                    )
                    tool_result = ToolResult(
                        name=tool_call.name,
                        output=f"Error running tool '{tool_call.name}': {exc}",
                        metadata={"error": str(exc)},
                    )
                    if self.guardrails is None:
                        _publish_output(
                            ToolOutputChunk(tool_result.output, {"error": str(exc)})
                        )
                        await asyncio.sleep(0)
                    break
                attempt += 1
                self.emit(
                    state,
                    "tool_retry",
                    f"Retrying tool: {tool_call.name}",
                    attempt=attempt,
                    error=str(exc),
                    iteration=iteration,
                )

        if self.hooks:
            tool_result = self.hooks.run_after_tool(tool_call.name, tool_result)

        # Guardrails: neutralize indirect injection and redact secrets BEFORE
        # the model reads the result.
        tool_result.output, redacted_secret = self.sanitize_tool_output(
            state, tool_call.name, tool_result.output
        )
        if self.guardrails is not None and tool_result.output:
            _publish_output(ToolOutputChunk(tool_result.output, {"buffered": True}))
            await asyncio.sleep(0)

        # Did this read latch the run into lockdown?
        self.note_lockdown(
            state,
            tool=tool_call.name,
            arguments=dict(tool_call.arguments),
            output_metadata=dict(tool_result.metadata),
            redacted_secret=redacted_secret,
            iteration=iteration,
        )

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
        self.emit(
            state,
            "tool_completed",
            f"Tool completed: {tool_call.name}",
            # Renderers pair an outcome to its call by (tool, call_id); without
            # them this loop's transcript could only guess.
            tool=tool_call.name,
            call_id=tool_call_record["id"],
            output=tool_result.output,
            output_chars=len(tool_result.output),
            model_output_chars=len(model_output),
            model_output_reduced=model_output != tool_result.output,
            metadata=safe_tool_event_metadata(tool_result.metadata),
            iteration=iteration,
        )
        self.note_connection_request(state, tool_call.name, tool_result.metadata)
        self.note_artifacts(state, tool_call.name, tool_result)
        if tool_result.metadata.get("interactive"):
            self.emit(
                state,
                "interactive_request",
                f"Interactive request from {tool_call.name}",
                kind=tool_result.metadata.get("kind"),
                payload=dict(tool_result.metadata),
            )
        return tool_result, msg

    async def run(
        self,
        user_prompt: str,
        *,
        user_content: list[dict[str, Any]] | None = None,
    ) -> tuple[RuntimeState, LLMResponse]:
        # Guarantee MCP cleanup even if registry construction or the loop raises.
        # ``user_content`` mirrors the sync loop: block-shaped user turn,
        # plain text everywhere else.
        try:
            return await self._run_inner(user_prompt, user_content=user_content)
        finally:
            self.close_mcps()

    async def _run_inner(
        self,
        user_prompt: str,
        *,
        user_content: list[dict[str, Any]] | None = None,
    ) -> tuple[RuntimeState, LLMResponse]:
        state = RuntimeState()

        # Guardrails: blocked prompts never reach the LLM.
        user_prompt, refusal = self.check_input(state, user_prompt)
        if refusal is not None:
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

        registry = self.registry()
        # Build the capability control plane before the system prompt so the
        # model sees the same connection/MCP metadata that tools can search.
        shared_state: dict[str, Any] = self.build_shared_state(registry, state)
        initially_required = self.initial_required_tool_names(user_prompt, registry)
        if initially_required:
            shared_state["forced_tool_names"] = initially_required
        tool_prompt = build_tools_prompt(
            registry.values(), connections=self.connections.all(), mcps=self.mcps,
            supports_parallel_tool_calls=self.model_supports_parallel_tool_calls(),
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
        # Earlier turns' tool payloads have already been read into the
        # answers below them; re-sending them costs their whole length on
        # every step of this turn. The calls and arguments stay.
        #
        # Eviction is a per-REQUEST view only — the originals are kept aside
        # and written back at save time. (See sync AgentRuntime for details.)
        original_prior = [m for m in prior_messages if m.role != "system"]
        if self.evict_prior_tool_outputs:
            prior_messages = evict_prior_tool_outputs(list(prior_messages))
        # Exactly one fresh system message at the front; strip any persisted
        # system messages from prior turns so multi-turn sessions don't stack
        # duplicates and grow unbounded. (See sync AgentRuntime for details.)
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
        # Built by RuntimeCore, so both loops publish identical tool state.
        tool_runner = ToolRunner(registry)

        # Deferred tool loading — same decision as the sync loop, made by
        # RuntimeCore: core schemas stay resident, the rest are names in an
        # index until tool_search (or a direct call) loads them.
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

        response = LLMResponse(content="")
        # id() of the response already appended as an assistant message in the
        # loop, so the trailing append doesn't duplicate the final text.
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
            force_text = bool(shared_state.pop("force_text_after_duplicate", False))
            forced_names = set(shared_state.get("forced_tool_names") or ())
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
            if self.hooks:
                self.hooks.run_before_llm(list(state.messages), active_schemas)

            # Mirrors runtime.py: compact when the window demands it (no-op
            # unless context_window_tokens is set), then re-ground.
            compacted_messages = self.compact(
                state, list(state.messages), iteration, shared_state
            )
            regrounding = self.regrounding_messages(shared_state)
            if regrounding:
                state.messages.extend(regrounding)
                compacted_messages = [*compacted_messages, *regrounding]

            compacted_messages = self.label_user_turns(compacted_messages)

            step_messages, step_schemas = self.step_request(
                messages=compacted_messages,
                tool_schemas=active_schemas,
                iteration=iteration,
                ran_tools=bool(state.tool_results),
            )
            if forced_names:
                step_messages.append(Message(
                    role="user",
                    content=(
                        "Execute the required registered tool now: "
                        + ", ".join(sorted(forced_names))
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
            response = await self._complete_with_retry(
                state=state,
                messages=step_messages,
                tools=step_schemas,
                base_prompt=base_prompt,
                require_tool_call=bool(forced_names and step_schemas),
            )
            self.track_usage(state, response, iteration)
            # Learn this model's real tokens-per-char from the view we just
            # sent, so the compaction trigger is calibrated, not guessed.
            self.calibrate_from_completion(step_messages, response)

            # Small models often emit the tool call as text; promote it.
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

            if not response.tool_calls:
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
                    self.emit(
                        state,
                        "tool_call_healed",
                        "Retrying an explicitly requested tool",
                        tools=missing_requested,
                        nudge=True,
                        iteration=iteration,
                    )
                    continue
                # Nudge-on-stall: the model narrated an action and called
                # nothing. One tightly-gated re-prompt recovers the turn.
                if self.should_nudge(
                    response,
                    has_tools=bool(tool_schemas),
                    last=iteration >= self.max_iterations,
                    tool_names=tuple(tool.name for tool in registry.values()),
                ):
                    self.record_nudge(response)
                    state.messages.append(
                        Message(role="assistant", content=response.content)
                    )
                    state.messages.append(Message(
                        role="user", content=self.NUDGE_TEXT,
                        metadata={"internal": True, "kind": "tool_call_retry"},
                    ))
                    self.emit(
                        state,
                        "tool_call_healed",
                        "Nudged: malformed tool call",
                        nudge=True,
                        iteration=iteration,
                    )
                    continue
                break

            tool_call_records = self.assign_tool_call_ids(
                response.tool_calls, state.messages, iteration
            )
            group_output_limit = None
            if (
                self.max_tool_output_chars > 0
                and self.max_tool_output_group_chars > 0
                and response.tool_calls
            ):
                group_output_limit = max(
                    1,
                    self.max_tool_output_group_chars // len(response.tool_calls),
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

            # Only read-only groups fan out — writes keep their order (see
            # runtime.py for the full rationale). Shared decision on
            # RuntimeCore so both loops agree on what is parallel-safe.
            group_is_parallel_safe = all(
                self.read_only_calls(response.tool_calls, registry)
            )
            if (
                self.parallel_tool_execution
                and len(response.tool_calls) > 1
                and group_is_parallel_safe
            ):
                # Run tools concurrently — each on its own isolated copy of
                # shared_state so concurrent writes can't corrupt each other;
                # merged back in original order after all complete.
                isolated_states = [
                    _isolated_tool_state(shared_state) for _ in response.tool_calls
                ]
                tasks = []
                semaphore = asyncio.Semaphore(
                    self.max_tool_concurrency or len(response.tool_calls)
                )

                async def _bounded_tool_call(**kwargs: Any):
                    async with semaphore:
                        return await self._execute_single_tool(**kwargs)

                for idx, tc in enumerate(response.tool_calls):
                    context = ToolContext(
                        prompt=user_prompt,
                        system_prompt=base_prompt,
                        metadata=dict(self.metadata),
                        state=isolated_states[idx],
                        session_id=self.session_id,
                    )
                    tasks.append(
                        _bounded_tool_call(
                            state=state,
                            registry=registry,
                            tool_runner=tool_runner,
                            tool_call=tc,
                            tool_call_record=tool_call_records[idx],
                            context=context,
                            iteration=iteration,
                            model_output_limit=group_output_limit,
                        )
                    )
                results = await asyncio.gather(*tasks)
                for idx, (tool_result, msg) in enumerate(results):
                    _merge_tool_state(shared_state, isolated_states[idx])
                    if tool_result is not None:
                        state.tool_results.append(tool_result)
                    state.messages.append(msg)
                    if tool_result is not None:
                        vision = self.vision_followup(
                            tool_result, response.tool_calls[idx].name
                        )
                        if vision is not None:
                            state.messages.append(vision)
            else:
                for idx, tc in enumerate(response.tool_calls):
                    context = ToolContext(
                        prompt=user_prompt,
                        system_prompt=base_prompt,
                        metadata=dict(self.metadata),
                        state=shared_state,
                        session_id=self.session_id,
                    )
                    tool_result, msg = await self._execute_single_tool(
                        state=state,
                        registry=registry,
                        tool_runner=tool_runner,
                        tool_call=tc,
                        tool_call_record=tool_call_records[idx],
                        context=context,
                        iteration=iteration,
                        model_output_limit=group_output_limit,
                    )
                    if tool_result is not None:
                        state.tool_results.append(tool_result)
                    state.messages.append(msg)
                    if tool_result is not None:
                        # Mirrors runtime.py: an image-bearing tool result is
                        # bridged into a user-turn image block.
                        vision = self.vision_followup(tool_result, tc.name)
                        if vision is not None:
                            state.messages.append(vision)

            if self.force_text_after_duplicate_batch(
                state.messages, tool_call_records
            ):
                shared_state["force_text_after_duplicate"] = True
            if forced_names:
                remaining_forced = forced_names - {
                    result.name for result in state.tool_results
                }
                if remaining_forced:
                    shared_state["forced_tool_names"] = remaining_forced
                else:
                    shared_state.pop("forced_tool_names", None)

        # Summarization if hit iteration cap
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
                summary = await self._complete_with_retry(
                    state=state,
                    messages=list(state.messages),
                    tools=[],
                    base_prompt=base_prompt,
                )
                # Account for the summary turn's tokens + fire the hook.
                self.track_usage(state, summary, self.max_iterations + 1)
                if self.hooks:
                    self.hooks.run_after_llm(summary)
                if summary.content:
                    response = summary
            except Exception:
                pass

        # Skip if this exact response was already appended in the loop.
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

        for tool_result in state.tool_results:
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
        self.session_store.save(
            SessionRecord(session_id=self.session_id, messages=persisted_messages)
        )
        self.surface_give_up(state.tool_results)
        response.content = self.sanitize_output(state, response.content)

        # Closing accounting, same shape as the sync loop.
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
        )

        # MCP transports are closed by run()'s finally (covers the error path).
        return state, response

    async def stream(self, user_prompt: str) -> AsyncIterator[AgentEvent]:
        """Run the agent and yield events as they're emitted."""
        event_queue: asyncio.Queue[AgentEvent | None] = asyncio.Queue()

        def _subscriber(event: AgentEvent) -> None:
            event_queue.put_nowait(event)

        self._event_subscriber = _subscriber

        async def _worker() -> None:
            try:
                await self.run(user_prompt)
            finally:
                await event_queue.put(None)

        task = asyncio.create_task(_worker())
        try:
            while True:
                item = await event_queue.get()
                if item is None:
                    break
                yield item
        finally:
            await task
            self._event_subscriber = None
