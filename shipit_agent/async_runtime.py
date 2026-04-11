from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Callable
from uuid import uuid4

from shipit_agent.construction import construct_tool_registry
from shipit_agent.integrations import CredentialStore
from shipit_agent.llms.base import LLM, LLMResponse
from shipit_agent.mcp import MCPServer
from shipit_agent.models import AgentEvent, Message, ToolResult
from shipit_agent.policies import RetryPolicy, RouterPolicy
from shipit_agent.registry import ToolRegistry
from shipit_agent.runtime import RuntimeState
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


class AsyncAgentRuntime:
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
        hooks: Any | None = None,
        context_window_tokens: int = 0,
        replan_interval: int = 0,
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
        self._total_usage: dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
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
        self, tool_runner: ToolRunner, tool_call: Any, context: ToolContext
    ) -> ToolResult:
        """Run a tool call in a thread executor."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            tool_runner.run_tool_call,
            tool_call,
            context,
        )

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

        if self.hooks:
            self.hooks.run_before_tool(tool_call.name, tool_call.arguments)

        self.emit(
            state,
            "tool_called",
            f"Tool called: {tool_call.name}",
            arguments=tool_call.arguments,
            iteration=iteration,
        )
        attempt = 0
        while True:
            try:
                tool_result = await self._run_tool_async(
                    tool_runner, tool_call, context
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
            output=tool_result.output,
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

    async def run(self, user_prompt: str) -> tuple[RuntimeState, LLMResponse]:
        state = RuntimeState()
        shared_state: dict[str, Any] = {}
        registry = self.registry()
        tool_prompt = build_tools_prompt(registry.values())
        base_prompt = (
            self.prompt if not tool_prompt else f"{self.prompt}\n\n{tool_prompt}"
        )
        existing_session = self.session_store.load(self.session_id)
        if existing_session:
            state.messages.extend(existing_session.messages)
        elif self.history_messages:
            state.messages.extend(self.history_messages)
        state.messages.append(
            Message(role="system", content=base_prompt, metadata=dict(self.metadata))
        )
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
                "name": t.name,
                "description": t.description,
                "prompt_instructions": getattr(t, "prompt_instructions", ""),
            }
            for t in registry.values()
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

        response = LLMResponse(content="")
        for iteration in range(1, self.max_iterations + 1):
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
                    "name": tc.name,
                    "arguments": dict(tc.arguments),
                }
                for index, tc in enumerate(response.tool_calls, start=1)
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

            if self.parallel_tool_execution and len(response.tool_calls) > 1:
                # Run tools concurrently
                tasks = []
                for idx, tc in enumerate(response.tool_calls):
                    context = ToolContext(
                        prompt=user_prompt,
                        system_prompt=base_prompt,
                        metadata=dict(self.metadata),
                        state=shared_state,
                        session_id=self.session_id,
                    )
                    tasks.append(
                        self._execute_single_tool(
                            state=state,
                            registry=registry,
                            tool_runner=tool_runner,
                            tool_call=tc,
                            tool_call_record=tool_call_records[idx],
                            context=context,
                            iteration=iteration,
                        )
                    )
                results = await asyncio.gather(*tasks)
                for tool_result, msg in results:
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
                if summary.content:
                    response = summary
            except Exception:
                pass

        if response.content:
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
        self.emit(
            state,
            "run_completed",
            "Agent run completed",
            output=response.content,
            content=response.content,
            format="markdown",
            usage=dict(self._total_usage),
        )

        for mcp in self.mcps:
            close = getattr(mcp, "close", None)
            if callable(close):
                close()
        return state, response

    def _track_usage(self, response: LLMResponse) -> None:
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            self._total_usage[key] += response.usage.get(key, 0)

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
