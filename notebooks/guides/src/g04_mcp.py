"""Guide 04: MCP servers, local and from the catalog."""

from cells import code, md

TITLE = "MCP servers"

SERVER = r'''
"""A tiny MCP server over stdio: team notes, with tools, resources and a prompt."""
import json
import sys
from pathlib import Path

STORE = Path("notes.json")
DEFAULT_NOTES = {
    "deploy": "Deploys go out Tuesdays and Thursdays at 14:00 UTC. Freeze the day before a holiday.",
    "oncall": "On-call rotates weekly on Monday. Page #oncall first, then the secondary.",
    "release": "Release notes live in CHANGELOG.md; tag as vX.Y.Z after the notes merge.",
}
TOOLS = [
    {"name": "search_notes", "description": "Search the team notes by keyword and return matching notes.",
     "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
     "annotations": {"readOnlyHint": True}},
    {"name": "add_note", "description": "Add or replace a team note under a topic.",
     "inputSchema": {"type": "object", "properties": {"topic": {"type": "string"}, "text": {"type": "string"}},
                     "required": ["topic", "text"]}},
]


def load():
    return json.loads(STORE.read_text()) if STORE.exists() else dict(DEFAULT_NOTES)


def handle(method, params):
    NOTES = load()
    if method == "initialize":
        return {"protocolVersion": "2025-06-18", "serverInfo": {"name": "notes", "version": "1.0"},
                "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                "instructions": "Team notes. Search before answering process questions."}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        name, args = params["name"], params.get("arguments", {})
        if name == "search_notes":
            q = args["query"].lower()
            hits = {k: v for k, v in NOTES.items() if q in k or q in v.lower()}
            text = json.dumps(hits) if hits else f"no note mentions {args['query']!r}"
        else:
            NOTES[args["topic"]] = args["text"]
            STORE.write_text(json.dumps(NOTES))
            text = f"saved note {args['topic']!r}"
        return {"content": [{"type": "text", "text": text}], "isError": False}
    if method == "resources/list":
        return {"resources": [{"uri": f"notes://{k}", "name": k, "mimeType": "text/plain"} for k in NOTES]}
    if method == "resources/read":
        key = params["uri"].removeprefix("notes://")
        return {"contents": [{"uri": params["uri"], "mimeType": "text/plain", "text": NOTES.get(key, "")}]}
    if method == "prompts/list":
        return {"prompts": [{"name": "handover", "description": "Write an on-call handover.",
                             "arguments": [{"name": "who", "required": True}]}]}
    if method == "prompts/get":
        who = params.get("arguments", {}).get("who", "the next person")
        return {"messages": [{"role": "user", "content": {"type": "text",
                "text": f"Write a short on-call handover for {who}, using the oncall note."}}]}
    if method == "ping":
        return {}
    raise ValueError(f"unsupported method {method}")


for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request:
        continue
    try:
        reply = {"result": handle(request["method"], request.get("params", {}))}
    except Exception as error:
        reply = {"error": {"code": -32601, "message": str(error)}}
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], **reply}), flush=True)
'''

CELLS = [
    md("""
    # Guide 04 · MCP servers

    The Model Context Protocol (MCP) is a standard way to give an agent tools that live in another process:
    a local program that talks over stdin and stdout, or a hosted server over HTTP. shipit connects to either,
    discovers the tools, and the agent calls them like its own.

    **What you'll learn**

    1. Write and run a small MCP server (so you see both sides)
    2. Connect to it, discover its tools, call them by hand
    3. Give it to an agent, alongside local tools
    4. Filter and namespace server tools
    5. Resources and prompts, not just tools
    6. The prebuilt catalog: 28 servers by name

    Every output below is real, from Haiku 5.5 (Anthropic) and Gemma 4 31B (Bedrock).
    """),
    md("""
    ## 1 · Models
    """),
    code("""
    import os
    import sys
    from pathlib import Path

    from shipit_agent import Agent
    from shipit_agent.llms import build_llm_from_env
    from shipit_agent.llms.factory import build_llm_from_settings

    os.environ["SHIPIT_ANTHROPIC_MODEL"] = "claude-haiku-5-5"
    haiku = build_llm_from_env("anthropic")
    gemma = build_llm_from_settings({"model": "google.gemma-4-31b"}, provider="bedrock")
    """),
    md("""
    ## 2 · A tiny MCP server

    An MCP server over stdio reads one JSON-RPC request per line and writes one reply per line. This one keeps
    team notes in `notes.json` and offers two tools, readable resources, and a prompt. In practice you'd use an SDK or an
    existing server; writing one by hand shows there's no magic.
    """),
    code(f'''
    SERVER = {SERVER!r}
    Path("notes_server.py").write_text(SERVER)
    print(len(SERVER.splitlines()), "lines written to notes_server.py")
    '''),
    md("""
    ## 3 · Connect and discover

    `RemoteMCPServer` with an `MCPStdioTransport` starts the server as a subprocess. `discover_tools()` runs the
    handshake and lists what it offers.
    """),
    code("""
    from shipit_agent import MCPStdioTransport, RemoteMCPServer

    notes = RemoteMCPServer(name="notes", transport=MCPStdioTransport(command=[sys.executable, "notes_server.py"]))
    for tool in notes.discover_tools():
        print(f"{tool.name:13} {tool.description}")
    print("server:", notes.server_info, "| says:", notes.instructions)
    """),
    md("""
    ## 4 · Call a tool by hand

    Each discovered tool is an ordinary shipit tool, with a schema and `run()`.
    """),
    code("""
    from shipit_agent.tools.base import ToolContext

    search = next(t for t in notes.discover_tools() if t.name == "search_notes")
    print(search.run(ToolContext(prompt="demo"), query="deploy").text)
    """),
    md("""
    ## 5 · Give it to an agent

    Pass servers in `mcps=`. The agent discovers their tools when the run starts and calls them like its own.
    """),
    code("""
    agent = Agent(llm=haiku, prompt="Answer from the team notes. Be brief.", mcps=[notes])
    result = agent.run("When do deploys go out?")
    print(result.output)
    print("calls:", [(r.name, r.output[:60]) for r in result.tool_results])
    """),
    md("""
    ## 6 · MCP tools beside your own

    Local tools and MCP tools mix freely in one agent.
    """),
    code("""
    from datetime import date

    from shipit_agent.tools import FunctionTool

    def today() -> str:
        \"\"\"Today's date and weekday.\"\"\"
        return date(2026, 11, 9).strftime("%A %Y-%m-%d")

    agent = Agent(llm=haiku, prompt="Answer from the team notes. Be brief.", mcps=[notes],
                  tools=[FunctionTool.from_callable(today, read_only=True)])
    result = agent.run("Is there a deploy today? Check the date and the notes.")
    print(result.output)
    print("calls:", [r.name for r in result.tool_results])
    """),
    md("""
    ## 7 · Writes through MCP

    `add_note` has no read-only hint, so it's a write. With the default permission mode an agent would ask
    first; Guide 09 covers that. Here the run is allowed to write.
    """),
    code("""
    writer = Agent(llm=haiku, prompt="Keep the team notes current. Be brief.", mcps=[notes],
                   permission_mode="bypassPermissions")
    print(writer.run("Add a note under 'freeze': no deploys from Dec 20 to Jan 3.").output)
    print(search.run(ToolContext(prompt="demo"), query="freeze").text)
    """),
    md("""
    ## 8 · Only some of a server's tools

    `allowed_tools` keeps a server read-only for an agent; `blocked_tools` removes named ones.
    """),
    code("""
    read_only = RemoteMCPServer(name="notes", transport=MCPStdioTransport(command=[sys.executable, "notes_server.py"]),
                                allowed_tools={"search_notes"})
    print([t.name for t in read_only.discover_tools()])
    """),
    md("""
    ## 9 · Namespaced names

    Two servers can both have a `search` tool. `include_server_in_tool_names=True` shows the model
    `notes__search_notes` while the server still receives `search_notes`.
    """),
    code("""
    named = RemoteMCPServer(name="notes", transport=MCPStdioTransport(command=[sys.executable, "notes_server.py"]),
                            include_server_in_tool_names=True)
    print([t.name for t in named.discover_tools()])
    print(Agent(llm=haiku, prompt="Be brief.", mcps=[named]).run("What does the oncall note say?").output)
    """),
    md("""
    ## 10 · Resources

    Resources are documents a server exposes for reading, addressed by URI.
    """),
    code("""
    for r in notes.list_resources():
        print(r.uri, "|", r.name)
    print(notes.read_resource("notes://release"))
    """),
    md("""
    ## 11 · Prompts

    A server can ship prompt templates. `get_prompt()` fills one in, ready to send to an agent.
    """),
    code("""
    print([p.name for p in notes.list_prompts()])
    handover = notes.get_prompt("handover", {"who": "Priya"})
    print(handover)
    print("\\n" + Agent(llm=haiku, mcps=[notes]).run(handover).output)
    """),
    md("""
    ## 12 · Streaming MCP calls

    MCP calls appear in the stream like any tool call.
    """),
    code("""
    for e in Agent(llm=haiku, prompt="Be brief.", mcps=[notes]).stream("Who do I page first when on call?"):
        if e.type == "tool_called":
            print("call", e.payload["tool"], e.payload["arguments"])
        elif e.type == "run_completed":
            print(e.payload["output"])
    """),
    md("""
    ## 13 · The same server on Gemma 4
    """),
    code("""
    result = Agent(llm=gemma, prompt="Answer from the team notes. Be brief.", mcps=[notes]).run(
        "Where do release notes go, and how do we tag a release?")
    print(result.output)
    print("calls:", [r.name for r in result.tool_results])
    """),
    md("""
    ## 14 · The prebuilt catalog

    shipit ships 28 well-known servers you connect by name with `connect_mcp(name, ...)`. Each entry knows its
    launcher, its required environment variables, and whether it's hosted (HTTP) or local (stdio).
    """),
    code("""
    from shipit_agent import list_mcp_catalog

    catalog = list_mcp_catalog()
    print(len(catalog), "servers")
    for c in catalog[:12]:
        how = "hosted" if c.url else "stdio "
        print(f"{c.name:16} {how} {c.auth:5} {c.description}")
    """),
    md("""
    Connecting one is a line. Local catalog servers start through `npx` or `uvx`, so they need Node or uv;
    hosted ones that use per-user OAuth take that user's token:

    ```python
    files = connect_mcp("filesystem", args=["/path/to/project"])
    github = connect_mcp("github", token=os.environ["GITHUB_TOKEN"])
    agent = Agent(llm=llm, mcps=[files, github])
    ```

    This guide doesn't run them, because each downloads its server package on first use.

    ## 15 · Clean up
    """),
    code("""
    for server in (notes, read_only, named):
        server.close()
    Path("notes_server.py").unlink()
    Path("notes.json").unlink(missing_ok=True)
    """),
    md("""
    ## 16 · Summary

    - An MCP server is a process speaking JSON-RPC; `RemoteMCPServer` + `MCPStdioTransport` runs one locally.
    - `discover_tools()` lists tools; `mcps=[...]` gives them to an agent, beside local tools.
    - `allowed_tools`, `blocked_tools` and `include_server_in_tool_names` shape what the agent sees.
    - Servers also offer resources (`list_resources`, `read_resource`) and prompts (`get_prompt`).
    - `connect_mcp(name, ...)` attaches any of the 28 catalog servers.

    **Next:** Guide 05 — connections and OAuth.
    """),
]
