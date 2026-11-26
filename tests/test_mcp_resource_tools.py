"""``list_mcp_resources`` and ``read_mcp_resource``: the SDK's ListMcpResources and ReadMcpResource."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from shipit_agent.core.models import ToolCall
from shipit_agent.llms.base import LLMResponse
from shipit_agent.mcp.server_resources import MCPResource
from shipit_agent.safety.permission_rules import sdk_tool_name
from shipit_agent.sdk import AgentClient, AgentOptions, ToolResultBlock, UserMessage
from shipit_agent.tools import ListMcpResourcesTool, ReadMcpResourceTool
from shipit_agent.tools.base import ToolContext


class _Transport:
    def __init__(self, contents: dict[str, Any]) -> None:
        self.contents = contents

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        assert method == "resources/read"
        if params["uri"] not in self.contents:
            raise RuntimeError(f"no resource {params['uri']}")
        return {"contents": [self.contents[params["uri"]]]}


class _Server:
    def __init__(self, name: str, resources: list[MCPResource], contents: dict[str, Any]) -> None:
        self.name, self.resources = name, resources
        self.transport = _Transport(contents)

    def initialize(self) -> None:
        return None

    def list_resources(self) -> list[MCPResource]:
        return list(self.resources)

    def discover_tools(self) -> list[Any]:
        return []


class _NoResources:
    name = "plain"

    def discover_tools(self) -> list[Any]:
        return []


DOCS = _Server(
    "docs",
    [MCPResource("file:///readme.md", "README", "The readme", "text/markdown"), MCPResource("file:///logo.png", "logo")],
    {"file:///readme.md": {"uri": "file:///readme.md", "mimeType": "text/markdown", "text": "# Hello"},
     "file:///logo.png": {"uri": "file:///logo.png", "mimeType": "image/png", "blob": "AAAA"}},
)
DB = _Server("db", [MCPResource("db://users", "users")], {"db://users": {"uri": "db://users", "text": "3 rows"}})


def _context(*servers: Any) -> ToolContext:
    return ToolContext(prompt="", state={"mcp_servers": list(servers)})


def _json(output: Any) -> Any:
    return json.loads(output.text)


def test_list_returns_every_servers_resources_in_the_sdk_shape() -> None:
    out = ListMcpResourcesTool().run(_context(DOCS, DB, _NoResources()))
    assert _json(out) == [
        {"uri": "file:///readme.md", "name": "README", "mimeType": "text/markdown", "description": "The readme", "server": "docs"},
        {"uri": "file:///logo.png", "name": "logo", "mimeType": None, "description": None, "server": "docs"},
        {"uri": "db://users", "name": "users", "mimeType": None, "description": None, "server": "db"},
    ]


def test_list_filters_by_server_and_names_an_unknown_one() -> None:
    assert [r["uri"] for r in _json(ListMcpResourcesTool().run(_context(DOCS, DB), server="db"))] == ["db://users"]
    missing = ListMcpResourcesTool().run(_context(DOCS), server="nope")
    assert missing.metadata["is_error"] is True and "docs" in missing.text
    assert _json(ListMcpResourcesTool().run(_context())) == []


def test_read_returns_text_and_notes_binary_content() -> None:
    text = _json(ReadMcpResourceTool().run(_context(DOCS), server="docs", uri="file:///readme.md"))
    assert text == {"contents": [{"uri": "file:///readme.md", "mimeType": "text/markdown", "text": "# Hello", "blobSavedTo": None}], "error": None}
    blob = _json(ReadMcpResourceTool().run(_context(DOCS), server="docs", uri="file:///logo.png"))["contents"][0]
    assert blob["text"] == "[binary image/png content not shown]" and blob["blobSavedTo"] is None


@pytest.mark.parametrize(
    ("server", "uri", "words"),
    [("nope", "x", "no MCP server"), ("docs", "file:///missing", "no resource"), ("plain", "x", "does not offer resources"), ("", "x", "server")],
)
def test_read_failures_are_errors_the_model_can_act_on(server: str, uri: str, words: str) -> None:
    out = ReadMcpResourceTool().run(_context(DOCS, _NoResources()), server=server, uri=uri)
    assert out.metadata["is_error"] is True and words in out.text


def test_both_are_read_only_and_answer_to_the_sdk_names() -> None:
    assert ListMcpResourcesTool().read_only and ReadMcpResourceTool().read_only
    for name in ("ListMcpResources", "ListMcpResourcesTool"):
        assert sdk_tool_name(name) == "list_mcp_resources"
    for name in ("ReadMcpResource", "ReadMcpResourceTool"):
        assert sdk_tool_name(name) == "read_mcp_resource"


class _Lists:
    model = "claude-sonnet-5-5"

    def __init__(self) -> None:
        self.turn = 0

    def complete(self, **_: Any) -> LLMResponse:
        self.turn += 1
        if self.turn % 2 == 1:
            return LLMResponse(content="", tool_calls=[ToolCall(name="list_mcp_resources", arguments={}, id=f"c{self.turn}")])
        return LLMResponse(content="done")


def test_in_a_session_a_switched_off_server_is_not_listed() -> None:
    async def run() -> list[list[str]]:
        options = AgentOptions(llm=_Lists(), tools=["ListMcpResourcesTool"], mcp_servers=[DOCS, DB],
                               allowed_tools=["ListMcpResourcesTool"])
        seen: list[list[str]] = []
        async with AgentClient(options) as client:
            for _ in range(2):
                await client.query("list")
                for message in [m async for m in client.receive_response()]:
                    if isinstance(message, UserMessage) and isinstance(message.content, list):
                        block = message.content[0]
                        if isinstance(block, ToolResultBlock):
                            seen.append(sorted({r["server"] for r in json.loads(str(block.content))}))
                await client.toggle_mcp_server("db", False)
        return seen

    assert asyncio.run(run()) == [["db", "docs"], ["docs"]]


SECRETS = _Server("secrets", [MCPResource("vault://prod", "prod")], {"vault://prod": {"uri": "vault://prod", "text": "TOP-SECRET"}})


class _UsesResources:
    model = "m"

    def __init__(self, *calls: ToolCall) -> None:
        self.calls, self.turn = list(calls), 0

    def complete(self, **_: Any) -> LLMResponse:
        self.turn += 1
        if self.turn == 1:
            return LLMResponse(content="", tool_calls=self.calls)
        return LLMResponse(content="done")


def _run(**agent_options: Any) -> list[str]:
    from shipit_agent import Agent

    calls = [ToolCall(name="list_mcp_resources", arguments={}, id="l1"),
             ToolCall(name="read_mcp_resource", arguments={"server": "secrets", "uri": "vault://prod"}, id="r1")]
    result = Agent(llm=_UsesResources(*calls), tools=[ListMcpResourcesTool(), ReadMcpResourceTool()],
                   mcps=[DOCS, SECRETS], **agent_options).run("go")
    return [str(r.output) for r in result.tool_results]


@pytest.mark.parametrize("rules", [{"disallowed_tools": ["mcp__secrets__*"]}, {"disallowed_tools": ["mcp__*"]}])
def test_a_server_closed_by_a_deny_rule_cannot_be_listed_or_read(rules: dict[str, Any]) -> None:
    listed, read = _run(**rules)
    assert "vault://prod" not in listed and "TOP-SECRET" not in read
    assert "no MCP server" in read


def test_a_deny_rule_through_the_permission_engine_closes_it_too() -> None:
    from shipit_agent.safety.permissions import PermissionEngine

    listed, read = _run(permissions=PermissionEngine(deny=["mcp__secrets__*"]))
    assert "TOP-SECRET" not in read and "vault://prod" not in listed


def test_denying_one_tool_of_a_server_leaves_its_resources_open() -> None:
    listed, read = _run(disallowed_tools=["mcp__secrets__rotate_key"])
    assert "vault://prod" in listed and "TOP-SECRET" in read
