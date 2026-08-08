from shipit_agent import MCPServer, MCPTool, RemoteMCPServer, ToolRegistry
from shipit_agent.llms import SimpleEchoLLM
from shipit_agent.profiles import AgentProfileBuilder


def test_mcp_tools_are_exposed_through_registry() -> None:
    mcp = MCPServer(name="demo").register(
        MCPTool(
            name="lookup",
            description="Lookup data",
            handler=lambda context, **kwargs: "ok",
        )
    )
    registry = ToolRegistry.build(mcps=[mcp])
    tool = registry.get("lookup")
    assert tool is not None
    assert tool.metadata["server"] == "demo"


def test_profile_builder_creates_agent() -> None:
    agent = (
        AgentProfileBuilder("shipit")
        .prompt("You are precise.")
        .description("Profile test")
        .max_iterations(3)
        .build(llm=SimpleEchoLLM())
    )
    result = agent.run("hello")
    assert "hello" in result.output.lower()
    assert agent.max_iterations == 3


def test_remote_mcp_server_discovers_tools() -> None:
    class FakeTransport:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def request(self, method: str, params=None):
            self.calls.append(method)
            if method == "initialize":
                return {"protocolVersion": "2024-11-05"}
            if method == "tools/list":
                return {
                    "tools": [
                        {
                            "name": "remote_lookup",
                            "description": "Lookup from remote MCP",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"query": {"type": "string"}},
                                "required": ["query"],
                            },
                        }
                    ]
                }
            if method == "tools/call":
                return {"content": [{"type": "text", "text": "remote-ok"}]}
            raise AssertionError(method)

    server = RemoteMCPServer(name="remote", transport=FakeTransport())
    registry = ToolRegistry.build(mcps=[server])
    tool = registry.get("remote_lookup")
    assert tool is not None
    result = tool.run(
        context=type(
            "Ctx",
            (),
            {
                "state": {},
                "prompt": "p",
                "system_prompt": "s",
                "metadata": {},
                "session_id": None,
            },
        )(),
        query="x",
    )
    assert "remote-ok" in result.text


def test_remote_mcp_server_reinitializes_cached_tools_after_close() -> None:
    class RestartableTransport:
        def __init__(self) -> None:
            self.calls: list[str] = []
            self.close_count = 0

        def request(self, method: str, params=None):
            self.calls.append(method)
            if method == "initialize":
                return {"protocolVersion": "2024-11-05"}
            if method == "tools/list":
                return {
                    "tools": [
                        {
                            "name": "lookup",
                            "description": "Lookup",
                            "inputSchema": {"type": "object", "properties": {}},
                        }
                    ]
                }
            if method == "tools/call":
                return {"content": [{"type": "text", "text": "ok"}]}
            raise AssertionError(method)

        def close(self) -> None:
            self.close_count += 1

    transport = RestartableTransport()
    server = RemoteMCPServer(name="restartable", transport=transport)

    first = server.discover_tools()
    server.close()
    second = server.discover_tools()
    result = second[0].run(context=type("Ctx", (), {"state": {}})())

    assert first[0] is second[0]
    assert transport.calls.count("initialize") == 2
    assert transport.calls.count("tools/list") == 1
    assert transport.close_count == 1
    assert result.text == "ok"


def test_remote_mcp_filters_tools_before_registry_exposure() -> None:
    class FilterTransport:
        def request(self, method: str, params=None):
            if method == "initialize":
                return {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {"tools": {"listChanged": True}},
                    "serverInfo": {"name": "filtered-server"},
                }
            if method == "tools/list":
                return {
                    "tools": [
                        {"name": "read", "inputSchema": {"type": "object"}},
                        {"name": "write", "inputSchema": {"type": "object"}},
                        {"name": "admin", "inputSchema": {"type": "object"}},
                    ]
                }
            raise AssertionError(method)

        def close(self) -> None:
            pass

    server = RemoteMCPServer(
        name="filtered",
        transport=FilterTransport(),
        allowed_tools={"read", "write"},
        blocked_tools={"write"},
        tool_filter=lambda item: item["name"] != "admin",
    )

    assert [tool.name for tool in server.discover_tools()] == ["read"]
    assert server.protocol_version == "2025-11-25"
    assert server.server_capabilities == {"tools": {"listChanged": True}}
    assert server.server_info == {"name": "filtered-server"}


def test_remote_mcp_preserves_structured_and_multimodal_tool_results() -> None:
    class RichTransport:
        def request(self, method: str, params=None):
            if method == "initialize":
                return {}
            if method == "tools/list":
                return {
                    "tools": [
                        {
                            "name": "inspect",
                            "title": "Inspect artifact",
                            "inputSchema": {"type": "object"},
                            "outputSchema": {
                                "type": "object",
                                "properties": {"score": {"type": "number"}},
                            },
                            "annotations": {"readOnlyHint": True},
                            "execution": {"taskSupport": "optional"},
                        }
                    ]
                }
            if method == "tools/call":
                return {
                    "content": [
                        {"type": "text", "text": "inspection complete"},
                        {"type": "image", "mimeType": "image/png", "data": "abc"},
                        {
                            "type": "resource_link",
                            "uri": "file:///report.json",
                            "name": "report",
                        },
                    ],
                    "structuredContent": {"score": 0.9},
                    "isError": False,
                }
            raise AssertionError(method)

        def close(self) -> None:
            pass

    tool = RemoteMCPServer(name="rich", transport=RichTransport()).discover_tools()[0]
    output = tool.run(context=type("Ctx", (), {"state": {}})())

    assert "inspection complete" in output.text
    assert "[image: image/png]" in output.text
    assert "file:///report.json" in output.text
    assert output.metadata["structured_content"] == {"score": 0.9}
    assert output.metadata["output_schema"]["properties"]["score"] == {"type": "number"}
    assert output.metadata["annotations"] == {"readOnlyHint": True}
    assert output.metadata["execution"] == {"taskSupport": "optional"}
