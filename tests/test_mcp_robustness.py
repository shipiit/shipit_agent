"""MCP robustness: name sanitization, cross-server collisions, timeouts,
and re-handshake after a respawn — the failure modes real MCP servers hit."""

from __future__ import annotations

import pytest

from shipit_agent.mcp import (
    MCPError,
    MCPServer,
    MCPTool,
    PersistentMCPSubprocessTransport,
    MCPStreamableHTTPTransport,
    RemoteMCPServer,
    _sanitize_tool_name,
)
from shipit_agent.registry import ToolRegistry


class FakeTransport:
    """In-memory MCP transport with scripted tool listings."""

    def __init__(self, tools):
        self._tools = tools
        self.requests: list[str] = []
        self.generation = 1

    def request(self, method, params=None):
        self.requests.append(method)
        if method == "initialize":
            return {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "serverInfo": {"name": "fake"},
                "instructions": "Prefer ask_question for docs lookups.",
            }
        if method == "tools/list":
            return {"tools": self._tools}
        return {"content": [{"type": "text", "text": "ok"}]}

    def notify(self, method, params=None):
        self.requests.append(method)

    def close(self):
        pass


def test_exposed_names_are_sanitized_unconditionally():
    """The observed `deepwiki**ask_question` must never reach a provider."""
    transport = FakeTransport(
        [{"name": "deepwiki**ask_question", "inputSchema": {"type": "object"}}]
    )
    server = RemoteMCPServer(name="deepwiki", transport=transport)
    [tool] = server.discover_tools()
    assert "*" not in tool.name
    assert tool.name == "deepwiki_ask_question"
    # The wire call still uses the server's exact spelling.
    assert tool.remote_name == "deepwiki**ask_question"
    assert "notifications/initialized" in transport.requests


def test_sanitize_handles_length_and_leading_digit():
    assert len(_sanitize_tool_name("x" * 200)) <= 64
    assert _sanitize_tool_name("1weird")[0].isalpha()
    assert _sanitize_tool_name("***") == "mcp_tool"


def test_cross_server_collision_renames_instead_of_crashing():
    a = MCPServer(name="alpha").register(
        MCPTool(name="lookup", description="a", handler=lambda context, **k: "a")
    )
    b = MCPServer(name="beta").register(
        MCPTool(name="lookup", description="b", handler=lambda context, **k: "b")
    )
    registry = ToolRegistry.build(mcps=[a, b])
    names = {t.name for t in registry.values()}
    assert "lookup" in names
    assert "beta__lookup" in names


def test_server_instructions_are_captured():
    transport = FakeTransport([{"name": "ask", "inputSchema": {"type": "object"}}])
    server = RemoteMCPServer(name="fake", transport=transport)
    server.discover_tools()
    assert "docs lookups" in server.instructions


def test_respawn_triggers_rehandshake():
    transport = FakeTransport([{"name": "ask", "inputSchema": {"type": "object"}}])
    server = RemoteMCPServer(name="fake", transport=transport)
    server.initialize()
    assert transport.requests.count("initialize") == 1
    server.initialize()  # same generation → no second handshake
    assert transport.requests.count("initialize") == 1
    transport.generation += 1  # the subprocess died and was respawned
    server.initialize()
    assert transport.requests.count("initialize") == 2


def test_persistent_transport_timeout_kills_wedged_server():
    import sys

    transport = PersistentMCPSubprocessTransport(
        [sys.executable, "-c", "import time; time.sleep(60)"], timeout=0.5
    )
    with pytest.raises(MCPError, match="timed out"):
        transport.request("tools/list", {})
    transport.close()


def test_server_instructions_reach_the_system_prompt():
    from shipit_agent.tools.helpers import build_tools_prompt

    transport = FakeTransport([{"name": "ask", "inputSchema": {"type": "object"}}])
    server = RemoteMCPServer(name="deepwiki", transport=transport)
    tools = server.discover_tools()
    prompt = build_tools_prompt(tools, mcps=[server])
    assert "## MCP server: deepwiki" in prompt
    assert "docs lookups" in prompt
    # The boilerplate per-tool guidance is NOT repeated under each tool.
    assert "remote server provides the best capability" not in prompt


def test_streamable_notifications_and_close_keep_session_affinity(monkeypatch):
    seen: list[tuple[str, str | None]] = []

    class Response:
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def open_request(req, timeout):
        seen.append((req.method, req.headers.get("Mcp-session-id")))
        return Response()

    monkeypatch.setattr("shipit_agent.mcp.request.urlopen", open_request)
    transport = MCPStreamableHTTPTransport("https://mcp.invalid")
    transport._session_id = "session-7"
    transport.notify("notifications/initialized", {})
    transport.close()
    transport.close()
    assert seen == [("POST", "session-7"), ("DELETE", "session-7")]
