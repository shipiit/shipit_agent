"""Guide 15: the safe defaults in 4.0, each one demonstrated."""

from cells import code, md

TITLE = "Secure by default"
SINCE = "4.0"

CELLS = [
    md("""
    # Guide 15 · Secure by default

    An agent reads things you don't control: web pages, files, tool results. Any of them can try to steer the
    model. 4.0 assumes that, so the safe choice is the one you get without asking. This guide shows each
    default refusing something, and the line that changes it when you need to.

    **What you'll learn**

    1. URL tools stay on the public internet
    2. File tools stay in the project, and an edit must say what it replaces
    3. Traces are scrubbed before they leave
    4. The server needs a key off this machine
    5. An MCP server's reply must answer the request it was sent
    6. An `async` hook on the `Agent` class is an error, not a silent pass
    7. A real agent meeting the first default

    Sections 1 to 6 need no model and no key. Section 7 is real output from Haiku 5.5 (Anthropic).
    """),
    md("""
    ## 1 · URL tools stay on the public internet

    `open_url`, `fetch_url`, `download_file`, `pdf` and the browser tools resolve a host before they connect
    and refuse private, loopback, link-local and cloud-metadata addresses. The check runs again on every
    redirect, and the connection is pinned to the address that was checked.
    """),
    code("""
    from shipit_agent.tools.open_url.safe_fetch import checked_address
    from shipit_agent.tools.open_url.url_safety import URLNotAllowedError

    for url in [
        "https://example.com/",
        "http://169.254.169.254/latest/meta-data/",   # cloud metadata
        "http://127.0.0.1:8080/admin",                # this machine
        "http://10.0.0.5/",                           # a private network
        "file:///etc/passwd",                         # not http at all
    ]:
        try:
            checked_address(url)
            print(f"allowed  {url}")
        except URLNotAllowedError as error:
            print(f"refused  {url}\\n         {str(error)[:86]}")
    """),
    md("""
    The tool turns that refusal into an error the model can read. An agent that works inside your own network
    opts out, one tool at a time.
    """),
    code("""
    from shipit_agent.tools.base import ToolContext
    from shipit_agent.tools.open_url import OpenURLTool

    context = ToolContext(prompt="demo")
    result = OpenURLTool().run(context, url="http://169.254.169.254/latest/meta-data/")
    print(result.text[:150])
    print("blocked:", result.metadata.get("blocked"))

    intranet = OpenURLTool(allow_private_hosts=True)
    print("opt-out is per tool:", intranet.allow_private_hosts)
    """),
    md("""
    ## 2 · File tools stay in the project

    Every file tool resolves the path it is given and refuses one that lands outside the project root. 4.0
    also refuses an edit whose `old_text` is empty: before, that prepended text to the file.
    """),
    code("""
    import shutil
    from pathlib import Path

    from shipit_agent.tools.edit_file import EditFileTool
    from shipit_agent.tools.file_read import FileReadTool

    project = Path("secure_demo").resolve()
    shutil.rmtree(project, ignore_errors=True)
    project.mkdir()
    (project / "settings.py").write_text("DEBUG = False\\n")

    read, edit = FileReadTool(root_dir=project), EditFileTool(root_dir=project)
    read.run(context, path="settings.py")  # an edit must follow a read of the current contents

    attempts = [
        ("outside the project", {"path": "../outside.py", "old_text": "x", "new_text": "y"}),
        ("empty old_text", {"path": "settings.py", "old_text": "", "new_text": "import os\\n"}),
        ("a real edit", {"path": "settings.py", "old_text": "DEBUG = False", "new_text": "DEBUG = True"}),
    ]
    for label, arguments in attempts:
        try:
            output = edit.run(context, **arguments)
            verdict = output.metadata.get("error") or "applied"
        except ValueError as error:
            verdict = str(error).split(":")[0]
        print(f"{label:20} {verdict}")
    print((project / "settings.py").read_text().strip())
    """),
    md("""
    ## 3 · Traces are scrubbed before they leave

    A trace carries prompts, tool arguments and tool output to wherever you export it. Wrap any trace store or
    exporter in `RedactingTraceStore` and it only ever receives scrubbed copies: secrets always, and with
    `pii=True` emails, phone numbers and card numbers too. The run's own events are untouched, and ids are
    kept so traces still join up.
    """),
    code("""
    from shipit_agent import InMemoryTraceStore
    from shipit_agent.models import AgentEvent
    from shipit_agent.tracing_exporters import RedactingTraceStore

    exported = InMemoryTraceStore()                       # stands in for Langfuse, OTLP, a file
    store = RedactingTraceStore(exported, pii=True)

    event = AgentEvent(
        type="tool_called",
        message="Calling billing with key sk-live-4f9a8b7c6d5e4f3a2b1c for ada@example.com",
        payload={"run_id": "fd6792f8-033f-41f3-a182-4455667f7453",
                 "arguments": {"api_key": "abc123", "note": "call +1 415 555 0134", "input_tokens": 120}},
    )
    store.append_event("trace-1", event)

    sent = exported.load("trace-1").events[0]
    print("exported:", sent.message)
    print("         ", sent.payload)
    print("in the run:", event.message)
    """),
    md("""
    ## 4 · The server needs a key off this machine

    `shipit serve` runs your agent, bash included, for whoever can reach it. On `127.0.0.1` that is you. Bound
    to any other address it refuses to start without a key. It does not invent one, because a generated key
    would have to be printed, and printed keys end up in logs.
    """),
    code("""
    from shipit_agent import Agent
    from shipit_agent.cli.serve import AgentServer
    from shipit_agent.llms.factory import build_llm_from_settings

    agent = Agent(llm=build_llm_from_settings(None, provider="shipit"))  # the offline model: no key, no network

    for host, key in [("127.0.0.1", None), ("0.0.0.0", None), ("0.0.0.0", "demo-key-not-a-real-secret")]:
        server = AgentServer(agent, api_key=key)
        try:
            server.require_key_for(host)
            print(f"{host:10} key={'yes' if key else 'no ':3}  starts")
        except ValueError as error:
            print(f"{host:10} key={'yes' if key else 'no ':3}  refused: {str(error)[:58]}")
    """),
    md("""
    ## 5 · An MCP reply must answer the request it was sent

    An MCP server is another program, sometimes someone else's. 4.0 checks every HTTP reply: it must be a
    JSON-RPC object, carry the id of the request, and hold a result. Here a small local server answers
    `tools/call` with the wrong id, as a confused or hostile server might.
    """),
    code("""
    import http.server
    import json
    import threading

    from shipit_agent.mcp.http import MCPHTTPTransport
    from shipit_agent.mcp.transport import MCPError


    class WrongIdOnCalls(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["content-length"])))
            reply_id = request["id"] + (1 if request["method"] == "tools/call" else 0)
            body = json.dumps({"jsonrpc": "2.0", "id": reply_id, "result": {"ok": True}}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass


    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), WrongIdOnCalls)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    transport = MCPHTTPTransport(f"http://127.0.0.1:{httpd.server_port}/mcp")

    print("tools/list:", transport.request("tools/list"))
    try:
        transport.request("tools/call", {"name": "anything"})
    except MCPError as error:
        print("tools/call:", error)
    httpd.shutdown()
    """),
    md("""
    ## 6 · An `async` hook is an error, not a silent pass

    Hooks on the `Agent` class are plain functions. Before 4.0, an `async def` hook returned a coroutine that
    nobody awaited, which read as "no decision": a deny hook written as `async` let every call through. Now
    it raises, so the mistake shows up the first time the hook runs.
    """),
    code("""
    from shipit_agent import AgentHooks

    hooks = AgentHooks()


    @hooks.on_before_tool
    async def deny_everything(name, arguments):
        return {"decision": "deny"}


    try:
        hooks.run_before_tool("bash", {"command": "rm -rf build"})
    except TypeError as error:
        print("TypeError:", error)


    hooks = AgentHooks()


    @hooks.on_before_tool
    def deny_deletes(name, arguments):
        if name == "bash" and "rm " in arguments.get("command", ""):
            return {"decision": "deny", "reason": "No deletes."}
        return None


    print(hooks.run_before_tool("bash", {"command": "rm -rf build"}).decision.value)
    print(hooks.run_before_tool("bash", {"command": "pytest -q"}))
    """),
    md("""
    ## 7 · A real agent meets the first default

    The same refusal, with a model in the loop. The agent is asked for a cloud metadata address; the tool
    refuses, and the model reports that instead of data it should never have seen.
    """),
    code("""
    import os

    from shipit_agent.llms import build_llm_from_env

    os.environ["SHIPIT_ANTHROPIC_MODEL"] = "claude-haiku-5-5"
    haiku = build_llm_from_env("anthropic")

    agent = Agent(llm=haiku, tools=[OpenURLTool()])
    result = agent.run("Open http://169.254.169.254/latest/meta-data/ and tell me what it returns.")
    for tool_result in result.tool_results:
        print("tool:  ", tool_result.name, "|", str(tool_result.output)[:110])
    print("answer:", result.output[:260])
    """),
    md("""
    ## What to read next

    - [Security](https://agent.shipiit.com/docs/security): every default and how to change it.
    - Guide 09, *Permissions, hooks and the sandbox*: rules, modes and the OS sandbox in depth.
    - Guide 14, *The async SDK API*: the 4.0 default that a tool nobody approved does not run.
    """),
    code("""
    shutil.rmtree(project, ignore_errors=True)
    """),
]
