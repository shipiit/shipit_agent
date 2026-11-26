"""Guide 14: the async SDK API, new in 4.0."""

from cells import code, md

TITLE = "The async SDK API"
SINCE = "4.0"

CELLS = [
    md("""
    # Guide 14 · The async SDK API

    New in 4.0. `shipit_agent.sdk` is a second way to drive the same loop: async throughout, with typed
    messages, one options object, approvals and hook events. It runs on shipit's own loop, so it works with
    every model provider.

    **What you'll learn**

    1. `query()`: one run, as typed messages
    2. Your own tools, served in process
    3. The 4.0 default: a tool nobody approved does not run
    4. Approving calls in code with `can_use_tool`
    5. Hooks, including `SessionStart` and `SessionEnd`
    6. `AgentClient`: a conversation you keep open
    7. The same code on another provider

    Every output below is real, from Haiku 5.5 (Anthropic) and Gemma 4 31B (Bedrock).
    """),
    md("""
    ## 1 · Models and a demo project

    A tiny project with one bug, so the agent has something to do.
    """),
    code("""
    import os
    import shutil
    from pathlib import Path

    from shipit_agent.llms import build_llm_from_env
    from shipit_agent.llms.factory import build_llm_from_settings

    os.environ["SHIPIT_ANTHROPIC_MODEL"] = "claude-haiku-5-5"
    haiku = build_llm_from_env("anthropic")
    gemma = build_llm_from_settings({"model": "google.gemma-4-31b"}, provider="bedrock")

    project = Path("sdk_demo").resolve()
    shutil.rmtree(project, ignore_errors=True)
    project.mkdir()
    (project / "calc.py").write_text("def add(a, b):\\n    return a - b\\n")
    (project / "test_calc.py").write_text("from calc import add\\n\\n\\ndef test_add():\\n    assert add(2, 3) == 5\\n")
    print(sorted(p.name for p in project.iterdir()))
    """),
    md("""
    ## 2 · `query()`: one run, as typed messages

    `query()` is an async generator. It yields an `AssistantMessage` for each model turn, whose `content` is a
    list of blocks (`TextBlock`, `ToolUseBlock`), and ends with one `ResultMessage` carrying the answer, the
    number of turns and the cost. `allowed_tools` names what may run without asking.
    """),
    code("""
    from shipit_agent.sdk import AgentOptions, AssistantMessage, ResultMessage, TextBlock, ToolUseBlock, query

    options = AgentOptions(
        llm=haiku,
        cwd=str(project),
        allowed_tools=["Read", "Grep", "Edit", "Bash(python -m pytest *)", "Bash(pytest *)"],
        max_turns=12,
        max_budget_usd=0.50,
    )

    async for message in query(prompt="Run the tests with pytest -q, fix the bug in calc.py, and run them again.", options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, ToolUseBlock):
                    print(f"tool   {block.name}  {str(block.input)[:70]}")
                elif isinstance(block, TextBlock) and block.text.strip():
                    print(f"text   {block.text.strip()[:110]}")
        elif isinstance(message, ResultMessage):
            print(f"result {message.subtype} · {message.num_turns} turns · ${message.total_cost_usd or 0:.4f}")

    print((project / "calc.py").read_text())
    """),
    md("""
    ## 3 · Your own tools, served in process

    `@tool` turns an async function into a tool; `create_sdk_mcp_server` groups tools into a server that runs
    inside your program. The model sees a server's tools as `<server>__<tool>`; rules and hook matchers can
    also name them the long way, `mcp__<server>__<tool>`.
    """),
    code("""
    from shipit_agent.sdk import create_sdk_mcp_server, tool

    ORDERS = {"A-1043": "shipped on 3 November, tracking ZX-9917", "A-1044": "being packed"}
    refunds: list[tuple[str, float]] = []


    @tool("order_status", "Look up an order's shipping status by its id.", {"order_id": str})
    async def order_status(args):
        status = ORDERS.get(args["order_id"])
        if status is None:
            return {"content": [{"type": "text", "text": f"No order {args['order_id']}."}], "is_error": True}
        return {"content": [{"type": "text", "text": f"{args['order_id']}: {status}"}]}


    @tool("refund", "Refund an amount in dollars on an order.", {"order_id": str, "amount": float})
    async def refund(args):
        refunds.append((args["order_id"], args["amount"]))
        return {"content": [{"type": "text", "text": f"Refunded ${args['amount']:.2f} on {args['order_id']}."}]}


    shop = create_sdk_mcp_server("shop", tools=[order_status, refund])


    async def ask(prompt, **extra):
        \"\"\"Run one prompt against the shop tools and report what was called and what was answered.\"\"\"
        options = AgentOptions(llm=extra.pop("llm", haiku), tools=[], mcp_servers={"shop": shop}, max_turns=6, **extra)
        called, answer = [], ""
        async for message in query(prompt=prompt, options=options):  # read to the end, so the session closes
            if isinstance(message, AssistantMessage):
                called += [b.name for b in message.content if isinstance(b, ToolUseBlock)]
            elif isinstance(message, ResultMessage):
                answer = (message.result or "").strip()
        return called, answer


    called, answer = await ask("Where is order A-1043?", allowed_tools=["mcp__shop__order_status"])
    print("called:", called)
    print("answer:", answer[:200])
    """),
    md("""
    ## 4 · The 4.0 default: a tool nobody approved does not run

    This is the one breaking change in 4.0. Before, a tool that no rule mentioned ran. Now it needs a rule in
    `allowed_tools`, a permission mode that covers it, or a yes from `can_use_tool`. Here `refund` is none of
    those, so the model may ask for it but it never runs.
    """),
    code("""
    refunds.clear()
    called, answer = await ask(
        "Order A-1043 arrived broken. Refund $40 on it.",
        allowed_tools=["mcp__shop__order_status"],
    )
    print("called: ", called)
    print("refunds:", refunds)
    print("answer: ", answer[:240])
    """),
    md("""
    ## 5 · Approving calls in code

    `can_use_tool` is asked about every call that no rule settles. It can allow, deny with a message the model
    reads, or rewrite the input. Here refunds up to $50 go through and larger ones are refused.
    """),
    code("""
    from shipit_agent.sdk import PermissionResultAllow, PermissionResultDeny

    asked = []


    async def can_use_tool(tool_name, tool_input, context):
        asked.append((tool_name, tool_input))
        if tool_name.endswith("refund") and tool_input.get("amount", 0) > 50:
            return PermissionResultDeny(message="Refunds over $50 need a manager.")
        return PermissionResultAllow()


    for prompt in ("Refund $40 on order A-1043.", "Refund $400 on order A-1044."):
        refunds.clear()
        called, answer = await ask(prompt, allowed_tools=["mcp__shop__order_status"], can_use_tool=can_use_tool)
        print(prompt)
        print("  refunds:", refunds)
        print("  answer: ", answer[:160].replace("\\n", " "))
    print("asked about:", sorted({name for name, _ in asked}))
    """),
    md("""
    ## 6 · Hooks, including session start and end

    Hooks are async functions keyed by event. A `PreToolUse` hook can deny a call before anything else sees
    it. `SessionStart` and `SessionEnd` are new in 4.0: they fire once per `query()`, and what `SessionStart`
    returns as `additionalContext` is added to the first prompt.
    """),
    code("""
    from shipit_agent.sdk import HookMatcher

    seen = []


    async def on_start(input_data, tool_use_id, context):
        seen.append(f"SessionStart source={input_data.get('source')}")
        return {"hookSpecificOutput": {"hookEventName": "SessionStart",
                                       "additionalContext": "House rule: always end your answer with the word DONE."}}


    async def no_big_refunds(input_data, tool_use_id, context):
        seen.append(f"PreToolUse {input_data['tool_name']}")
        if input_data["tool_input"].get("amount", 0) > 50:
            return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                           "permissionDecisionReason": "Refunds over $50 are not allowed here."}}
        return {}


    async def on_end(input_data, tool_use_id, context):
        seen.append(f"SessionEnd reason={input_data.get('reason')}")
        return {}


    refunds.clear()
    called, answer = await ask(
        "Check order A-1044, then refund $75 on it.",
        allowed_tools=["mcp__shop__order_status", "mcp__shop__refund"],
        hooks={
            "SessionStart": [HookMatcher("startup", [on_start])],
            "PreToolUse": [HookMatcher("mcp__shop__refund", [no_big_refunds])],  # a matcher is a tool's full name
            "SessionEnd": [HookMatcher(None, [on_end])],
        },
    )
    print("\\n".join(seen))
    print("refunds:", refunds)
    print("answer: ", answer[:240].replace("\\n", " "))
    """),
    md("""
    ## 7 · `AgentClient`: a conversation you keep open

    `query()` is one run. `AgentClient` keeps a conversation: each `query()` is a turn, and the model has the
    earlier turns. The second question below only makes sense with the first.
    """),
    code("""
    from shipit_agent.sdk import AgentClient

    options = AgentOptions(llm=haiku, tools=[], mcp_servers={"shop": shop}, allowed_tools=["mcp__shop__order_status"], max_turns=6)

    async with AgentClient(options) as client:
        for prompt in ("Where is order A-1043?", "And what is its tracking number? Answer with the number only."):
            await client.query(prompt)
            async for message in client.receive_response():
                if isinstance(message, ResultMessage):
                    print(f"you:   {prompt}")
                    print(f"agent: {(message.result or '').strip()[:160]}")
    """),
    md("""
    ## 8 · The same code on another provider

    Nothing above is specific to one provider. The same helper, the same tools and the same rule, on an open
    model on AWS Bedrock.
    """),
    code("""
    refunds.clear()
    called, answer = await ask("Where is order A-1044?", llm=gemma, allowed_tools=["mcp__shop__order_status"])
    print("called:", called)
    print("answer:", answer[:200])

    called, answer = await ask("Refund $40 on order A-1043.", llm=gemma, allowed_tools=["mcp__shop__order_status"])
    print("called:", called, "| refunds:", refunds)
    """),
    md("""
    ## What to read next

    - [Agent SDK API](https://agent.shipiit.com/docs/guides/agent-sdk): every option, message and hook event.
    - Guide 15, *Secure by default*: the other 4.0 defaults, each one demonstrated.
    - Guide 16, *Tasks, background work and async chat*.
    """),
    code("""
    shutil.rmtree(project, ignore_errors=True)
    """),
]
