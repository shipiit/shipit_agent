import asyncio

import pytest

from shipit_agent import Agent
from shipit_agent.chat_session import AgentChatSession
from shipit_agent.llms.base import LLMResponse
from shipit_agent.models import AgentEvent


class Model:
    def complete(self, **kwargs):
        return LLMResponse(content="answer", usage={"prompt_tokens": 10, "completion_tokens": 2})


def test_async_chat_preserves_history_callbacks_and_budget():
    async def scenario():
        chat = Agent(llm=Model(), max_session_tokens=20, auto_use_skills=False,
                     auto_project_memory=False, auto_project_skills=False).chat_session(session_id="async")
        seen = []
        chat.add_event_callback(seen.append)
        await chat.asend("first")
        events = [event async for event in chat.astream("second")]
        assert events and seen
        assert [m.content for m in chat.history() if m.role == "user"] == ["first", "second"]
        result = await chat.asend("third")
        assert result.metadata["run_summary"]["incomplete_reason"] == "session_token_budget"
    asyncio.run(scenario())


@pytest.mark.parametrize("transport", ["websocket", "sse"])
def test_closing_async_packet_stream_closes_underlying_producer(monkeypatch, transport):
    closed = []
    class Producer:
        async def astream(self, prompt):
            try:
                yield AgentEvent(type="run_started", message="started")
                yield AgentEvent(type="final_answer", message="done")
            finally:
                closed.append(True)
    monkeypatch.setattr(AgentChatSession, "_session_agent", lambda self: Producer())
    async def scenario():
        chat = Agent(llm=Model()).chat_session(session_id="close")
        stream = chat.astream_packets("hi", transport=transport)
        packet = await anext(stream)
        assert isinstance(packet, str if transport == "sse" else dict)
        await stream.aclose()
        assert closed == [True]
    asyncio.run(scenario())


def test_real_agent_wrapper_awaits_runtime_stream_cleanup(monkeypatch):
    from shipit_agent.async_runtime import AsyncAgentRuntime
    closed = []
    async def stream(self, *args, **kwargs):
        try:
            yield AgentEvent(type="run_started", message="started")
            await asyncio.sleep(60)
        finally:
            await asyncio.sleep(0)
            closed.append(True)
    monkeypatch.setattr(AsyncAgentRuntime, "stream", stream)
    async def scenario():
        chat = Agent(llm=Model(), auto_use_skills=False,
                     auto_project_skills=False, auto_project_memory=False).chat_session(session_id="close-runtime")
        events = chat.astream_packets("hi")
        await anext(events)
        await events.aclose()
        assert closed == [True]  # no GC or event-loop shutdown required
    asyncio.run(scenario())


def test_two_concurrent_twenty_turn_chats_keep_tools_and_history_isolated():
    from shipit_agent import FunctionTool
    from shipit_agent.models import ToolCall
    executed = []

    def lookup(query: str) -> str:
        executed.append(query)
        return "evidence:" + query

    class ToolModel:
        def complete(self, *, messages, **kwargs):
            prompts = [line for m in messages if m.role == "user"
                       for line in m.content.splitlines() if line.startswith("tenant-")]
            latest = prompts[-1]
            tenant, turn = latest.split(":")
            assert all(p.startswith(tenant + ":") for p in prompts)
            assert len(prompts) == int(turn) + 1, [m.content for m in messages if m.role == "user"]
            usage = {"prompt_tokens": 20, "completion_tokens": 5}
            if any(m.role == "tool" and "evidence:" + latest in m.content for m in messages):
                return LLMResponse(content="Verified " + latest, usage=usage)
            return LLMResponse(content="", usage=usage, tool_calls=[ToolCall(
                name="lookup", arguments={"query": latest}, id="call-" + latest)])

    async def scenario():
        agent = Agent(llm=ToolModel(), tools=[FunctionTool.from_callable(lookup)],
                      auto_use_skills=False, auto_project_memory=False,
                      auto_project_skills=False, max_session_tokens=2000)
        async def converse(tenant):
            chat = agent.chat_session(session_id=tenant)
            for turn in range(20):
                prompt = f"{tenant}:{turn}"
                if turn % 2:
                    events = [e async for e in chat.astream(prompt)]
                    completed = [e for e in events if e.type == "run_completed"]
                    assert len(completed) == 1
                    assert completed[0].payload["output"] == "Verified " + prompt
                else:
                    result = await chat.asend(prompt)
                    assert result.output == "Verified " + prompt
            assert len([m for m in chat.history() if m.role == "tool"]) == 20
            assert chat._runtime_state["session_tokens"] == 1000
        await asyncio.gather(converse("tenant-a"), converse("tenant-b"))
    asyncio.run(scenario())
    assert len(executed) == len(set(executed)) == 40


def test_async_stream_propagates_worker_error_instead_of_silent_success():
    class BrokenModel:
        def complete(self, **kwargs):
            raise ValueError("fixture provider failure")
    async def scenario():
        chat = Agent(llm=BrokenModel(), auto_use_skills=False,
                     auto_project_memory=False, auto_project_skills=False).chat_session(session_id="broken")
        seen = []
        with pytest.raises(ValueError, match="fixture provider failure"):
            async for event in chat.astream("hi"):
                seen.append(event.type)
        assert "run_started" in seen
        assert "final_answer" not in seen
    asyncio.run(scenario())
