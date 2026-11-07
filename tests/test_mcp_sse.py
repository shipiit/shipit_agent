"""MCP over the HTTP+SSE transport, as in the Claude Agent SDK's {"type": "sse"}.

The client opens a GET stream; the server's first event names the URL to
POST JSON-RPC messages to, and every response comes back on the stream,
matched by id. A real local server, in a thread, speaks that protocol here.
"""

from __future__ import annotations

import json
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Iterator

import pytest

from shipit_agent.core.models import ToolCall
from shipit_agent.llms import LLMResponse
from shipit_agent.mcp import MCPError
from shipit_agent.mcp.sse import MCPSSETransport
from shipit_agent.sdk import AgentOptions, ResultMessage, query

TOOLS = [{"name": "stock", "description": "Units in stock", "inputSchema": {"type": "object", "properties": {"sku": {"type": "string"}}}}]


def _answer(message: dict[str, Any]) -> dict[str, Any] | None:
    method, msg_id = message.get("method"), message.get("id")
    if msg_id is None:
        return None  # a notification
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                                                           "serverInfo": {"name": "fake", "version": "1"}}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        sku = message["params"]["arguments"]["sku"]
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"content": [{"type": "text", "text": f"{sku}: 35 units"}]}}
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"no method {method}"}}


@pytest.fixture
def sse_server() -> Iterator[tuple[str, list[dict[str, Any]]]]:
    outbox: queue.Queue[str | None] = queue.Queue()
    received: list[dict[str, Any]] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_: Any) -> None:
            pass

        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b"event: endpoint\ndata: /messages?session=1\n\n")
            self.wfile.flush()
            while (item := outbox.get()) is not None:
                self.wfile.write(item.encode())
                self.wfile.flush()

        def do_POST(self) -> None:
            message = json.loads(self.rfile.read(int(self.headers["content-length"])))
            received.append(message)
            self.send_response(202)
            self.end_headers()
            answer = _answer(message)
            if answer is not None:
                outbox.put(f"event: message\ndata: {json.dumps(answer)}\n\n")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/sse", received
    outbox.put(None)
    server.shutdown()


def test_a_request_goes_out_by_post_and_its_answer_comes_back_on_the_stream(sse_server) -> None:
    url, received = sse_server
    transport = MCPSSETransport(url, timeout=5)
    try:
        assert transport.request("initialize")["serverInfo"]["name"] == "fake"
        assert transport.request("tools/list")["tools"][0]["name"] == "stock"
        transport.notify("notifications/initialized")
        with pytest.raises(MCPError, match="no method"):
            transport.request("nope")
    finally:
        transport.close()
    assert [m.get("method") for m in received] == ["initialize", "tools/list", "notifications/initialized", "nope"]


class CallsStock:
    model = "m"

    def complete(self, *, messages, tools=None, **_):
        if any(m.role == "tool" for m in messages):
            return LLMResponse(content=[m for m in messages if m.role == "tool"][-1].content)
        return LLMResponse(tool_calls=[ToolCall(name="inv__stock", arguments={"sku": "SKU-7"})])


def test_an_agent_calls_a_tool_on_an_sse_server(sse_server) -> None:
    import asyncio

    url, _ = sse_server

    async def run() -> str:
        options = AgentOptions(llm=CallsStock(), tools=[], mcp_servers={"inv": {"type": "sse", "url": url}})
        async for message in query(prompt="stock of SKU-7?", options=options):
            if isinstance(message, ResultMessage):
                return message.result or ""
        return ""

    assert "SKU-7: 35 units" in asyncio.run(run())


def test_closing_does_not_wait_for_the_stream_to_time_out(sse_server) -> None:
    import time

    url, _ = sse_server
    transport = MCPSSETransport(url, timeout=5)
    transport.request("initialize")
    started = time.monotonic()
    transport.close()
    assert time.monotonic() - started < 1.0


def test_only_http_and_https_urls_are_used() -> None:
    with pytest.raises(MCPError, match="http or https"):
        MCPSSETransport("file:///etc/passwd", timeout=1).request("initialize")
