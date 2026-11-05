"""The awaitable agent loop.

:class:`AsyncAgentRuntime` runs the same loop as
:class:`~shipit_agent.core.runtime.AgentRuntime` without blocking an event
loop. Both share their step logic through
:class:`~shipit_agent.core.runtime_core.RuntimeCore`.
"""

from __future__ import annotations

import asyncio
import sys
import threading
from typing import Any, Callable
from uuid import uuid4

from shipit_agent.core.construction import construct_tool_registry
from shipit_agent.core.loop.answer_step import AnswerStepMixin
from shipit_agent.core.loop.code_mode import CodeModeMixin
from shipit_agent.core.loop.event_stream import EventStreamMixin
from shipit_agent.core.loop.model_call import ModelCallMixin
from shipit_agent.core.loop.planning import PlanningMixin
from shipit_agent.core.loop.step_narration import StepNarrationMixin
from shipit_agent.core.loop.tool_attempts import ToolAttemptsMixin
from shipit_agent.core.loop.tool_denial import ToolDenialMixin
from shipit_agent.core.loop.tool_exec import ToolExecutionMixin
from shipit_agent.core.loop.tool_outcome import ToolOutcomeMixin
from shipit_agent.core.loop.tool_step import ToolStepMixin
from shipit_agent.core.loop.turn import Turn
from shipit_agent.core.loop.turn_finish import TurnFinishMixin
from shipit_agent.core.loop.turn_history import TurnHistoryMixin
from shipit_agent.core.loop.turn_setup import TurnSetupMixin
from shipit_agent.core.loop.turn_steps import TurnStepsMixin
from shipit_agent.core.loop.turn_tools import TurnToolsMixin
from shipit_agent.core.models import AgentEvent, Message
from shipit_agent.core.policies import RetryPolicy, RouterPolicy
from shipit_agent.core.registry import ToolRegistry
from shipit_agent.core.runtime_core import (
    RuntimeCore,
)
from shipit_agent.core.state import (
    RuntimeState,
)
from shipit_agent.integrations import CredentialStore
from shipit_agent.llms.base import (
    LLM,
    LLMResponse,
    accepts_text_delta_callback,
    accepts_tool_input_callback,
)
from shipit_agent.mcp import MCPServer
from shipit_agent.observability.tracing import InMemoryTraceStore, TraceStore
from shipit_agent.safety.permissions import PermissionEngine
from shipit_agent.sessions.lock import async_session_run_lock
from shipit_agent.stores import (
    InMemoryMemoryStore,
    InMemorySessionStore,
    MemoryStore,
    SessionStore,
)
from shipit_agent.tools import Tool

#: Stands in for "no step limit" so the loop's step arithmetic stays plain ints.
NO_STEP_LIMIT = sys.maxsize

class AsyncAgentRuntime(
    EventStreamMixin,
    PlanningMixin,
    ModelCallMixin,
    StepNarrationMixin,
    ToolExecutionMixin,
    ToolDenialMixin,
    ToolAttemptsMixin,
    ToolOutcomeMixin,
    TurnSetupMixin,
    TurnHistoryMixin,
    TurnToolsMixin,
    TurnStepsMixin,
    AnswerStepMixin,
    ToolStepMixin,
    TurnFinishMixin,
    CodeModeMixin,
    RuntimeCore,
):
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
        max_iterations: int | None = None,
        retry_policy: RetryPolicy | None = None,
        router_policy: RouterPolicy | None = None,
        credential_store: CredentialStore | None = None,
        trace_store: TraceStore | None = None,
        trace_id: str | None = None,
        parallel_tool_execution: bool = True,
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
        deferred_tools: Any = "auto",
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
        #: The caller's limit, or ``None`` for none. The loop compares against
        #: ``max_iterations``, which is an unreachable count when there is no limit.
        self.step_limit = max_iterations
        self.max_iterations = NO_STEP_LIMIT if max_iterations is None else max_iterations
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
        self._emit_lock = threading.Lock()
        self.run_id = str(uuid4())
        self._event_sequence = 0

    def registry(self) -> ToolRegistry:
        """The run's tools, less any a bare deny rule removes (MCP tools included)."""
        registry = construct_tool_registry(tools=self.tools, mcps=self.mcps)
        if self.permissions is not None:
            for name in [n for n in registry.tools if self.permissions.removes(n)]:
                del registry.tools[name]
        return registry

    def emit(
        self, state: RuntimeState, event_type: str, message: str, **payload: Any
    ) -> None:
        """Record one event and deliver it to the stream subscriber and trace store.

        Every event is stamped with the run and session ids and a sequence
        number, so a client can order and correlate events; tool events also
        carry ``tool_call_id``. The lock keeps parallel tool threads from
        interleaving writes to a trace store that may not be thread-safe.
        """
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

    async def run(
        self,
        user_prompt: str,
        *,
        user_content: list[dict[str, Any]] | None = None,
    ) -> tuple[RuntimeState, LLMResponse]:
        """Run one turn and return its final state and model response."""
        return await self._run_turn(user_prompt, user_content=user_content)

    async def _run_turn(
        self,
        user_prompt: str,
        *,
        user_content: list[dict[str, Any]] | None = None,
    ) -> tuple[RuntimeState, LLMResponse]:
        # The one implementation of a turn. ``run`` and the sync runtime's
        # ``run``/``stream`` all come here, so they cannot drift apart.
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
        turn = await self._begin_turn(user_prompt, user_content=user_content)
        if not isinstance(turn, Turn):
            # A prompt hook or guardrail refused the turn before the model ran.
            return turn
        await self._run_steps(turn)
        return await self._finish_turn(turn)

