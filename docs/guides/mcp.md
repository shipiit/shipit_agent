# MCP Integration

The [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) lets you attach remote tool servers to your agent without writing any client code. SHIPIT Agent has native MCP support via three transports, plus a prebuilt catalog of well-known servers.

## Prebuilt MCP catalog (recommended)

The fastest path: connect well-known servers by name with `connect_mcp`. Required env vars and the launcher binary (`npx` / `uvx`) are validated up front, so a misconfiguration is one clear message instead of a cryptic subprocess error:

```python
from shipit_agent import Agent, connect_mcp, list_mcp_catalog

github = connect_mcp("github")                       # needs GITHUB_TOKEN
files  = connect_mcp("filesystem", args=["/my/project"])
db     = connect_mcp("postgres", args=["postgresql://localhost/app"])

agent = Agent.with_builtins(llm=llm, mcps=[github, files, db])

for entry in list_mcp_catalog():                     # browse the catalog
    print(entry.name, "—", entry.description)
```

Catalog: `filesystem`, `github`, `gitlab`, `slack`, `postgres`, `sqlite`, `puppeteer`, `brave-search`, `fetch`, `memory`, `sentry`, `google-maps`. Pass `env={...}` to supply credentials explicitly, or `command=[...]` to launch a local build instead of the published package.

Runtime MCP failures (server down, timeout) return a readable tool result the model can react to — they do not crash the run.

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

For local MCP servers launched as subprocesses, pass the full command as a list:

```python
from shipit_agent import MCPStdioTransport, RemoteMCPServer

mcp = RemoteMCPServer(
    name="filesystem",
    transport=MCPStdioTransport(
        command=["npx", "-y", "@modelcontextprotocol/server-filesystem", "/path/to/workspace"],
    ),
)
```

`MCPStdioTransport` spawns one subprocess per request — simple and stateless.

## Persistent sessions

If you want one MCP subprocess to stay alive across requests (faster, and required for session-stateful servers), use the persistent transport — `connect_mcp` uses this under the hood:

```python
from shipit_agent import PersistentMCPSession, RemoteMCPServer

transport = PersistentMCPSession(
    ["npx", "-y", "@modelcontextprotocol/server-filesystem", "./workspace"],
)
mcp = RemoteMCPServer(name="fs", transport=transport)

try:
    agent = Agent(llm=llm, mcps=[mcp])
    result1 = agent.run("List files in workspace.")
    result2 = agent.run("Read the README.")
finally:
    transport.close()
```

The runtime also closes MCP transports automatically when a run finishes.

## Resources & prompts

Beyond tools, MCP servers can expose **resources** (files, tables, docs) and
**prompt templates**. Both are first-class:

```python
server = connect_mcp("filesystem", args=["/my/project"])

for r in server.list_resources():          # browse what's available
    print(r.uri, "—", r.name)
readme = server.read_resource("file:///my/project/README.md")

for p in server.list_prompts():             # prompt templates
    print(p.name, "—", p.description)
text = server.get_prompt("review", {"file": "app.py"})
agent.run(text)                             # use it like a slash command
```

Give the **model** access to a server's resources with one extra tool:

```python
agent = Agent(llm=llm, mcps=[server], tools=[server.resource_tool()])
# the agent can now call `filesystem_resources` to list/read resources
```

Servers that don't implement resources or prompts simply return empty lists —
no errors to handle.

## Streamable HTTP + authenticated remote servers

For hosted MCP servers on the 2025 streamable-HTTP spec (JSON *or* SSE
responses, `Mcp-Session-Id` affinity), use `MCPStreamableHTTPTransport`; pass
`bearer_token=` for OAuth/bearer-protected endpoints:

```python
from shipit_agent import MCPStreamableHTTPTransport, RemoteMCPServer

mcp = RemoteMCPServer(
    name="hosted",
    transport=MCPStreamableHTTPTransport(
        "https://mcp.example.com/mcp",
        bearer_token=os.environ["MCP_TOKEN"],
    ),
)
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
        connect_mcp("filesystem", args=["./workspace"]),
    ],
)
```

All tools — local and MCP — appear in the single tool registry the LLM sees. `ToolSearchTool` indexes MCP tools too.

## Debugging

- Use `agent.doctor()` to get a health report including MCP server reachability
- MCP tool calls emit the same `tool_called` / `tool_completed` events as local tools — render them with `format_activity(result)` or live with `format_event_line(event)`
- Tool arguments and outputs are captured in the trace store

## Related

- [The super agent](super-agent.md)
- [MCP spec](https://modelcontextprotocol.io/)
- [Prebuilt tools](prebuilt-tools.md)
