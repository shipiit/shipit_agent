"""Managing MCP servers on a live session: reconnect, switch off and on, and strict config."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from shipit_agent.core.models import ToolCall
from shipit_agent.llms.base import LLMResponse
from shipit_agent.sdk import AgentClient, AgentOptions, UserMessage, build_agent, create_sdk_mcp_server, tool


@tool("ping", "Ping", {})
def _ping(args: dict[str, Any]) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": "pong"}]}


class _Model:
    model = "claude-sonnet-5-5"

    def __init__(self) -> None:
        self.offered: list[list[str]] = []

    def complete(self, *, tools: Any = None, **_: Any) -> LLMResponse:
        names = [(t.get("function") or t).get("name", "") for t in tools or []]
        self.offered.append(names)
        if "util__ping" in names and len(self.offered) % 2 == 1:
            return LLMResponse(content="", tool_calls=[ToolCall(name="util__ping", arguments={}, id=f"c{len(self.offered)}")])
        return LLMResponse(content="done")


class _Flaky:
    """A server that fails until it is reconnected."""

    name = "flaky"

    def __init__(self) -> None:
        self.closed = 0
        self.invalidated = 0
        self.up = False

    def discover_tools(self) -> list[Any]:
        if not self.up:
            raise ConnectionError("not started")
        return []

    def close(self) -> None:
        self.closed += 1
        self.up = True

    def invalidate_tools_cache(self) -> None:
        self.invalidated += 1


def _util() -> Any:
    return create_sdk_mcp_server("util", tools=[_ping])["instance"]


def _statuses(status: dict[str, Any]) -> dict[str, str]:
    return {server["name"]: server["status"] for server in status["mcpServers"]}


async def _turn(client: AgentClient, prompt: str) -> list[Any]:
    await client.query(prompt)
    return [message async for message in client.receive_response()]


def test_a_server_switched_off_is_not_offered_until_it_is_switched_back_on() -> None:
    llm = _Model()

    async def run() -> list[dict[str, str]]:
        options = AgentOptions(llm=llm, tools=[], mcp_servers=[_util()], allowed_tools=["mcp__util__ping"])
        async with AgentClient(options) as client:
            first = await _turn(client, "one")
            assert any(isinstance(m, UserMessage) for m in first)
            await client.toggle_mcp_server("util", False)
            off = _statuses(await client.get_mcp_status())
            await _turn(client, "two")
            offered_while_off = list(llm.offered[-1])
            await client.toggle_mcp_server("util", False)  # twice is the same as once
            await client.toggle_mcp_server("util", True)
            on = _statuses(await client.get_mcp_status())
            await _turn(client, "three")
            assert "util__ping" not in offered_while_off and "util__ping" in llm.offered[-1]
            return [off, on]

    off, on = asyncio.run(run())
    assert off == {"util": "disabled"} and on == {"util": "connected"}


def test_reconnecting_restarts_a_failed_server() -> None:
    server = _Flaky()

    async def run() -> tuple[str, str]:
        async with AgentClient(AgentOptions(llm=_Model(), tools=[], mcp_servers=[server])) as client:
            before = _statuses(await client.get_mcp_status())["flaky"]
            await client.reconnect_mcp_server("flaky")
            return before, _statuses(await client.get_mcp_status())["flaky"]

    assert asyncio.run(run()) == ("failed", "connected")
    assert (server.closed, server.invalidated) == (1, 1)


def test_reconnecting_a_server_that_still_fails_raises_its_error() -> None:
    class _Dead(_Flaky):
        def close(self) -> None:
            self.closed += 1

    async def run() -> None:
        async with AgentClient(AgentOptions(llm=_Model(), tools=[], mcp_servers=[_Dead()])) as client:
            await client.reconnect_mcp_server("flaky")

    with pytest.raises(ConnectionError, match="not started"):
        asyncio.run(run())


@pytest.mark.parametrize("call", ["reconnect", "toggle"])
def test_an_unknown_server_name_is_an_error(call: str) -> None:
    async def run() -> None:
        async with AgentClient(AgentOptions(llm=_Model(), tools=[], mcp_servers=[_util()])) as client:
            if call == "reconnect":
                await client.reconnect_mcp_server("nope")
            else:
                await client.toggle_mcp_server("nope", False)

    with pytest.raises(KeyError, match="nope"):
        asyncio.run(run())


def test_a_switched_off_server_can_be_reconnected_and_stays_off() -> None:
    server = _Flaky()

    async def run() -> str:
        async with AgentClient(AgentOptions(llm=_Model(), tools=[], mcp_servers=[server])) as client:
            await client.toggle_mcp_server("flaky", False)
            await client.reconnect_mcp_server("flaky")
            return _statuses(await client.get_mcp_status())["flaky"]

    assert asyncio.run(run()) == "disabled" and server.closed == 1


def test_server_info_describes_the_session() -> None:
    async def run() -> dict[str, Any] | None:
        async with AgentClient(AgentOptions(llm=_Model(), tools=[], mcp_servers=[_util()], permission_mode="plan")) as client:
            return await client.get_server_info()

    info = asyncio.run(run())
    assert info is not None
    assert (info["model"], info["mcp_servers"], info["permission_mode"]) == ("claude-sonnet-5-5", ["util"], "plan")


def _plugin(root: Path) -> Path:
    plugin = root / "plug"
    (plugin / ".claude-plugin").mkdir(parents=True)
    (plugin / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "plug", "version": "1.0.0"}))
    (plugin / ".mcp.json").write_text(json.dumps({"mcpServers": {"fromplugin": {"command": "true"}}}))
    return plugin


def test_strict_mcp_config_uses_only_the_servers_passed_in(tmp_path: Path) -> None:
    plugins = [{"type": "local", "path": str(_plugin(tmp_path))}]
    base = dict(llm=_Model(), tools=[], cwd=tmp_path, plugins=plugins, mcp_servers=[_util()])
    loose = build_agent(AgentOptions(**base))
    strict = build_agent(AgentOptions(**base, strict_mcp_config=True))
    assert [server.name for server in strict.mcps] == ["util"]
    assert len(loose.mcps) == 2
