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


def test_remote_mcp_resolves_per_call_metadata_from_context() -> None:
    class MetadataTransport:
        call_params = None

        def request(self, method: str, params=None):
            if method == "initialize":
                return {}
            if method == "tools/list":
                return {
                    "tools": [
                        {
                            "name": "lookup",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"query": {"type": "string"}},
                            },
                        }
                    ]
                }
            if method == "tools/call":
                self.call_params = params
                return {"content": [{"type": "text", "text": "ok"}]}
            raise AssertionError(method)

        def close(self) -> None:
            pass

    transport = MetadataTransport()
    server = RemoteMCPServer(
        name="metadata",
        transport=transport,
        tool_meta_resolver=lambda context, tool, arguments: {
            "tenant_id": context.metadata["tenant_id"],
            "trace_id": context.metadata["trace_id"],
            "tool": tool,
        },
    )
    tool = server.discover_tools()[0]
    context = type(
        "Ctx",
        (),
        {"metadata": {"tenant_id": "acme", "trace_id": "trace-1"}},
    )()

    output = tool.run(context=context, query="shipit")

    assert output.text == "ok"
    assert transport.call_params == {
        "name": "lookup",
        "arguments": {"query": "shipit"},
        "_meta": {
            "tenant_id": "acme",
            "trace_id": "trace-1",
            "tool": "lookup",
        },
    }


def test_mcp_server_namespaces_colliding_tools_but_calls_remote_names() -> None:
    class CollisionTransport:
        def __init__(self, label: str) -> None:
            self.label = label
            self.called_name = None

        def request(self, method: str, params=None):
            if method == "initialize":
                return {}
            if method == "tools/list":
                return {
                    "tools": [
                        {
                            "name": "search",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"query": {"type": "string"}},
                            },
                        }
                    ]
                }
            if method == "tools/call":
                self.called_name = params["name"]
                return {
                    "content": [{"type": "text", "text": self.label}]
                }
            raise AssertionError(method)

        def close(self) -> None:
            pass

    docs_transport = CollisionTransport("docs")
    code_transport = CollisionTransport("code")
    docs = RemoteMCPServer(
        name="docs api",
        transport=docs_transport,
        include_server_in_tool_names=True,
    )
    code = RemoteMCPServer(
        name="code/api",
        transport=code_transport,
        include_server_in_tool_names=True,
    )

    registry = ToolRegistry.build(mcps=[docs, code])

    assert set(registry.tools) == {"docs_api__search", "code_api__search"}
    context = type("Ctx", (), {"metadata": {}})()
    assert registry.get("docs_api__search").run(context, query="x").text == "docs"
    assert registry.get("code_api__search").run(context, query="x").text == "code"
    assert docs_transport.called_name == "search"
    assert code_transport.called_name == "search"


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


def test_remote_mcp_uses_server_supplied_summary() -> None:
    class SummaryTransport:
        def request(self, method: str, params=None):
            if method == "initialize":
                return {}
            if method == "tools/list":
                return {"tools": [{"name": "search", "inputSchema": {"type": "object"}}]}
            if method == "tools/call":
                return {
                    "content": [{"type": "text", "text": "large result body\nrow 1"}],
                    "_meta": {"summary": "6,746 matches"},
                }
            raise AssertionError(method)

        def close(self) -> None:
            pass

    tool = RemoteMCPServer(name="rl", transport=SummaryTransport()).discover_tools()[0]
    output = tool.run(context=type("Ctx", (), {"state": {}})())
    assert output.metadata["summary"] == "6,746 matches"


def test_remote_mcp_short_single_line_result_is_its_summary() -> None:
    class ShortTransport:
        def request(self, method: str, params=None):
            if method == "initialize":
                return {}
            if method == "tools/list":
                return {"tools": [{"name": "groups", "inputSchema": {"type": "object"}}]}
            if method == "tools/call":
                return {"content": [{"type": "text", "text": "12 groups"}]}
            raise AssertionError(method)

        def close(self) -> None:
            pass

    tool = RemoteMCPServer(name="rl", transport=ShortTransport()).discover_tools()[0]
    output = tool.run(context=type("Ctx", (), {"state": {}})())
    assert output.metadata["summary"] == "12 groups"


def test_remote_mcp_strips_undeclared_arguments_for_strict_servers() -> None:
    class StrictTransport:
        called_with = None

        def request(self, method: str, params=None):
            if method == "initialize":
                return {}
            if method == "tools/list":
                return {
                    "tools": [
                        {
                            "name": "read",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"repo": {"type": "string"}},
                                "required": ["repo"],
                            },
                        }
                    ]
                }
            if method == "tools/call":
                self.called_with = params["arguments"]
                return {"content": [{"type": "text", "text": "ok"}]}
            raise AssertionError(method)

        def close(self) -> None:
            pass

    transport = StrictTransport()
    tool = RemoteMCPServer(name="strict", transport=transport).discover_tools()[0]

    output = tool.run(
        context=type("Ctx", (), {"state": {}})(), repo="owner/repo", path="extra"
    )

    assert transport.called_with == {"repo": "owner/repo"}
    assert output.metadata["ignored_arguments"] == ["path"]
