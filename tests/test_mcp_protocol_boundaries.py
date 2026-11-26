"""Keep malformed or unrelated MCP responses out of agent evidence."""

import json
from io import BytesIO

import pytest

from shipit_agent.mcp import (
    MCPError, MCPHTTPTransport, MCPStreamableHTTPTransport, RemoteMCPServer,
)


def respond(monkeypatch, body, content_type="application/json"):
    response = BytesIO(body.encode())
    response.headers = {
        "Content-Type": content_type, "Mcp-Session-Id": "new-session",
    }
    monkeypatch.setattr("shipit_agent.mcp.request.urlopen", lambda *a, **k: response)


@pytest.mark.parametrize("transport_cls", [MCPHTTPTransport, MCPStreamableHTTPTransport])
@pytest.mark.parametrize("response_id", [None, True, "1", 2])
def test_rejects_unrelated_response(monkeypatch, transport_cls, response_id):
    respond(monkeypatch, json.dumps({"id": response_id, "result": {"tools": []}}))
    transport = transport_cls("https://example.test/mcp")
    with pytest.raises(MCPError, match="response id"):
        transport.request("tools/list")
    if isinstance(transport, MCPStreamableHTTPTransport):
        assert transport._session_id is None


@pytest.mark.parametrize("transport_cls", [MCPHTTPTransport, MCPStreamableHTTPTransport])
@pytest.mark.parametrize("body", ["not json", '{"id":1,"result":[]}', '{"id":1}'])
def test_rejects_malformed_response(monkeypatch, transport_cls, body):
    respond(monkeypatch, body)
    with pytest.raises(MCPError):
        transport_cls("https://example.test/mcp").request("tools/list")


def test_sse_selects_matching_response_and_updates_session(monkeypatch):
    events = [
        {"method": "notifications/progress", "params": {}},
        {"id": 9, "error": {"message": "unrelated failure"}},
        {"id": 1, "result": {"tools": [{"name": "correct"}]}},
    ]
    respond(monkeypatch, "".join("data: " + json.dumps(e) + "\r\n\r\n" for e in events),
            "text/event-stream")
    transport = MCPStreamableHTTPTransport("https://example.test/mcp")
    assert transport.request("tools/list") == {"tools": [{"name": "correct"}]}
    assert transport._session_id == "new-session"


class Pages:
    def __init__(self, pages):
        self.pages = iter(pages)
        self.params = []

    def request(self, method, params=None):
        if method == "initialize":
            return {"capabilities": {}}
        self.params.append(params)
        return next(self.pages)

    def notify(self, *args):
        pass

    def close(self):
        pass


def test_pagination_preserves_opaque_cursor_and_finishes_at_limit():
    transport = Pages([
        {"tools": [{"name": "a"}], "nextCursor": " opaque/+== "},
        {"tools": [{"name": "b"}]},
    ])
    server = RemoteMCPServer(name="pages", transport=transport, max_discovery_pages=2)
    assert len(server.discover_tools()) == 2
    assert transport.params == [{}, {"cursor": " opaque/+== "}]


def test_unbounded_cursor_sequence_fails_without_partial_tool_catalog():
    transport = Pages([
        {"tools": [{"name": "a"}], "nextCursor": "one"},
        {"tools": [{"name": "b"}], "nextCursor": "two"},
    ])
    server = RemoteMCPServer(name="pages", transport=transport, max_discovery_pages=2)
    with pytest.raises(MCPError, match="max_discovery_pages=2"):
        server.discover_tools()
    assert len(transport.params) == 2
    assert server.tools == []
    assert not server._discovered


@pytest.mark.parametrize("page", [{}, {"tools": {}}, {"tools": ["bad"]},
                                  {"tools": [], "nextCursor": 123}])
def test_invalid_page_is_not_silently_accepted(page):
    server = RemoteMCPServer(name="pages", transport=Pages([page]))
    with pytest.raises(MCPError, match="Invalid tools/list"):
        server.discover_tools()
