"""Guide 03: tools, from a function to 66 built-ins."""

from cells import code, md

TITLE = "Tools: your functions, classes and the built-ins"

CELLS = [
    md("""
    # Guide 03 · Tools: your functions, classes and the built-ins

    A tool is a name, a description, a JSON Schema for its arguments, and code that runs. The model decides
    when to call one; shipit runs it, handles its errors, and feeds the result back.

    **What you'll learn**

    1. Turn a Python function into a tool, and see the schema the model gets
    2. Write a tool as a class, with guidance and structured results
    3. Errors the model can fix, and errors it can't
    4. Big results: a short view for the model, the full data for you
    5. Parallel calls, built-in tools, and limiting what an agent may use
    6. Many tools, small requests: deferred tools and `tool_search`

    Every output below is real, from Haiku 5.5 (Anthropic) and Gemma 4 31B (Bedrock).
    """),
    md("""
    ## 1 · Models
    """),
    code("""
    import os

    from shipit_agent import Agent
    from shipit_agent.llms import build_llm_from_env
    from shipit_agent.llms.factory import build_llm_from_settings

    os.environ["SHIPIT_ANTHROPIC_MODEL"] = "claude-haiku-5-5"
    haiku = build_llm_from_env("anthropic")
    gemma = build_llm_from_settings({"model": "google.gemma-4-31b"}, provider="bedrock")
    """),
    md("""
    ## 2 · A function becomes a tool

    `FunctionTool.from_callable` reads the function's name, docstring and type hints. `read_only=True` tells the
    permission gate it changes nothing, so it runs without asking.
    """),
    code("""
    import json

    from shipit_agent.tools import FunctionTool

    ORDERS = {
        "A-1043": {"customer": "ada@example.com", "total": 120.0, "status": "delivered"},
        "A-1044": {"customer": "lin@example.com", "total": 64.5, "status": "in transit"},
    }

    def find_order(order_id: str) -> str:
        \"\"\"Look up an order by id (like A-1043) and return its customer, total and status.\"\"\"
        order = ORDERS.get(order_id)
        return json.dumps(order) if order else f"no order {order_id}"

    find = FunctionTool.from_callable(find_order, read_only=True)
    print(json.dumps(find.schema(), indent=2))
    """),
    md("""
    ## 3 · The model calls it
    """),
    code("""
    agent = Agent(llm=haiku, prompt="You are a support agent. Be brief.", tools=[find])
    result = agent.run("Where is order A-1044, and how much was it?")
    print(result.output)
    for r in result.tool_results:
        print(" ", r.name, "->", r.output)
    """),
    md("""
    ## 4 · A tool as a class

    A class gives you a hand-written schema, `prompt_instructions` (guidance the model reads), and a
    `ToolOutput` with `metadata` for your code that the model never sees.
    """),
    code("""
    from shipit_agent.tools.base import ToolContext, ToolOutput

    class RefundTool:
        name = "refund_order"
        description = "Refund an order, in full or in part."
        prompt_instructions = "Refund only orders that exist; a partial refund needs an amount."
        read_only = False

        def schema(self) -> dict:
            return {"type": "function", "function": {
                "name": self.name, "description": self.description,
                "parameters": {"type": "object", "properties": {
                    "order_id": {"type": "string", "description": "The order to refund, e.g. A-1043."},
                    "amount": {"type": "number", "description": "Dollars to refund; omit for a full refund."},
                }, "required": ["order_id"]},
            }}

        def run(self, context: ToolContext, **kwargs) -> ToolOutput:
            order_id, amount = kwargs["order_id"], kwargs.get("amount")
            if order_id not in ORDERS:
                return ToolOutput.error(f"{order_id} is not an order. Order ids look like A-1043; look it up first.")
            refunded = ORDERS[order_id]["total"] if amount is None else amount
            return ToolOutput(text=f"Refunded ${refunded:.2f} on {order_id}.",
                              metadata={"order_id": order_id, "refunded": refunded})

    refund = RefundTool()
    print(refund.name, "| read_only:", refund.read_only)
    """),
    md("""
    ## 5 · Errors the model can fix

    `ToolOutput.error(...)` goes back to the model as a failed call with your message, and the model adjusts.
    Here it's given an order number in the wrong format.
    """),
    code("""
    agent = Agent(llm=haiku, prompt="You are a support agent. Be brief.", tools=[find, refund],
                  permission_mode="bypassPermissions")
    result = agent.run("Refund order 1043 in full.")
    for r in result.tool_results:
        print(f"{r.name:13} {r.output}")
    print("\\n" + result.output)
    """),
    md("""
    The run above used `permission_mode="bypassPermissions"` so the refund ran without asking; Guide 09 covers
    permissions. Structured data from the tool is in `metadata`, which the model never sees:
    """),
    code("""
    print([r.metadata for r in result.tool_results if r.name == "refund_order"])
    """),
    md("""
    ## 6 · Errors it can't fix

    A raised exception never ends the run. The model sees `Error running tool '<name>': <message>` and carries on.
    """),
    code("""
    def inventory(sku: str) -> str:
        \"\"\"Return stock for a SKU.\"\"\"
        raise ConnectionError("inventory service is down")

    agent = Agent(llm=haiku, prompt="Be brief.", tools=[FunctionTool.from_callable(inventory, read_only=True)])
    result = agent.run("How many SKU-7 are in stock?")
    print([r.output for r in result.tool_results])
    print(result.output)
    """),
    md("""
    ## 7 · A short view for the model, the full data for you

    `ToolOutput.from_records(rows, fields=..., limit=...)` shows the model a page of the fields it needs, with the
    total count, and keeps every record in `text` for your code.
    """),
    code("""
    rows = [{"id": f"T-{i}", "status": "open" if i % 3 else "closed", "subject": f"Ticket {i}", "body": "…" * 50}
            for i in range(1, 121)]
    out = ToolOutput.from_records(rows, fields=["id", "status"], limit=5)
    print("model sees:\\n" + out.model_text)
    print("\\nfull text:", len(out.text), "characters")
    """),
    md("""
    ## 8 · Long outputs are capped for the model

    `max_tool_output_chars` (16,000 by default) bounds what the model sees of one result, because every later turn
    re-sends it. `result.tool_results` always keeps the whole output.
    """),
    code("""
    def server_log() -> str:
        \"\"\"Return today's server log.\"\"\"
        return "\\n".join(f"{12 + i // 3600}:{i // 60 % 60:02d}:{i % 60:02d} GET /api/orders 200" for i in range(4000)) + "\\n13:07:00 ERROR db timeout"

    agent = Agent(llm=haiku, prompt="Be brief.", tools=[FunctionTool.from_callable(server_log, read_only=True)],
                  max_tool_output_chars=2000)
    result = agent.run("Is there an error in today's server log? Quote it if so.")
    print("full output kept:", len(result.tool_results[0].output), "characters")
    print(result.output)
    """),
    md("""
    The cap keeps the start and the end of a long result and tells the model how much was left out, so it saw
    the last line here, and knows it may have missed errors in the middle. Better still, make tools return the
    part that matters (here: only the error lines).

    ## 9 · Parallel calls

    When the model asks for several read-only tools in one response, they run at the same time
    (`parallel_tool_execution=True`, the default). Two lookups that each take one second:
    """),
    code("""
    import time

    def weather(city: str) -> str:
        \"\"\"Current weather for a city.\"\"\"
        time.sleep(1)
        return {"Lisbon": "21°C, sunny", "Oslo": "4°C, rain"}.get(city, "unknown")

    tool = FunctionTool.from_callable(weather, read_only=True)
    for parallel in (True, False):
        agent = Agent(llm=haiku, prompt="Call tools for each city at once.", tools=[tool], parallel_tool_execution=parallel)
        started = time.perf_counter()
        result = agent.run("Weather in Lisbon and in Oslo?")
        print(f"parallel={parallel!s:5} {time.perf_counter() - started:4.1f}s  {len(result.tool_results)} calls")
    """),
    md("""
    ## 10 · The built-in tools

    `Agent.with_builtins()` attaches shipit's own tools: files, shell, search, the web, planning, documents and
    more. Point `project_root` at a folder to work in.
    """),
    code("""
    from pathlib import Path

    project = Path("demo_project")
    (project / "src").mkdir(parents=True, exist_ok=True)
    (project / "src" / "pricing.py").write_text(
        "def price(seats: int) -> float:\\n    return seats * 12.0  # Starter, per seat per month\\n")
    (project / "README.md").write_text("# Demo\\nA tiny pricing module.\\n")

    builder = Agent.with_builtins(llm=haiku, project_root=str(project))
    print(len(builder.tools), "tools:", ", ".join(sorted(t.name for t in builder.tools))[:400], "…")
    """),
    code("""
    result = builder.run("What does price() charge per seat? Answer from the code, citing the file and line.")
    print([r.name for r in result.tool_results])
    print(result.output)
    """),
    md("""
    ## 11 · Only the tools it needs

    Fewer tools mean smaller requests and fewer wrong choices. Pass exactly the classes you want, or keep the
    built-ins and remove some with `disallowed_tools`. Removed tools are hidden from the model when the run
    starts, so the count to check is the one each step reports.
    """),
    code("""
    from shipit_agent.tools import FileReadTool, GrepSearchTool

    reader = Agent(llm=haiku, project_root=str(project),
                   tools=[FileReadTool(root_dir=str(project)), GrepSearchTool(root_dir=str(project))])
    print("reader:", [t.name for t in reader.tools])

    def tools_seen(agent: Agent) -> int:
        for e in agent.stream("Reply with one word: ready"):
            if e.type == "step_started":
                return e.payload.get("tool_count", 0)
        return 0

    everything = Agent.with_builtins(llm=haiku, project_root=str(project), deferred_tools=False)
    no_shell = everything.clone(disallowed_tools=["bash", "bash_job", "playwright_browse"])
    print("tools the model sees, all built-ins:", tools_seen(everything))
    print("tools the model sees, without shell and browser:", tools_seen(no_shell))
    """),
    md("""
    ## 12 · Many tools, small requests

    Every tool's schema is sent with every request. Above ten tools, shipit keeps a small core loaded and lists
    the rest by name (`deferred_tools="auto"`); the model loads one with `tool_search` when it needs it.
    """),
    code("""
    for mode in (False, True):
        agent = Agent.with_builtins(llm=haiku, project_root=str(project), deferred_tools=mode)
        result = agent.run("Reply with one word: ready")
        print(f"deferred_tools={mode!s:5} input tokens: {result.metadata['usage']['prompt_tokens'] + result.metadata['usage'].get('cache_read_input_tokens', 0) + result.metadata['usage'].get('cache_creation_input_tokens', 0)}")
    """),
    md("""
    ## 13 · Watch the tools in a stream

    Tool events show each call with its arguments, its output and how long it took.
    """),
    code("""
    for e in Agent(llm=haiku, prompt="Be brief.", tools=[find]).stream("Status of A-1043 and A-1044?"):
        if e.type == "tool_called":
            print(f"call  {e.payload['tool']}({e.payload['arguments']})")
        elif e.type == "tool_completed":
            print(f"done  {e.payload['tool']} -> {e.payload['output'][:50]}…  [{e.payload.get('duration_ms', 0):.1f} ms]")
        elif e.type == "run_completed":
            print(e.payload["output"])
    """),
    md("""
    ## 14 · The same tools on Gemma 4

    Section 5 on Gemma 4 31B (Bedrock): the bad order id, the error, and the fix.
    """),
    code("""
    agent = Agent(llm=gemma, prompt="You are a support agent. Be brief.", tools=[find, refund],
                  permission_mode="bypassPermissions")
    result = agent.run("Refund order 1043 in full.")
    for r in result.tool_results:
        print(f"{r.name:13} {r.output}")
    print("\\n" + result.output)
    """),
    md("""
    ## 15 · Clean up
    """),
    code("""
    import shutil

    shutil.rmtree(project)
    """),
    md("""
    ## 16 · Summary

    - `FunctionTool.from_callable(fn, read_only=...)` turns a typed function into a tool.
    - A class tool adds `prompt_instructions`, a hand-written schema and `ToolOutput` with `metadata`.
    - `ToolOutput.error(...)` lets the model fix its call; a raised exception is reported, never fatal.
    - `model_text` / `from_records` / `max_tool_output_chars` keep big results small for the model.
    - Read-only calls run in parallel; `with_builtins()` adds the built-in set; `deferred_tools` keeps requests small.

    **Next:** Guide 04 — MCP servers.
    """),
]
