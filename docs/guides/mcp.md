# MCP Integration

The [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) lets you attach remote tool servers to your agent without writing any client code. SHIPIT Agent has native MCP support via three transports.

## Remote HTTP MCP server

```python
from shipit_agent import Agent, MCPHTTPTransport, RemoteMCPServer
from shipit_agent.llms import OpenAIChatLLM

mcp = RemoteMCPServer(
    name="project_docs",
    transport=MCPHTTPTransport("http://localhost:8080/mcp"),
)

agent = Agent.with_builtins(
    llm=OpenAIChatLLM(model="gpt-4o-mini"),
    mcps=[mcp],
)

result = agent.run("What does the README say about MCP?")
```

The `mcp_attached` event fires once per server when `stream()` starts.

## stdio subprocess MCP server

For local MCP servers launched as subprocesses:

```python
from shipit_agent import MCPStdioTransport, RemoteMCPServer

mcp = RemoteMCPServer(
    name="filesystem",
    transport=MCPStdioTransport(
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", "/path/to/workspace"],
    ),
)
```

The subprocess is kept alive for the duration of the agent run and cleaned up automatically on `run_completed`.

## Persistent sessions

If you want the MCP subprocess to stay alive across multiple `agent.run()` calls (for session-stateful servers), use a persistent session:

```python
from shipit_agent import PersistentMCPSession

session = PersistentMCPSession(mcp)
session.start()

try:
    agent = Agent(llm=llm, mcps=[session])
    result1 = agent.run("List files in workspace.")
    result2 = agent.run("Read the README.")
finally:
    session.close()
```

## Mixing MCP tools with local tools

```python
agent = Agent(
    llm=llm,
    tools=[
        WebSearchTool(),
        OpenURLTool(),
        ToolSearchTool(),
    ],
    mcps=[
        RemoteMCPServer(name="docs", transport=MCPHTTPTransport("http://localhost:8080/mcp")),
        RemoteMCPServer(name="fs", transport=MCPStdioTransport(command="npx", args=["-y", "@modelcontextprotocol/server-filesystem", "./workspace"])),
    ],
)
```

All tools — local and MCP — appear in the single tool registry the LLM sees. `ToolSearchTool` indexes MCP tools too.

## Debugging

- Use `agent.doctor()` to get a health report including MCP server reachability
- MCP tool calls emit the same `tool_called` / `tool_completed` events as local tools
- Tool arguments and outputs are captured in the trace store

## Related

- [MCP spec](https://modelcontextprotocol.io/)
- [Prebuilt tools](prebuilt-tools.md)
