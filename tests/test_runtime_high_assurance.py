from __future__ import annotations

import asyncio
import inspect
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from shipit_agent import Agent
from shipit_agent.async_runtime import AsyncAgentRuntime
from shipit_agent.llms.base import LLMResponse
from shipit_agent.mcp import MCPError, RemoteMCPServer
from shipit_agent.models import ToolCall
from shipit_agent.runtime import AgentRuntime
from shipit_agent.runtime_state import RuntimeState
from shipit_agent.stores import InMemorySessionStore, SessionRecord
from shipit_agent.tools import ToolOutput


class _EchoLLM:
    model = "test"

    def complete(self, *, messages, **kwargs):
        user = next(str(m.content) for m in reversed(messages) if m.role == "user")
        time.sleep(0.03)
        return LLMResponse(content=f"answer:{user}")


def test_same_session_concurrent_turns_are_not_lost() -> None:
    store = InMemorySessionStore()
    agent = Agent(llm=_EchoLLM(), prompt="p", session_store=store, session_id="same")
    session = agent.chat_session(session_id="same")

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(session.send, ["first", "second"]))

    record = store.load("same")
    assert record is not None
    contents = [str(message.content) for message in record.messages]
    assert "first" in contents
    assert "second" in contents
    assert "answer:first" in contents
    assert "answer:second" in contents


def test_same_session_concurrent_async_turns_are_not_lost() -> None:
    async def scenario() -> list[str]:
        store = InMemorySessionStore()
        first = AsyncAgentRuntime(
            llm=_EchoLLM(), prompt="p", session_store=store, session_id="shared"
        )
        second = AsyncAgentRuntime(
            llm=_EchoLLM(), prompt="p", session_store=store, session_id="shared"
        )
        await asyncio.gather(first.run("first"), second.run("second"))
        record = store.load("shared")
        assert record is not None
        return [str(message.content) for message in record.messages]

    contents = asyncio.run(scenario())
    assert "first" in contents
    assert "second" in contents
    assert "answer:first" in contents
    assert "answer:second" in contents


def test_runtime_constructor_contracts_have_exact_parity() -> None:
    sync = set(inspect.signature(AgentRuntime.__init__).parameters) - {"self"}
    asynchronous = set(inspect.signature(AsyncAgentRuntime.__init__).parameters) - {
        "self"
    }
    assert asynchronous == sync


def test_async_session_preserves_metadata_and_calibration() -> None:
    store = InMemorySessionStore()
    store.save(SessionRecord(session_id="s", metadata={"owner": "keep"}))
    runtime = AsyncAgentRuntime(
        llm=_EchoLLM(),
        prompt="p",
        session_store=store,
        session_id="s",
        context_window_tokens=100,
    )
    asyncio.run(runtime.run("hello"))
    metadata = store.load("s").metadata  # type: ignore[union-attr]
    assert metadata["owner"] == "keep"
    assert "token_calibration" in metadata


def test_async_runtime_prefers_native_async_llm() -> None:
    class Native:
        model = "test"

        def complete(self, **kwargs):
            raise AssertionError("sync fallback should not run")

        async def acomplete(self, **kwargs):
            return LLMResponse(content="native")

    state, response = asyncio.run(AsyncAgentRuntime(llm=Native(), prompt="p").run("go"))
    assert response.content == "native"
    assert state.messages[-1].content == "native"


def test_async_required_tool_completion_receives_abort_callback() -> None:
    class CallbackProbe:
        model = "test"

        def __init__(self) -> None:
            self.stopped = False

        def complete(
            self,
            *,
            messages,
            tools,
            system_prompt,
            metadata,
            text_delta_callback=None,
            require_tool_call=False,
        ):
            assert require_tool_call is True
            assert text_delta_callback is not None
            self.stopped = text_delta_callback("x" * 32) is False
            return LLMResponse(tool_calls=[ToolCall(name="probe", arguments={})])

    probe = CallbackProbe()
    runtime = AsyncAgentRuntime(llm=probe, prompt="p", max_required_tool_text_chars=16)
    response = asyncio.run(
        runtime._complete_async(
            state=RuntimeState(),
            messages=[],
            tools=[{"function": {"name": "probe"}}],
            base_prompt="p",
            require_tool_call=True,
        )
    )
    assert response.tool_calls[0].name == "probe"
    assert probe.stopped is True


def test_async_text_streaming_stays_enabled_with_tool_schemas() -> None:
    class StreamingFinal:
        model = "test"

        async def acomplete(self, *, text_delta_callback=None, **kwargs):
            assert text_delta_callback is not None
            text_delta_callback("final text")
            return LLMResponse(content="final text")

        def complete(self, **kwargs):
            raise AssertionError("sync fallback should not run")

    async def scenario() -> RuntimeState:
        state = RuntimeState()
        runtime = AsyncAgentRuntime(llm=StreamingFinal(), prompt="p")
        await runtime._complete_async(
            state=state,
            messages=[],
            tools=[{"function": {"name": "available_tool"}}],
            base_prompt="p",
        )
        await asyncio.sleep(0)
        return state

    state = asyncio.run(scenario())
    assert [
        event.payload["chunk"] for event in state.events if event.type == "text_delta"
    ] == ["final text"]


def test_async_tool_prefers_native_arun() -> None:
    class AsyncTool:
        name = "native_tool"
        description = "native"
        prompt_instructions = ""

        def schema(self):
            return {
                "type": "function",
                "function": {
                    "name": self.name,
                    "description": self.description,
                    "parameters": {"type": "object", "properties": {}},
                },
            }

        def run(self, context, **kwargs):
            raise AssertionError("sync tool should not run")

        async def arun(self, context, **kwargs):
            return ToolOutput("native tool result")

    class CallsOnce:
        model = "test"

        def __init__(self):
            self.calls = 0

        async def acomplete(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return LLMResponse(
                    tool_calls=[ToolCall(name="native_tool", arguments={})]
                )
            return LLMResponse(content="done")

        def complete(self, **kwargs):
            raise AssertionError("sync LLM should not run")

    state, response = asyncio.run(
        AsyncAgentRuntime(llm=CallsOnce(), prompt="p", tools=[AsyncTool()]).run("go")
    )
    assert response.content == "done"
    assert state.tool_results[0].output == "native tool result"
    event_types = [event.type for event in state.events]
    assert "agent_decision" in event_types
    assert "agent_observation" in event_types
    assert "tool_group_started" in event_types
    assert "tool_group_completed" in event_types


def test_public_async_agent_code_mode_uses_real_tool_gate() -> None:
    calls: list[dict] = []

    class Resource:
        name = "warehouse"
        description = "Query the warehouse"
        prompt_instructions = ""

        def schema(self):
            return {
                "type": "function",
                "function": {
                    "name": self.name,
                    "description": self.description,
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "action": {"type": "string", "enum": ["query"]},
                            "sql": {"type": "string"},
                        },
                        "required": ["action"],
                    },
                },
            }

        def run(self, context, **kwargs):
            calls.append(kwargs)
            return ToolOutput("northwind,820")

    class Script:
        model = "test"

        def __init__(self):
            self.step = 0

        def complete(self, **kwargs):
            self.step += 1
            if self.step == 1:
                return LLMResponse(
                    tool_calls=[
                        ToolCall(
                            name="execute_code",
                            arguments={
                                "code": ("print(env.WAREHOUSE.query(sql='SELECT 1'))")
                            },
                        )
                    ]
                )
            return LLMResponse(content="done")

    result = asyncio.run(
        Agent(
            llm=Script(),
            tools=[Resource()],
            code_mode=True,
            auto_use_skills=False,
        ).run_async("query it")
    )
    assert result.output == "done"
    assert calls == [{"action": "query", "sql": "SELECT 1"}]


def test_async_stream_close_cancels_without_waiting_for_sync_provider() -> None:
    class Slow:
        model = "test"

        def complete(self, **kwargs):
            time.sleep(0.8)
            return LLMResponse(content="late")

    async def scenario() -> tuple[float, bool]:
        runtime = AsyncAgentRuntime(llm=Slow(), prompt="p")
        stream = runtime.stream("go")
        await anext(stream)
        started = time.monotonic()
        await stream.aclose()
        return time.monotonic() - started, runtime.cancelled

    elapsed, cancelled = asyncio.run(scenario())
    assert elapsed < 0.25
    assert cancelled is True


class _PagedTransport:
    generation = 1

    def __init__(self, *, repeated: bool = False) -> None:
        self.repeated = repeated
        self.calls: list[tuple[str, dict]] = []

    def request(self, method, params=None):
        params = dict(params or {})
        self.calls.append((method, params))
        if method == "initialize":
            return {"protocolVersion": "2025-11-25"}
        if method == "tools/list":
            cursor = params.get("cursor")
            if cursor is None:
                return {
                    "tools": [{"name": "one", "inputSchema": {"type": "object"}}],
                    "nextCursor": "page-2",
                }
            return {
                "tools": [{"name": "two", "inputSchema": {"type": "object"}}],
                "nextCursor": "page-2" if self.repeated else None,
            }
        if method in {"resources/list", "prompts/list"}:
            key = method.split("/", 1)[0]
            cursor = params.get("cursor")
            suffix = "one" if cursor is None else "two"
            item = (
                {"uri": f"memory://{suffix}", "name": suffix}
                if key == "resources"
                else {"name": suffix}
            )
            return {
                key: [item],
                "nextCursor": "page-2" if cursor is None else None,
            }
        return {}

    def notify(self, *args):
        return None

    def close(self):
        return None


def test_mcp_tool_discovery_collects_all_pages() -> None:
    transport = _PagedTransport()
    server = RemoteMCPServer(name="paged", transport=transport)
    assert [tool.name for tool in server.discover_tools()] == ["one", "two"]
    assert ("tools/list", {"cursor": "page-2"}) in transport.calls


def test_mcp_resources_and_prompts_collect_all_pages() -> None:
    server = RemoteMCPServer(name="paged", transport=_PagedTransport())
    assert [item.name for item in server.list_resources()] == ["one", "two"]
    assert [item.name for item in server.list_prompts()] == ["one", "two"]


def test_mcp_repeated_cursor_fails_instead_of_looping() -> None:
    server = RemoteMCPServer(name="paged", transport=_PagedTransport(repeated=True))
    with pytest.raises(MCPError, match="repeated cursor"):
        server.discover_tools()


def test_public_agent_async_apis_keep_one_session() -> None:
    async def scenario() -> tuple[str, list[str]]:
        agent = Agent(llm=_EchoLLM(), prompt="p", session_id="async-agent")
        first = await agent.run_async("one")
        events = [event.type async for event in agent.astream("two")]
        return first.output, events

    output, event_types = asyncio.run(scenario())
    assert output == "answer:one"
    assert "run_completed" in event_types
