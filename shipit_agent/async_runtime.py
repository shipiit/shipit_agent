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
from shipit_agent.runtime_core import RuntimeCore
from shipit_agent.runtime import (
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
        max_tool_output_group_chars: int = 0,
        tool_output_dir: str | None = None,
        replan_interval: int = 0,
        permissions: PermissionEngine | None = None,
        approvals: Any | None = None,
        guardrails: Any | None = None,
        heal_tool_calls: bool = True,
        lockdown: Any = None,
        code_mode: bool = False,
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
            context_window_tokens=context_window_tokens,
            max_tool_output_chars=max_tool_output_chars,
            max_tool_output_group_chars=max_tool_output_group_chars,
            tool_output_dir=tool_output_dir,
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
        self, *, messages: list[Message], tools: list[dict[str, Any]], base_prompt: str
    ) -> LLMResponse:
        """Run the synchronous LLM.complete in a thread to avoid blocking."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.llm.complete(
                messages=messages,
                tools=tools,
                system_prompt=base_prompt,
                metadata=dict(self.metadata),
            ),
        )

    async def _complete_with_retry(
        self,
        *,
        state: RuntimeState,
        messages: list[Message],
        tools: list[dict[str, Any]],
        base_prompt: str,
    ) -> LLMResponse:
        attempt = 0
        while True:
            try:
                return await self._complete_async(
                    messages=messages, tools=tools, base_prompt=base_prompt
                )
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

    async def run(self, user_prompt: str) -> tuple[RuntimeState, LLMResponse]:
        # Guarantee MCP cleanup even if registry construction or the loop raises.
        try:
            return await self._run_inner(user_prompt)
        finally:
            self.close_mcps()

    async def _run_inner(self, user_prompt: str) -> tuple[RuntimeState, LLMResponse]:
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
        # Exactly one fresh system message at the front; strip any persisted
        # system messages from prior turns so multi-turn sessions don't stack
        # duplicates and grow unbounded. (See sync AgentRuntime for details.)
        state.messages.append(
            Message(role="system", content=base_prompt, metadata=dict(self.metadata))
        )
        state.messages.extend(m for m in prior_messages if m.role != "system")
        state.messages.append(Message(role="user", content=user_prompt))

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
            if self.hooks:
                self.hooks.run_before_llm(list(state.messages), tool_schemas)

            self.emit(
                state,
                "step_started",
                "LLM completion started",
                tool_count=len(tool_schemas),
                iteration=iteration,
            )
            response = await self._complete_with_retry(
                state=state,
                messages=list(state.messages),
                tools=tool_schemas,
                base_prompt=base_prompt,
            )
            self.track_usage(state, response, iteration)

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
                # Nudge-on-stall: the model narrated an action and called
                # nothing. One tightly-gated re-prompt recovers the turn.
                if self.should_nudge(
                    response,
                    has_tools=bool(tool_schemas),
                    last=iteration >= self.max_iterations,
                ):
                    self.record_nudge(response)
                    state.messages.append(
                        Message(role="assistant", content=response.content)
                    )
                    state.messages.append(Message(role="user", content=self.NUDGE_TEXT))
                    self.emit(
                        state,
                        "tool_call_healed",
                        "Nudged: intent without action",
                        nudge=True,
                        iteration=iteration,
                    )
                    continue
                break

            tool_call_records = [
                {
                    "id": f"call_{iteration}_{index}",
                    "name": tc.name,
                    "arguments": dict(tc.arguments),
                }
                for index, tc in enumerate(response.tool_calls, start=1)
            ]
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
                    metadata={
                        **dict(response.metadata),
                        "tool_calls": tool_call_records,
                    },
                )
            )
            appended_response_id = id(response)

            if self.parallel_tool_execution and len(response.tool_calls) > 1:
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
                    metadata=dict(response.metadata),
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

        self.session_store.save(
            SessionRecord(session_id=self.session_id, messages=list(state.messages))
        )
        self.surface_give_up(state.tool_results)
        response.content = self.sanitize_output(state, response.content)

        self.emit(
            state,
            "run_completed",
            "Agent run completed",
            output=response.content,
            content=response.content,
            format="markdown",
            usage=dict(self._total_usage),
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
