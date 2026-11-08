"""Guide 10: sub-agents, delegation and the verifier."""

from cells import code, md

TITLE = "Sub-agents and the verifier"

CELLS = [
    md("""
    # Guide 10 · Sub-agents and the verifier

    One agent can hand work to others: a specialist with its own prompt, tools and model, or several helpers in
    parallel. And a second, cheap model can watch the first: veto a tool call that's off-task, and refuse to let
    a coding turn finish without passing tests.

    **What you'll learn**

    1. An agent as a tool, on a different model (a two-model team)
    2. Named sub-agents with `agents=`
    3. Delegation: fanning work out to parallel helpers
    4. The verifier: vetoing off-task tool calls
    5. `verify_before_stop`: no "done" without fresh passing tests

    Every output below is real, from Haiku 5.5 (Anthropic) and Gemma 4 31B (Bedrock).
    """),
    md("""
    ## 1 · Models
    """),
    code("""
    import json
    import os
    import shutil
    from pathlib import Path

    from shipit_agent import Agent
    from shipit_agent.llms import build_llm_from_env
    from shipit_agent.llms.factory import build_llm_from_settings
    from shipit_agent.tools import FunctionTool

    os.environ["SHIPIT_ANTHROPIC_MODEL"] = "claude-haiku-5-5"
    haiku = build_llm_from_env("anthropic")
    gemma = build_llm_from_settings({"model": "google.gemma-4-31b"}, provider="bedrock")
    """),
    md("""
    ## 2 · A specialist on another model

    `as_tool()` wraps an agent so another can call it. Here a Gemma 4 "pricing analyst" with its own data tool
    serves a Haiku lead: each model does the part it's given.
    """),
    code("""
    PRICES = {"starter": 12, "team": 29, "enterprise": 79}

    def plan_price(plan: str) -> str:
        \"\"\"Per-seat monthly price for a plan.\"\"\"
        return str(PRICES.get(plan.lower(), "unknown plan"))

    analyst = Agent(llm=gemma, name="pricing_analyst",
                    prompt="You answer pricing questions with the plan_price tool. Show your arithmetic.",
                    tools=[FunctionTool.from_callable(plan_price, read_only=True)])

    lead = Agent(llm=haiku, prompt="You are a sales lead. Ask the analyst for numbers; then answer in two lines.",
                 tools=[analyst.as_tool(description="Pricing analyst: computes plan costs.")])
    result = lead.run("A 40-seat company: what's the yearly difference between Team and Enterprise?")
    print(result.output)
    print("\\nlead called:", [r.name for r in result.tool_results])
    """),
    md("""
    ## 3 · What the lead saw

    The specialist's whole answer comes back as one tool result.
    """),
    code("""
    print(result.tool_results[0].output[:600])
    """),
    md("""
    ## 4 · Named sub-agents with `agents=`

    Define helpers by name: a description (how the lead decides), a prompt, and the tools they may use. Defining
    any gives the lead a `sub_agent` tool that lists them.
    """),
    code("""
    lead = Agent(llm=haiku, prompt="You coordinate. Use your sub-agents, then answer briefly.", agents={
        "reviewer": {"description": "Reviews a code snippet for bugs.", "prompt": "List concrete bugs only, one line each."},
        "tester": {"description": "Writes pytest tests for a function.", "prompt": "Write minimal pytest tests, code only."},
    })

    SNIPPET = "def average(xs):\\n    return sum(xs) / len(xs)\\n"
    result = lead.run(f"Have the reviewer check this, and the tester write tests for it:\\n{SNIPPET}")
    print("lead called:", [r.name for r in result.tool_results])
    for r in result.tool_results:
        print(f"--- {r.name}: {r.output[:300]}\\n")
    print(result.output[:400])
    """),
    md("""
    ## 5 · Sub-agent activity in the stream

    Sub-agent starts and finishes are events, so a UI can show who is working on what.
    """),
    code("""
    from collections import Counter

    seen = Counter()
    for e in lead.stream(f"Ask the reviewer about this:\\n{SNIPPET}"):
        if e.type == "tool_called":
            print("lead calls:", e.payload["tool"], {k: str(v)[:50] for k, v in e.payload["arguments"].items()})
        elif e.type == "sub_agent_event":
            seen[e.payload.get("event_type") or e.payload.get("type") or "event"] += 1
    print("events from inside the sub-agent:", dict(seen))
    """),
    md("""
    ## 6 · Delegation: fan work out

    A task with a list of independent items is a natural fan-out. `DelegationPolicy` makes sure the lead has a
    `sub_agent` tool and tells it when a task looks like one; children are read-only by default.
    """),
    code("""
    from shipit_agent import DelegationPolicy

    docs = Path("delegation_docs")
    docs.mkdir(exist_ok=True)
    for name, text in {
        "billing.md": "Invoices go out on the 1st. Failed cards retry 3 times over 7 days.",
        "security.md": "Data is encrypted at rest with AES-256. Production access needs a hardware key.",
        "support.md": "Team plans get a 4-hour response. Enterprise gets 24/7 phone support.",
        "exports.md": "Exports are capped at 100,000 rows. Larger ones are split into several files.",
    }.items():
        (docs / name).write_text(text)

    agent = Agent.with_builtins(llm=haiku, project_root=str(docs), delegation=DelegationPolicy(min_items=3))
    result = agent.run("For each of the 4 files in this folder, give a one-line summary.")
    print("calls:", [r.name for r in result.tool_results])
    print(result.output)
    """),
    md("""
    ## 7 · The verifier: a second model checks each tool call

    A `VerifierNetwork` on a cheap model reads each proposed call against the goal. An off-task or destructive
    call is vetoed before it runs, with a reason the main model sees. Here Gemma 4 does the work and Haiku 5.5
    checks it, and the user's request ("delete any stale record") conflicts with the goal the verifier holds.
    """),
    code("""
    from shipit_agent.verifier import VerifierConfig, VerifierNetwork

    RECORDS = {"cust-1": "active", "cust-2": "active", "test-9": "stale"}
    deleted = []

    def list_records() -> str:
        \"\"\"List customer records and their status.\"\"\"
        return json.dumps(RECORDS)

    def delete_record(record_id: str) -> str:
        \"\"\"Permanently delete a customer record.\"\"\"
        deleted.append(record_id)
        return f"deleted {record_id}"

    verifier = VerifierNetwork(llm=haiku, goal="Produce a read-only status report. Nothing may be deleted.",
                               config=VerifierConfig(veto_enabled=True, veto_min_confidence=0.6))
    agent = Agent(llm=gemma, prompt="You maintain customer records.", verifier=verifier,
                  tools=[FunctionTool.from_callable(list_records, read_only=True), FunctionTool.from_callable(delete_record)],
                  permission_mode="bypassPermissions")
    result = agent.run("Report record statuses, and delete any stale record while you're at it.")
    for r in result.tool_results:
        print(f"{r.name:13} {r.output[:110]}")
    print("\\ndeleted:", deleted, "| vetoes:", verifier.stats.pretool_veto)
    print(result.output[:300])
    """),
    md("""
    ## 8 · `verify_before_stop`: no "done" without passing tests

    For coding agents: a turn that edited code can't finish until the project's tests have run, and passed,
    after the last edit. The agent is sent back to run them. The test command is detected from the project
    (`pytest.ini`, `pyproject.toml`, `package.json`, a `Makefile`), so the demo declares pytest.
    """),
    code("""
    project = Path("verify_demo").resolve()
    shutil.rmtree(project, ignore_errors=True)
    project.mkdir()
    (project / "mathx.py").write_text("def clamp(x, lo, hi):\\n    return x\\n")
    (project / "pytest.ini").write_text("[pytest]\\naddopts = -q -p no:cacheprovider\\n")
    (project / "test_mathx.py").write_text(
        "from mathx import clamp\\n\\ndef test_clamp():\\n    assert clamp(5, 0, 3) == 3\\n    assert clamp(-1, 0, 3) == 0\\n")

    agent = Agent.with_builtins(llm=haiku, project_root=str(project), verify_before_stop=True,
                                permission_mode="acceptEdits")
    result = agent.run("Fix clamp() in mathx.py so it clamps x between lo and hi.")
    print("steps:", [r.name for r in result.tool_results])
    print("commands:", [e.payload["arguments"].get("command") for e in result.events
                        if e.type == "tool_called" and e.payload["tool"] == "bash"])
    print((project / "mathx.py").read_text())
    print(result.output[:300])
    """),
    md("""
    ## 9 · The same team, roles swapped

    Gemma 4 leads and Haiku 5.5 is the analyst: the pieces don't care which model sits where.
    """),
    code("""
    analyst = Agent(llm=haiku, name="pricing_analyst", prompt="Answer pricing questions with plan_price. Show arithmetic.",
                    tools=[FunctionTool.from_callable(plan_price, read_only=True)])
    lead = Agent(llm=gemma, prompt="You are a sales lead. Ask the analyst for numbers; then answer in two lines.",
                 tools=[analyst.as_tool(description="Pricing analyst: computes plan costs.")])
    print(lead.run("A 12-seat company: monthly cost on Starter versus Team?").output)
    """),
    md("""
    ## 10 · Clean up
    """),
    code("""
    shutil.rmtree(docs, ignore_errors=True)
    shutil.rmtree(project, ignore_errors=True)
    """),
    md("""
    ## 11 · Summary

    - `agent.as_tool()` makes a specialist, with its own model and tools, callable by another agent.
    - `agents={...}` defines named sub-agents behind a `sub_agent` tool; their activity streams as events.
    - `DelegationPolicy` fans list-shaped work out to read-only helpers.
    - `VerifierNetwork` vetoes off-goal tool calls on a cheap model; `verifier.stats` counts what it did.
    - `verify_before_stop=True` keeps a coding turn going until tests pass after the last edit.

    **Next:** Guide 11 — deep agents and autopilot.
    """),
]
