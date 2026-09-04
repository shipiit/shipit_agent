from __future__ import annotations

import asyncio
import inspect
from collections import deque
from typing import Any, AsyncIterator, Callable
from uuid import uuid4

from shipit_agent.construction import construct_tool_registry
from shipit_agent.integrations import CredentialStore
from shipit_agent.llms.base import (
    LLM,
    LLMResponse,
    accepts_kwarg,
    accepts_text_delta_callback,
    accepts_tool_input_callback,
)
from shipit_agent.mcp import MCPServer
from shipit_agent.models import AgentEvent, Message, ToolCall, ToolResult
from shipit_agent.narrate.verbs import summarize
from shipit_agent.permissions import PermissionEngine
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
from shipit_agent.session_lock import async_session_run_lock
from shipit_agent.session_facts import FactLedger
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
        decision_llm: LLM | None = None,
        progress_summaries: bool = True,
        prompt: str,
        tools: list[Tool] | None = None,
        mcps: list[MCPServer] | None = None,
        required_tools: list[str] | None = None,
        require_tool_call: bool = False,
        max_required_tool_text_chars: int = 2_048,
        max_completion_text_chars: int = 0,
        max_tool_argument_chars: int = 65_536,
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
        verify_before_stop: bool = False,
        response_format: dict[str, Any] | None = None,
        session_runtime_state: dict[str, Any] | None = None,
        close_mcps_on_finish: bool = True,
        stream_queue_maxsize: int = 256,
        cancel_on_stream_close: bool = True,
        stream_join_timeout: float = 2.0,
    ) -> None:
        self.llm = llm
        self.decision_llm = decision_llm
        self.progress_summaries = progress_summaries
        self.response_format = response_format
        self.close_mcps_on_finish = bool(close_mcps_on_finish)
        self.stream_queue_maxsize = max(1, int(stream_queue_maxsize))
        self.cancel_on_stream_close = bool(cancel_on_stream_close)
        self.stream_join_timeout = max(0.0, float(stream_join_timeout))
        self.prompt = prompt
        self.tools = list(tools or [])
        self.mcps = list(mcps or [])
        self.required_tools = list(required_tools or [])
        self.require_tool_call = bool(require_tool_call)
        self.max_required_tool_text_chars = max(
            0, int(max_required_tool_text_chars or 0)
        )
        self.max_completion_text_chars = max(0, int(max_completion_text_chars or 0))
        self.max_tool_argument_chars = max(0, int(max_tool_argument_chars or 0))
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
        # Shared controls — guardrails, lockdown, approvals, healing, usage,
        # and compaction — are initialized by the same RuntimeCore contract as
        # the synchronous runtime.
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
            verify_before_stop=verify_before_stop,
            session_runtime_state=session_runtime_state,
        )
        self._llm_streams_text = accepts_text_delta_callback(self.llm.complete)
        self._llm_streams_tool_input = accepts_tool_input_callback(self.llm.complete)
        self._event_subscriber: Callable[[AgentEvent], None] | None = None

    def registry(self) -> ToolRegistry:
        return construct_tool_registry(tools=self.tools, mcps=self.mcps)

    async def _run_planner_if_needed(
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
        result = await tool_runner.run_tool_call_async(
            ToolCall(name=planner.name, arguments={"goal": user_prompt}),
            ToolContext(
                prompt=user_prompt,
                system_prompt=base_prompt,
                metadata=dict(self.metadata),
                state=shared_state,
                session_id=self.session_id,
            ),
        )
        state.tool_results.append(result)
        state.messages.append(
            Message(
                role="user",
                content=f"[Planner output]\n{result.output}",
                metadata={
                    "source": "planner",
                    "planner_tool": planner.name,
                    "internal": True,
                },
            )
        )
        self.emit(
            state, "planning_completed", "Planner completed", output=result.output
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
        loop: asyncio.AbstractEventLoop,
    ) -> str:
        """Install code-mode bindings without bypassing the async tool gates.

        ``execute_code`` itself runs outside the event loop. Calls made through
        its synchronous ``env`` bridge are therefore submitted back to this
        runtime's loop, where they use the same permission, approval, retry,
        guardrail, and transcript path as direct async tool calls.
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
            if method != "call":
                arguments["action"] = method
            counter["n"] += 1
            record = {"id": f"env_{counter['n']}", "name": binding.tool_name}
            call = type(
                "EnvToolCall",
                (),
                {"name": binding.tool_name, "arguments": arguments},
            )()
            future = asyncio.run_coroutine_threadsafe(
                self._execute_single_tool(
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
                ),
                loop,
            )
            result, message = future.result()
            if result is None:
                raise PermissionError(message.content)
            return result.output, dict(result.metadata)

        shared_state[BINDINGS_STATE_KEY] = bindings
        shared_state[INVOKER_STATE_KEY] = _invoke
        return binding_index(bindings)

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
        self,
        *,
        state: RuntimeState,
        messages: list[Message],
        tools: list[dict[str, Any]],
        base_prompt: str,
        require_tool_call: bool = False,
    ) -> LLMResponse:
        """Use a provider's native async API, with a context-preserving fallback."""
        from shipit_agent.action_detection import RepetitionGuard

        loop = asyncio.get_running_loop()
        repetition_guard = RepetitionGuard()
        provisional_chars = 0
        # Keep final answers streaming when tool schemas remain advertised.
        # Native structured tool calling separates calls from answer text;
        # schema availability alone is not evidence that this is a tool step.
        #
        # Stream unless a guardrail could rewrite the answer after the fact:
        # output-modifying rules (secret/PII redaction, output blocklist,
        # custom/judge output check) must buffer the whole answer to redact
        # before display. Input and tool-output rules don't touch the answer
        # stream, so a set with only those streams live.
        expose_text_deltas = (
            self.guardrails is None or not self.guardrails.modifies_output())

        def _schedule_emit(event_type: str, message: str, **payload: Any) -> None:
            loop.call_soon_threadsafe(
                lambda: self.emit(state, event_type, message, **payload)
            )

        def _on_text_delta(chunk: str) -> bool | None:
            nonlocal provisional_chars
            if not chunk:
                return None
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
                _schedule_emit("text_delta", "", chunk=chunk)
            return None

        parsers: dict[str, Any] = {}
        emitted: dict[str, int] = {}
        argument_guards: dict[str, RepetitionGuard] = {}
        argument_chars: dict[str, int] = {}

        def _on_tool_input(
            call_id: str, tool_name: str, fragment: str
        ) -> bool | None:
            from shipit_agent.narrate.json_stream import (
                StreamingToolInputParser,
                streaming_field_for,
            )

            argument_chars[call_id] = argument_chars.get(call_id, 0) + len(fragment)
            guard = argument_guards.setdefault(call_id, RepetitionGuard())
            repeated = guard.add(fragment)
            if (
                repeated and argument_chars[call_id] >= 512
            ) or (
                self.max_tool_argument_chars
                and argument_chars[call_id] >= self.max_tool_argument_chars
            ):
                return False

            parser = parsers.get(call_id)
            if parser is None:
                field = streaming_field_for(tool_name)
                if field is None:
                    parsers[call_id] = False
                    return None
                parser = parsers[call_id] = StreamingToolInputParser(field)
                emitted[call_id] = 0
                _schedule_emit(
                    "tool_input_started",
                    f"Writing {tool_name} input",
                    tool=tool_name,
                    call_id=call_id,
                    field=field,
                )
            if parser is False:
                return None
            parser.append(fragment)
            if parser.has_error:
                parsers[call_id] = False
                return None
            value = parser.streaming_value
            new = value[emitted[call_id] :]
            if new:
                emitted[call_id] = len(value)
                _schedule_emit(
                    "tool_input_delta",
                    "",
                    tool=tool_name,
                    call_id=call_id,
                    delta=new,
                )
            return None

        complete_kwargs: dict[str, Any] = dict(
            messages=messages,
            tools=tools,
            system_prompt=base_prompt,
            metadata=dict(self.metadata),
        )
        async_complete = getattr(self.llm, "acomplete", None)
        complete_fn = async_complete if callable(async_complete) else self.llm.complete
        from shipit_agent.llms.base import accepts_explicit_kwarg

        if require_tool_call and accepts_explicit_kwarg(
            complete_fn, "require_tool_call"
        ):
            complete_kwargs["require_tool_call"] = True
        # Per-request timeout, only for adapters that can honour it — same
        # decision as the sync loop.
        if self.retry_policy.request_timeout is not None and accepts_kwarg(
            complete_fn, "timeout"
        ):
            complete_kwargs["timeout"] = self.retry_policy.request_timeout
        if accepts_text_delta_callback(complete_fn):
            complete_kwargs["text_delta_callback"] = _on_text_delta
        if accepts_tool_input_callback(complete_fn):
            complete_kwargs["tool_input_callback"] = _on_tool_input
        if (
            self.response_format
            and not tools
            and accepts_kwarg(complete_fn, "response_format")
        ):
            complete_kwargs["response_format"] = self.response_format

        if callable(async_complete):
            result = async_complete(**complete_kwargs)
            if inspect.isawaitable(result):
                return await result
            return result
        # asyncio.to_thread propagates contextvars; run_in_executor does not.
        return await asyncio.to_thread(self.llm.complete, **complete_kwargs)

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
                    state=state,
                    messages=messages,
                    tools=tools,
                    base_prompt=base_prompt,
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

    async def _generate_decision_summary(
        self,
        *,
        state: RuntimeState,
        response: LLMResponse,
        user_prompt: str,
        iteration: int,
    ) -> str:
        """Create the same bounded progress line as the synchronous runtime."""
        if not self.progress_summaries:
            return ""
        spoken = _first_sentences(response.content)
        if _looks_like_prose(spoken):
            return spoken
        calls = list(response.tool_calls or [])
        if not calls:
            return ""

        if self.decision_llm is not None:
            actions = "\n".join(
                f"- {call.name}({_bounded(dict(call.arguments or {}), 250)})"
                for call in calls
            )
            prompt = (
                "Write one short first-person progress line for the user.\n"
                f"They asked: {_bounded(user_prompt, 250)}\n"
                f"Last step: {_bounded(state.last_observation, 250) or 'none'}\n"
                f"About to run:\n{actions}\n"
                "Use only these facts; do not claim a result yet."
            )
            try:
                narrator = self.decision_llm
                async_complete = getattr(narrator, "acomplete", None)
                kwargs = {
                    "messages": [Message(role="user", content=prompt)],
                    "tools": [],
                    "system_prompt": (
                        "Narrate agent progress in plain language, without markdown "
                        "or private reasoning. Use two short sentences at most."
                    ),
                    "metadata": {
                        **dict(self.metadata),
                        "purpose": "agent_decision_summary",
                        "iteration": iteration,
                    },
                }
                if callable(async_complete):
                    narrated = async_complete(**kwargs)
                    result = (
                        await narrated if inspect.isawaitable(narrated) else narrated
                    )
                else:
                    result = await asyncio.to_thread(narrator.complete, **kwargs)
                if getattr(result, "usage", None):
                    self.track_usage(state, result, iteration)
                text = _first_sentences(getattr(result, "content", ""))
                if _looks_like_prose(text):
                    return text
            except Exception as exc:  # noqa: BLE001
                self.emit(
                    state,
                    "progress_summary_failed",
                    "Progress summary generation failed",
                    purpose="agent_decision_summary",
                    iteration=iteration,
                    error=str(exc),
                )

        actions = [
            summarize(call.name, dict(call.arguments or {})).present_label()
            for call in calls
        ]
        return _join_clauses(actions) + "."

    def _generate_observation_summary(
        self,
        *,
        tool_results: list[ToolResult],
        tool_calls: list[Any],
    ) -> str:
        """Describe bounded tool outcomes without another model call."""
        if not tool_results or not self.progress_summaries:
            return ""
        arguments = _arguments_by_name(tool_calls)
        clauses: list[str] = []
        for result in tool_results:
            label = summarize(result.name, arguments.get(result.name, {})).past_label()
            if _result_failed(result):
                clauses.append(f"{label} — failed")
            else:
                detail = _describe_result(result)
                clauses.append(f"{label} — {detail}" if detail else label)
        return _join_clauses(clauses) + "."

    async def _run_tool_async(
        self,
        tool_runner: ToolRunner,
        tool_call: Any,
        context: ToolContext,
        output_callback: Callable[[ToolOutputChunk], None] | None = None,
    ) -> ToolResult:
        """Run native async tools directly and sync tools in a context-aware thread."""
        result = await tool_runner.run_tool_call_async(
            tool_call, context, output_callback
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
                    tool_result = ToolResult(
                        name=tool_call.name,
                        output=f"Error running tool '{tool_call.name}': {exc}",
                        is_error=True,
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
            except Exception as exc:  # noqa: BLE001 - tools are a fault boundary
                error_output = f"Error running tool '{tool_call.name}': {exc}"
                tool_result = ToolResult(
                    name=tool_call.name,
                    output=error_output,
                    is_error=True,
                    metadata={
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                    },
                )
                if self.guardrails is None:
                    _publish_output(ToolOutputChunk(
                        error_output,
                        {"error": str(exc), "error_type": type(exc).__name__},
                    ))
                    await asyncio.sleep(0)
                break

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
        if state.verify_gate is not None:
            md = dict(tool_result.metadata or {})
            arguments = getattr(tool_call, "arguments", None) or {}
            state.verify_gate.note_tool(
                read_only=signature is not None,
                paths=[str(path) for path in _declared_paths(md)],
                command=str(md.get("command") or arguments.get("command") or ""),
                exit_code=md.get("exit_code"),
                output=(
                    tool_result.output if isinstance(tool_result.output, str) else ""
                ),
                ok=md.get("ok"),
            )
        terminal_event = "tool_failed" if tool_result.is_error else "tool_completed"
        self.emit(
            state,
            terminal_event,
            f"Tool {'failed' if tool_result.is_error else 'completed'}: {tool_call.name}",
            # Renderers pair an outcome to its call by (tool, call_id); without
            # them this loop's transcript could only guess.
            tool=tool_call.name,
            call_id=tool_call_record["id"],
            output=tool_result.output,
            output_chars=len(tool_result.output),
            model_output_chars=len(model_output),
            model_output_reduced=model_output != tool_result.output,
            metadata=safe_tool_event_metadata(tool_result.metadata),
            error=(str(tool_result.metadata.get("error") or "")
                   if tool_result.is_error else ""),
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
        async with async_session_run_lock(self.session_store, self.session_id):
            try:
                return await self._run_inner(user_prompt, user_content=user_content)
            finally:
                if self.close_mcps_on_finish:
                    await asyncio.to_thread(self.close_mcps)

    async def _run_inner(
        self,
        user_prompt: str,
        *,
        user_content: list[dict[str, Any]] | None = None,
    ) -> tuple[RuntimeState, LLMResponse]:
        state = RuntimeState()

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
            except Exception:
                state.verify_gate = None

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

        # MCP discovery may spawn processes and perform several network
        # handshakes. Keep it off the application event loop.
        registry = await asyncio.to_thread(self.registry)
        # Build the capability control plane before the system prompt so the
        # model sees the same connection/MCP metadata that tools can search.
        shared_state: dict[str, Any] = self.build_shared_state(registry, state)
        initially_required = self.initial_required_tool_names(user_prompt, registry)
        if initially_required:
            shared_state["forced_tool_names"] = initially_required
        elif self.require_tool_call and list(registry.values()):
            shared_state["force_any_tool"] = True
        tool_prompt = build_tools_prompt(
            registry.values(),
            connections=self.connections.all(),
            mcps=self.mcps,
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
            stored_checkpoint = existing_session.metadata.get("compaction_checkpoint")
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
        fact_ledger = FactLedger.from_serialized(
            existing_session.metadata.get("verified_facts")
            if existing_session
            else None
        )
        recall_tool_name = (
            self.install_result_recall(registry, prior_messages)
            if self.evict_prior_tool_outputs
            else ""
        )
        if recall_tool_name:
            shared_state.update(self.build_shared_state(registry, state))
            tool_prompt = build_tools_prompt(
                registry.values(),
                connections=self.connections.all(),
                mcps=self.mcps,
                supports_parallel_tool_calls=(
                    self.model_supports_parallel_tool_calls()
                ),
            )
            base_prompt = (
                self.prompt if not tool_prompt else f"{self.prompt}\n\n{tool_prompt}"
            )
        # Earlier turns' tool payloads have already been read into the
        # answers below them; re-sending them costs their whole length on
        # every step of this turn. The calls and arguments stay.
        #
        # Eviction is a per-REQUEST view only — the originals are kept aside
        # and written back at save time. (See sync AgentRuntime for details.)
        original_prior = [m for m in prior_messages if m.role != "system"]
        if self.evict_prior_tool_outputs:
            prior_messages = evict_prior_tool_outputs(
                list(prior_messages), recall_tool_name=recall_tool_name
            )
        # Exactly one fresh system message at the front; strip any persisted
        # system messages from prior turns so multi-turn sessions don't stack
        # duplicates and grow unbounded. (See sync AgentRuntime for details.)
        state.messages.append(
            Message(role="system", content=base_prompt, metadata=dict(self.metadata))
        )
        state.messages.extend(m for m in prior_messages if m.role != "system")
        rendered_facts = fact_ledger.render()
        if rendered_facts:
            state.messages.append(
                Message(
                    role="assistant",
                    content=rendered_facts,
                    metadata={"internal": True, "kind": "verified_session_facts"},
                )
            )
        state.messages.append(Message(role="user", content=user_content or user_prompt))

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
                skills=[
                    dict(skill) for skill in selected_skills if isinstance(skill, dict)
                ],
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

        if self.code_mode:
            index = self._install_code_mode(
                state=state,
                registry=registry,
                tool_runner=tool_runner,
                shared_state=shared_state,
                user_prompt=user_prompt,
                base_prompt=base_prompt,
                loop=asyncio.get_running_loop(),
            )
            if index:
                from shipit_agent.codemode import CORE_TOOLS

                core_tools = [
                    tool
                    for tool in registry.values()
                    if getattr(tool, "name", "") in CORE_TOOLS
                ]
                core_prompt = build_tools_prompt(
                    core_tools,
                    connections=self.connections.all(),
                    supports_parallel_tool_calls=(
                        self.model_supports_parallel_tool_calls()
                    ),
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
                    if (schema.get("function") or {}).get("name") in CORE_TOOLS
                ]

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
                resident_tools,
                connections=self.connections.all(),
                mcps=self.mcps,
                supports_parallel_tool_calls=self.model_supports_parallel_tool_calls(),
            )
            base_prompt = "\n\n".join(
                part for part in (self.prompt, resident_prompt, deferral_index) if part
            )
            state.messages[0] = Message(
                role="system", content=base_prompt, metadata=dict(self.metadata)
            )

        await self._run_planner_if_needed(
            state=state,
            registry=registry,
            user_prompt=user_prompt,
            base_prompt=base_prompt,
            shared_state=shared_state,
            tool_runner=tool_runner,
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
            force_text = bool(
                shared_state.pop("force_text_after_duplicate", False)
                or shared_state.pop("force_text_after_malformed", False)
            )
            forced_names = set(shared_state.get("forced_tool_names") or ())
            force_any_tool = bool(shared_state.get("force_any_tool"))
            active_schemas = (
                []
                if force_text
                else self.select_step_schemas(tool_schemas, shared_state)
            )
            if forced_names:
                active_schemas = [
                    schema
                    for schema in active_schemas
                    if str((schema.get("function") or {}).get("name", ""))
                    in forced_names
                ]
            schemas_for_budget = (
                []
                if iteration == self.max_iterations and self.max_iterations > 1
                else active_schemas
            )
            self.account_request_overhead(schemas_for_budget)
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
            if forced_names or force_any_tool:
                step_messages.append(
                    Message(
                        role="user",
                        content=(
                            (
                                "Execute the required registered tool now: "
                                + ", ".join(sorted(forced_names))
                                if forced_names
                                else "Execute the most appropriate available tool now"
                            )
                            + ". Emit the structured call, not prose or a simulated result."
                        ),
                        metadata={"internal": True, "kind": "required_tool"},
                    )
                )
            step_messages = self.fit_provider_request(
                state, step_messages, iteration=iteration
            )

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
                require_tool_call=bool(
                    (forced_names or force_any_tool) and step_schemas
                ),
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

            if response.tool_calls:
                decision_summary = await self._generate_decision_summary(
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
                force_any_retries = int(shared_state.get("force_any_retries", 0) or 0)
                if (
                    force_any_tool
                    # Unsatisfiable with no tool advertised this step — see the
                    # sync runtime: retrying just loops the required-tool nudge.
                    and step_schemas
                    and iteration < self.max_iterations
                    and force_any_retries < self.MAX_FORCE_ANY_RETRIES
                ):
                    shared_state["force_any_retries"] = force_any_retries + 1
                    state.messages.append(
                        Message(
                            role="assistant",
                            content="[Unverified response discarded: no required tool executed.]",
                        )
                    )
                    state.messages.append(
                        Message(
                            role="user",
                            content=(
                                "A registered tool must execute before answering. "
                                "Call the best available tool now; do not simulate its result."
                            ),
                            metadata={"internal": True, "kind": "required_tool_retry"},
                        )
                    )
                    self.emit(
                        state,
                        "tool_call_healed",
                        "Retrying required tool use",
                        nudge=True,
                        iteration=iteration,
                    )
                    continue
                # Give up forcing after the cap rather than re-emitting the same
                # retry to max_iterations (the "Retrying required tool use" loop).
                if force_any_tool:
                    shared_state.pop("force_any_tool", None)
                    force_any_tool = False
                    self.emit(
                        state,
                        "step",
                        "Required tool did not execute; answering from available "
                        "context",
                        iteration=iteration,
                    )
                executed = {result.name for result in state.tool_results}
                missing_required = sorted(
                    forced_names - executed - self._requested_tool_nudges
                )
                missing_requested = self.missing_requested_tools(
                    user_prompt, registry, state.tool_results
                )
                missing_requested = sorted(
                    set(missing_requested) | set(missing_required)
                )
                if missing_requested and iteration < self.max_iterations:
                    self.record_requested_tool_nudge(missing_requested)
                    shared_state["forced_tool_names"] = set(missing_requested)
                    state.messages.append(
                        Message(
                            role="assistant",
                            content="[Unverified response discarded: no requested tool executed.]",
                        )
                    )
                    state.messages.append(
                        Message(
                            role="user",
                            content=(
                                "The requested registered tool did not execute. Call "
                                + ", ".join(missing_requested)
                                + " now; do not simulate or invent its result."
                            ),
                            metadata={"internal": True, "kind": "requested_tool_retry"},
                        )
                    )
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
                        Message(
                            role="assistant",
                            content=self.malformed_attempt_context(response),
                        )
                    )
                    state.messages.append(
                        Message(
                            role="user",
                            content=self.NUDGE_TEXT,
                            metadata={"internal": True, "kind": "tool_call_retry"},
                        )
                    )
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
                                    role="user",
                                    content=verify_nudge,
                                    metadata={
                                        "internal": True,
                                        "kind": "verify_retry",
                                    },
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

            group_id = f"tool_group_{iteration}"
            group_result_start = len(state.tool_results)
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

            iteration_results = state.tool_results[group_result_start:]
            observation_summary = self._generate_observation_summary(
                tool_results=iteration_results,
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

            if self.force_text_after_duplicate_batch(state.messages, tool_call_records):
                shared_state["force_text_after_duplicate"] = True
            if state.tool_results:
                shared_state.pop("force_any_tool", None)
            if forced_names:
                remaining_forced = forced_names - {
                    result.name for result in state.tool_results
                }
                if remaining_forced:
                    shared_state["forced_tool_names"] = remaining_forced
                else:
                    shared_state.pop("forced_tool_names", None)
            if (
                self.replan_interval > 0
                and iteration % self.replan_interval == 0
                and iteration < self.max_iterations
            ):
                await self._run_planner_if_needed(
                    state=state,
                    registry=registry,
                    user_prompt=user_prompt,
                    base_prompt=base_prompt,
                    shared_state=shared_state,
                    tool_runner=tool_runner,
                )

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

        response.content = self.stable_final_content(state, response.content)

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
            *(
                message
                for message in state.messages[1 + len(original_prior) :]
                if message.metadata.get("kind") != "verified_session_facts"
            ),
        ]
        session_metadata = dict(existing_session.metadata) if existing_session else {}
        session_metadata["token_calibration"] = self.token_calibrator.to_dict()
        fact_ledger.ingest_tool_results(state.tool_results)
        if len(fact_ledger):
            session_metadata["verified_facts"] = fact_ledger.to_list()
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

    async def stream(
        self,
        user_prompt: str,
        *,
        user_content: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """Run the agent and yield a bounded stream with disconnect cancellation."""
        event_buffer: deque[AgentEvent] = deque()
        wake = asyncio.Event()
        worker_done = False
        provisional_types = {"text_delta", "tool_input_delta", "tool_output_delta"}

        def _subscriber(event: AgentEvent) -> None:
            # Preserve canonical lifecycle events. Under a slow consumer only
            # replace an older delta; run_completed carries the complete text.
            if len(event_buffer) >= self.stream_queue_maxsize:
                drop_index = next(
                    (
                        index
                        for index, queued in enumerate(event_buffer)
                        if queued.type in provisional_types
                    ),
                    None,
                )
                if drop_index is None:
                    self.cancel()
                    return
                del event_buffer[drop_index]
            event_buffer.append(event)
            wake.set()

        self._event_subscriber = _subscriber

        async def _worker() -> None:
            nonlocal worker_done
            try:
                await self.run(user_prompt, user_content=user_content)
            finally:
                worker_done = True
                wake.set()

        task = asyncio.create_task(_worker())
        try:
            while not worker_done or event_buffer:
                if not event_buffer:
                    wake.clear()
                    if worker_done:
                        break
                    await wake.wait()
                    continue
                yield event_buffer.popleft()
        finally:
            self._event_subscriber = None
            if not task.done() and self.cancel_on_stream_close:
                self.cancel()
                task.cancel()
            if task.done() or not self.cancel_on_stream_close:
                await asyncio.gather(task, return_exceptions=True)
            else:
                try:
                    await asyncio.wait_for(
                        asyncio.gather(task, return_exceptions=True),
                        timeout=self.stream_join_timeout,
                    )
                except TimeoutError:
                    task.cancel()
