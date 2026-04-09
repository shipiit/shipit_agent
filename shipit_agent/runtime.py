from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator
from uuid import uuid4

from shipit_agent.construction import build_tool_schemas, construct_tool_registry
from shipit_agent.integrations import CredentialStore
from shipit_agent.llms.base import LLM, LLMResponse
from shipit_agent.mcp import MCPServer
from shipit_agent.models import AgentEvent, Message, ToolResult
from shipit_agent.policies import RetryPolicy, RouterPolicy
from shipit_agent.registry import ToolRegistry
from shipit_agent.stores import InMemoryMemoryStore, InMemorySessionStore, MemoryFact, MemoryStore, SessionRecord, SessionStore
from shipit_agent.tool_runner import ToolRunner
from shipit_agent.tools import Tool, ToolContext
from shipit_agent.tools.helpers import build_tools_prompt
from shipit_agent.tracing import InMemoryTraceStore, TraceStore


@dataclass(slots=True)
class RuntimeState:
    messages: list[Message] = field(default_factory=list)
    events: list[AgentEvent] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)


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
        self._event_subscriber: Callable[[AgentEvent], None] | None = None

    def registry(self) -> ToolRegistry:
        return construct_tool_registry(tools=self.tools, mcps=self.mcps)

    def build_tool_schemas(self) -> list[dict[str, Any]]:
        return build_tool_schemas(self.registry())

    def emit(self, state: RuntimeState, event_type: str, message: str, **payload: Any) -> None:
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
        if planner is None or not self.router_policy.auto_plan or not self.router_policy.should_plan(user_prompt):
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
            tool_call=type("PlannerCall", (), {"name": planner.name, "arguments": {"goal": user_prompt}})(),
            context=context,
        )
        state.tool_results.append(tool_result)
        state.messages.append(Message(role="tool", name=planner.name, content=tool_result.output))
        self.emit(state, "planning_completed", "Planner completed", output=tool_result.output)

    def _complete_with_retry(self, *, state: RuntimeState, messages: list[Message], tools: list[dict[str, Any]], base_prompt: str) -> LLMResponse:
        attempt = 0
        while True:
            try:
                return self.llm.complete(
                    messages=messages,
                    tools=tools,
                    system_prompt=base_prompt,
                    metadata=dict(self.metadata),
                )
            except self.retry_policy.retry_on_exceptions as exc:
                if attempt >= self.retry_policy.max_llm_retries:
                    raise
                attempt += 1
                self.emit(state, "llm_retry", "Retrying LLM completion", attempt=attempt, error=str(exc))

    def run(self, user_prompt: str) -> tuple[RuntimeState, LLMResponse]:
        state = RuntimeState()
        shared_state: dict[str, Any] = {}
        registry = self.registry()
        tool_prompt = build_tools_prompt(registry.values())
        base_prompt = self.prompt if not tool_prompt else f"{self.prompt}\n\n{tool_prompt}"
        existing_session = self.session_store.load(self.session_id)
        if existing_session:
            state.messages.extend(existing_session.messages)
        elif self.history_messages:
            state.messages.extend(self.history_messages)
        state.messages.append(Message(role="system", content=base_prompt, metadata=dict(self.metadata)))
        state.messages.append(Message(role="user", content=user_prompt))

        self.emit(state, "run_started", "Agent run started", prompt=user_prompt)

        for mcp in self.mcps:
            self.emit(state, "mcp_attached", f"MCP server attached: {mcp.name}", server=mcp.name)

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
        shared_state["artifact_workspace_root"] = self.metadata.get("artifact_workspace_root", ".shipit_workspace/artifacts")
        shared_state["workspace_root"] = self.metadata.get("workspace_root", ".shipit_workspace")
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
        for iteration in range(1, self.max_iterations + 1):
            self.emit(state, "step_started", "LLM completion started", tool_count=len(tool_schemas), iteration=iteration)
            response = self._complete_with_retry(
                state=state,
                messages=list(state.messages),
                tools=tool_schemas,
                base_prompt=base_prompt,
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

            for tool_call_index, tool_call in enumerate(response.tool_calls):
                context = ToolContext(
                    prompt=user_prompt,
                    system_prompt=base_prompt,
                    metadata=dict(self.metadata),
                    state=shared_state,
                    session_id=self.session_id,
                )
                tool = registry.get(tool_call.name)
                if tool is None:
                    continue
                self.emit(state, "tool_called", f"Tool called: {tool_call.name}", arguments=tool_call.arguments, iteration=iteration)
                attempt = 0
                while True:
                    try:
                        tool_result = tool_runner.run_tool_call(tool_call, context)
                        break
                    except self.retry_policy.retry_on_exceptions as exc:
                        if attempt >= self.retry_policy.max_tool_retries:
                            self.emit(state, "tool_failed", f"Tool failed: {tool_call.name}", error=str(exc), iteration=iteration)
                            raise
                        attempt += 1
                        self.emit(state, "tool_retry", f"Retrying tool: {tool_call.name}", attempt=attempt, error=str(exc), iteration=iteration)
                state.tool_results.append(tool_result)
                state.messages.append(
                    Message(
                        role="tool",
                        name=tool_call.name,
                        content=tool_result.output,
                        metadata={
                            **dict(tool_result.metadata),
                            "tool_call_id": tool_call_records[tool_call_index]["id"],
                        },
                    )
                )
                self.emit(state, "tool_completed", f"Tool completed: {tool_call.name}", output=tool_result.output, iteration=iteration)
                if tool_result.metadata.get("interactive"):
                    self.emit(
                        state,
                        "interactive_request",
                        f"Interactive request from {tool_call.name}",
                        kind=tool_result.metadata.get("kind"),
                        payload=dict(tool_result.metadata),
                    )

        if response.content:
            state.messages.append(Message(role="assistant", content=response.content, metadata=dict(response.metadata)))

        for tool_result in state.tool_results:
            self.memory_store.add(
                MemoryFact(
                    content=f"{tool_result.name}: {tool_result.output}",
                    category="tool_result",
                    metadata=dict(tool_result.metadata),
                )
            )
        self.session_store.save(SessionRecord(session_id=self.session_id, messages=list(state.messages)))
        self.emit(state, "run_completed", "Agent run completed", output=response.content)
        for mcp in self.mcps:
            close = getattr(mcp, "close", None)
            if callable(close):
                close()
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
        worker = threading.Thread(target=_worker, name="shipit-agent-stream", daemon=True)
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
