"""``AgentClient``: a multi-turn session like the Claude Agent SDK's client."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import pytest

from shipit_agent import FunctionTool
from shipit_agent.core.models import ToolCall
from shipit_agent.llms.base import LLMResponse
from shipit_agent.sdk import AgentClient, AgentOptions, ResultMessage, UserMessage, create_sdk_mcp_server, tool


class _Model:
    """Answers each prompt; records the conversation and model it was given."""

    def __init__(self, model: str = "claude-sonnet-5-5", script: list[LLMResponse] | None = None) -> None:
        self.model = model
        self.script = list(script or [])
        self.seen: list[tuple[str, list[str]]] = []

    def complete(self, *, messages: Any, **_: Any) -> LLMResponse:
        self.seen.append((self.model, [str(m.content) for m in messages if m.role == "user"]))
        if self.script:
            return self.script.pop(0)
        return LLMResponse(content=f"reply {len(self.seen)}")


def _call(name: str, **arguments: Any) -> LLMResponse:
    return LLMResponse(content="", tool_calls=[ToolCall(name=name, arguments=arguments)])


async def _turn(client: AgentClient, prompt: str) -> list[Any]:
    await client.query(prompt)
    return [message async for message in client.receive_response()]


def test_turns_share_one_conversation() -> None:
    llm = _Model()

    async def run() -> None:
        async with AgentClient(AgentOptions(llm=llm, tools=[])) as client:
            await _turn(client, "My name is Ada.")
            await _turn(client, "What is my name?")

    asyncio.run(run())
    second_turn_users = llm.seen[1][1]
    assert any("My name is Ada." in text for text in second_turn_users)
    assert "What is my name?" in second_turn_users[-1]


def test_a_response_starts_with_the_prompt_and_ends_with_the_result() -> None:
    async def run() -> list[Any]:
        async with AgentClient(AgentOptions(llm=_Model(), tools=[])) as client:
            return await _turn(client, "hi")

    messages = asyncio.run(run())
    assert isinstance(messages[0], UserMessage) and messages[0].content == "hi" and messages[0].uuid
    assert isinstance(messages[-1], ResultMessage) and messages[-1].result == "reply 1"


def test_disconnect_ends_receive_messages() -> None:
    async def run() -> list[Any]:
        client = AgentClient(AgentOptions(llm=_Model(), tools=[]))
        await client.connect("hi")
        await client.disconnect()
        return [message async for message in client.receive_messages()]

    messages = asyncio.run(run())
    assert isinstance(messages[-1], ResultMessage)


def test_interrupt_stops_the_turn_between_steps() -> None:
    def slow(text: str = "") -> str:
        """Takes a while."""
        time.sleep(0.3)
        return "slow done"

    llm = _Model(script=[_call("slow"), _call("slow")])

    async def run() -> list[Any]:
        options = AgentOptions(llm=llm, tools=[FunctionTool.from_callable(slow, name="slow")])
        async with AgentClient(options) as client:
            await client.query("go")
            await asyncio.sleep(0.1)
            await client.interrupt()
            return [message async for message in client.receive_response()]

    messages = asyncio.run(run())
    assert isinstance(messages[-1], ResultMessage)
    assert len(llm.seen) == 1


def _note(text: str = "") -> str:
    """Write a note."""
    return f"noted:{text}"


def test_set_permission_mode_applies_to_later_calls() -> None:
    llm = _Model(script=[_call("note_create", text="a"), LLMResponse(content="ok"),
                         _call("note_create", text="b"), LLMResponse(content="ok")])

    async def run() -> tuple[list[Any], list[Any]]:
        # Plan mode refuses mutating tools; default mode lets this one run.
        options = AgentOptions(llm=llm, tools=[FunctionTool.from_callable(_note, name="note_create")],
                               permission_mode="plan")
        async with AgentClient(options) as client:
            first = await _turn(client, "one")
            await client.set_permission_mode("default")
            return first, await _turn(client, "two")

    first, second = asyncio.run(run())
    assert first[-1].permission_denials and not second[-1].permission_denials


def test_set_model_switches_and_none_switches_back() -> None:
    llm = _Model(model="primary")

    async def run() -> None:
        async with AgentClient(AgentOptions(llm=llm, tools=[])) as client:
            await _turn(client, "one")
            await client.set_model("other")
            await _turn(client, "two")
            await client.set_model(None)
            await _turn(client, "three")

    asyncio.run(run())
    assert [model for model, _ in llm.seen] == ["primary", "other", "primary"]


def test_rewind_files_restores_what_each_turn_changed(tmp_path: Path) -> None:
    llm = _Model(script=[
        _call("write_file", path="a.txt", content="first"), LLMResponse(content="wrote a"),
        _call("write_file", path="a.txt", content="second"), _call("write_file", path="b.txt", content="new"),
        LLMResponse(content="changed both"),
    ])

    async def run() -> None:
        options = AgentOptions(llm=llm, cwd=tmp_path, tools=["Write"], enable_file_checkpointing=True,
                               permission_mode="bypassPermissions")
        async with AgentClient(options) as client:
            turn_one = (await _turn(client, "one"))[0].uuid
            turn_two = (await _turn(client, "two"))[0].uuid
            assert (tmp_path / "a.txt").read_text() == "second" and (tmp_path / "b.txt").exists()
            await client.rewind_files(turn_two)
            assert (tmp_path / "a.txt").read_text() == "first" and not (tmp_path / "b.txt").exists()
            await client.rewind_files(turn_one)
            assert not (tmp_path / "a.txt").exists()
            with pytest.raises(KeyError):
                await client.rewind_files(turn_two)

    asyncio.run(run())


def test_rewind_files_needs_checkpointing() -> None:
    async def run() -> None:
        async with AgentClient(AgentOptions(llm=_Model(), tools=[])) as client:
            with pytest.raises(RuntimeError, match="enable_file_checkpointing"):
                await client.rewind_files("x")

    asyncio.run(run())


def test_context_usage_grows_with_the_conversation() -> None:
    async def run() -> tuple[dict[str, Any], dict[str, Any]]:
        async with AgentClient(AgentOptions(llm=_Model(), tools=[])) as client:
            before = await client.get_context_usage()
            await _turn(client, "a fairly long message " * 50)
            return before, await client.get_context_usage()

    before, after = asyncio.run(run())
    assert set(before) >= {"model", "categories", "totalTokens", "maxTokens", "percentage"}
    assert after["categories"]["messages"] > before["categories"]["messages"] == 0
    assert after["maxTokens"] == 1_000_000


@tool("ping", "Ping", {})
def _ping(args: dict[str, Any]) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": "pong"}]}


class _Broken:
    name = "broken"

    def discover_tools(self) -> list[Any]:
        raise ConnectionError("would not start")


def test_mcp_status_reports_each_server() -> None:
    async def run() -> dict[str, Any]:
        options = AgentOptions(llm=_Model(), tools=[],
                               mcp_servers=[create_sdk_mcp_server("util", tools=[_ping])["instance"], _Broken()])
        async with AgentClient(options) as client:
            return await client.get_mcp_status()

    servers = {s["name"]: s for s in asyncio.run(run())["mcpServers"]}
    assert servers["util"]["status"] == "connected" and servers["util"]["tools"] == [{"name": "util__ping"}]
    assert servers["broken"]["status"] == "failed" and "would not start" in servers["broken"]["error"]
