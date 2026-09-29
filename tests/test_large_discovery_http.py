"""Large catalogs and real loopback HTTP, with no production service access."""
import json
import random
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from shipit_agent.mcp import MCPStreamableHTTPTransport, RemoteMCPServer
from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.tool_search.tool_search_tool import ToolSearchTool


@pytest.mark.parametrize("size", [100, 500])
@pytest.mark.parametrize("query,expected", [
    ("find underground forum discussions", "forum_search"),
    ("look for threat actor chatter", "forum_search"),
    ("retrieve the incident evidence brief", "case_read"),
    ("read case investigation details", "case_read"),
    ("find a billing receipt", "invoice_lookup"),
    ("retrieve customer invoice", "invoice_lookup"),
    ("search source code repository", "code_search"),
    ("locate a symbol definition", "code_search"),
    ("download webpage article content", "url_fetch"),
    ("read the linked web page", "url_fetch"),
])
def test_mixed_catalog_discovery_is_not_catalog_order_dependent(size, query, expected):
    capabilities = [
        ("forum_search", "Find underground forum discussions and threat actor chatter"),
        ("case_read", "Retrieve incident evidence brief and read case investigation details"),
        ("invoice_lookup", "Find a billing receipt or retrieve a customer invoice"),
        ("code_search", "Search source code repository and locate a symbol definition"),
        ("url_fetch", "Download webpage article content or read the linked web page"),
    ]
    candidates = [{"name": name, "description": description, "read_only": True}
                  for name, description in capabilities]
    candidates += [{"name": name + "_delete", "description": "Delete stored records",
                    "read_only": False} for name, _ in capabilities]
    candidates += [{"name": f"log_archive_{i}", "description": "Read application log events"}
                   for i in range(size - len(candidates))]
    random.Random(31).shuffle(candidates)
    result = ToolSearchTool().run(ToolContext(prompt=query, state={"available_tools": candidates}), query=query)
    assert result.metadata["matches"][0]["name"] == expected


@pytest.mark.parametrize("size", [100, 500])
@pytest.mark.parametrize("query", ["locate invoice using customer email", "billing invoice retrieval", "receipt correspondence"])
def test_large_catalog_paraphrases(size, query):
    candidates = [{"name": f"archive_{i}", "description": "Search archived application logs"} for i in range(size-2)]
    candidates.extend([
        {"name": "invoice_send", "description": "Send an invoice notification to customers"},
        {"name": "invoice_lookup", "description": "Locate billing invoice using customer email",
         "discovery_terms": ["receipt correspondence"]},
    ])
    result = ToolSearchTool().run(ToolContext(prompt=query, state={"available_tools": candidates}), query=query)
    assert result.metadata["matches"][0]["name"] == "invoice_lookup"
    assert len(result.text) < 6000


@pytest.mark.parametrize("failure", [None, 401, 429, 503])
@pytest.mark.parametrize("isolated_failure", [False, True])
def test_real_http_sse_and_failure_isolation(failure, isolated_failure):
    received = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            method = request["method"]
            if method == "tools/call" and failure and (
                not isolated_failure or self.path == "/tenant-b"
            ):
                self.send_error(failure)
                return
            if "id" not in request:
                self.send_response(202)
                self.end_headers()
                return
            if method == "initialize":
                result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                          "serverInfo": {"name": "loopback", "version": "1"}}
            elif method == "tools/list":
                result = {"tools": [{"name": "lookup", "description": "Read fixture", "inputSchema": {"type": "object"}}]}
            else:
                received.append((self.path, self.headers.get("Mcp-Session-Id")))
                result = {"content": [{"type": "text", "text": self.path + "-fixture"}]}
            payload = json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result})
            sse = method == "tools/call"
            body = (f"event: message\ndata: {payload}\n\n" if sse else payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream" if sse else "application/json")
            self.send_header("Mcp-Session-Id", self.path)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()

    def run(tenant):
        transport = MCPStreamableHTTPTransport(f"http://127.0.0.1:{http.server_port}/{tenant}", timeout=3)
        server = RemoteMCPServer(name=tenant, transport=transport)
        try:
            [tool] = server.discover_tools()
            return tool.run(ToolContext(prompt="lookup", session_id=tenant))
        finally:
            server.close()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run, ["tenant-a", "tenant-b"]))
        if failure:
            failed = results[1:] if isolated_failure else results
            assert all(result.metadata.get("ok") is False for result in failed)
            assert all(str(failure) in result.metadata["error"] for result in failed)
            if isolated_failure:
                assert "/tenant-a-fixture" in results[0].text
                assert results[0].metadata.get("ok") is not False
                assert received == [("/tenant-a", "/tenant-a")]
        else:
            assert "/tenant-a-fixture" in results[0].text
            assert "/tenant-b-fixture" in results[1].text
            assert set(received) == {("/tenant-a", "/tenant-a"), ("/tenant-b", "/tenant-b")}
    finally:
        http.shutdown()
        http.server_close()
        thread.join(timeout=3)
