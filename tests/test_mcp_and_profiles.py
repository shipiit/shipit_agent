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
    assert registry.get("lookup") is not None


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
                            "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
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
    result = tool.run(context=type("Ctx", (), {"state": {}, "prompt": "p", "system_prompt": "s", "metadata": {}, "session_id": None})(), query="x")
    assert "remote-ok" in result.text
