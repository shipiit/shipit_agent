"""Guide 09: permissions, approvals, hooks and the OS sandbox."""

from cells import code, md

TITLE = "Permissions, hooks and the sandbox"

CELLS = [
    md("""
    # Guide 09 · Permissions, hooks and the sandbox

    An agent that can edit files and run commands needs limits. shipit has three layers:

    - **Permissions** decide each tool call before it runs: allow, deny, or ask a person.
    - **Hooks** run your code around every model call and tool call, and can block one.
    - **The OS sandbox** confines the commands that do run: writes only inside the project, no network.

    **What you'll learn**

    1. Rules and modes, checked without a model
    2. An agent stopped by a deny rule, and one in plan mode
    3. Deciding calls in code, and parking them for a person to approve
    4. Hooks for logging and guardrails
    5. The sandbox: what a confined command can and can't do

    Every output below is real, from Haiku 5.5 (Anthropic) and Gemma 4 31B (Bedrock), on macOS.
    """),
    md("""
    ## 1 · Models and a demo project
    """),
    code("""
    import os
    import shutil
    import subprocess
    import sys
    from pathlib import Path

    from shipit_agent import Agent
    from shipit_agent.llms import build_llm_from_env
    from shipit_agent.llms.factory import build_llm_from_settings

    os.environ["SHIPIT_ANTHROPIC_MODEL"] = "claude-haiku-5-5"
    haiku = build_llm_from_env("anthropic")
    gemma = build_llm_from_settings({"model": "google.gemma-4-31b"}, provider="bedrock")

    project = Path("perm_demo").resolve()
    shutil.rmtree(project, ignore_errors=True)
    (project / "src").mkdir(parents=True)
    (project / "migrations").mkdir()
    (project / "src" / "calc.py").write_text("def add(a, b):\\n    return a + b\\n")
    (project / "test_calc.py").write_text("from src.calc import add\\n\\ndef test_add():\\n    assert add(2, 3) == 5\\n")
    (project / "migrations" / "0001_init.py").write_text("# create tables\\n")
    (project / ".env").write_text("PAYMENTS_KEY=demo-value-not-a-real-secret\\n")
    subprocess.run(["git", "init", "-q"], cwd=project)
    subprocess.run(["git", "config", "user.name", "Demo User"], cwd=project)
    subprocess.run(["git", "config", "user.email", "demo@example.com"], cwd=project)
    print(sorted(str(p.relative_to(project)) for p in project.rglob("*") if p.is_file() and ".git/" not in str(p)))
    """),
    md("""
    ## 2 · Rules, checked without a model

    A `PermissionEngine` holds allow, deny and ask rules. `check()` shows the decision for any call, so you can
    test a policy before an agent ever uses it. A deny always wins; compound commands are judged part by part.
    """),
    code("""
    from shipit_agent import PermissionEngine

    engine = PermissionEngine(
        allow=["Bash(pytest *)", "Bash(git diff *)", "Bash(ls *)"],
        deny=["Bash(git push *)", "Read(.env)"],
        ask=["Edit(migrations/**)"],
        root=str(project),
    )
    calls = [
        ("bash", {"command": "pytest -q"}),
        ("bash", {"command": "git diff HEAD"}),
        ("bash", {"command": "git push origin main"}),
        ("read_file", {"path": ".env"}),
        ("edit_file", {"path": "migrations/0002_users.py"}),
        ("edit_file", {"path": "src/calc.py"}),
        ("bash", {"command": "ls && rm -rf build"}),
    ]
    for tool, args in calls:
        r = engine.check(tool, args)
        print(f"{tool:9} {str(args):42} {r.decision.value:5} {r.reason[:60]}")
    """),
    md("""
    ## 3 · Modes

    The mode decides the calls no rule covers. The same three calls under each mode. `check()` sees only the
    rules and the mode: when an agent runs, the runtime also flags risky actions (deleting files, pushing,
    sending data out) and asks about them in `default` mode, as section 8 shows.
    """),
    code("""
    probe = [("read_file", {"path": "src/calc.py"}), ("edit_file", {"path": "src/calc.py"}), ("bash", {"command": "rm -rf src"})]
    for mode in ("default", "acceptEdits", "plan", "dontAsk", "bypassPermissions"):
        e = PermissionEngine(mode=mode, root=str(project))
        print(f"{mode:18}", "  ".join(f"{t}:{e.check(t, a).decision.value}" for t, a in probe))
    """),
    md("""
    ## 4 · An agent behind the rules

    The agent runs the tests (allowed), then tries to push (denied). A refused call goes back to the model as a
    tool result, so it can explain or change course.
    """),
    code("""
    agent = Agent.with_builtins(llm=haiku, project_root=str(project), permissions=engine)
    result = agent.run("Run the tests with pytest -q, then push to origin main.")
    for r in result.tool_results:
        print(f"{r.name:6} {r.output.strip()[:90]}")
    print("\\n" + result.output)
    """),
    md("""
    ## 5 · Secrets stay unread

    `Read(.env)` is denied, whichever tool tries.
    """),
    code("""
    result = agent.run("What's in the .env file?")
    print([(r.name, r.output[:70]) for r in result.tool_results])
    print(result.output[:300])
    print("value leaked:", "demo-value" in result.output)
    """),
    md("""
    ## 6 · Plan mode

    In `plan` mode the agent may only read: every write is refused, so it researches and reports what it would
    change. A review step before anything is touched.
    """),
    code("""
    planner = Agent.with_builtins(llm=haiku, project_root=str(project), permission_mode="plan")
    result = planner.run("Add a subtract() function to src/calc.py with a test.")
    print("tools used:", sorted({r.name for r in result.tool_results}))
    print(result.output[:700])
    print("calc.py unchanged:", "subtract" not in (project / "src" / "calc.py").read_text())
    """),
    md("""
    ## 7 · Deciding in code

    A `permission_callback` decides the calls that would otherwise ask. Return a `PermissionResult`, or `None` to
    ask as usual. Here: deletes are refused with a reason; edits under `src/` are allowed.
    """),
    code("""
    from shipit_agent import PermissionDecision, PermissionResult
    from shipit_agent.tools.base import ToolOutput

    def decide(tool_name: str, arguments: dict) -> PermissionResult | None:
        command = arguments.get("command", "")
        if tool_name == "bash" and command.startswith("rm "):
            return PermissionResult(PermissionDecision.DENY, reason="Deleting is done by a person.")
        if tool_name in ("edit_file", "write_file") and str(arguments.get("path", "")).startswith("src/"):
            return PermissionResult(PermissionDecision.ALLOW)
        return None

    agent = Agent.with_builtins(llm=haiku, project_root=str(project), permission_callback=decide)
    result = agent.run("Add a subtract(a, b) function to src/calc.py, then delete migrations/ with rm -rf.")
    for r in result.tool_results:
        print(f"{r.name:10} {r.output.strip()[:80]}")
    print("subtract added:", "subtract" in (project / "src" / "calc.py").read_text(),
          "| migrations still there:", (project / "migrations").exists())
    """),
    md("""
    ## 8 · Approving later

    For unattended agents, an `ApprovalQueue` parks a call that needs approval instead of refusing it; a person
    approves later and the call runs then. Only actions whose result the agent doesn't need can wait, so a tool
    opts in with `await_decision = False` (built-ins such as `slack`, `linear` and `jira` already do). A
    command like `rm -rf`, whose output the agent reasons over, is refused instead:
    """),
    code("""
    from shipit_agent import ApprovalQueue

    agent = Agent.with_builtins(llm=haiku, project_root=str(project), approvals=ApprovalQueue())
    print(agent.run("Delete the migrations folder with rm -rf migrations.").output[:220])
    """),
    code("""
    sent = []

    class SendEmail:
        name = "send_email"
        description = "Send an email."
        read_only = False
        await_decision = False          # the agent can carry on without the result

        def schema(self) -> dict:
            props = {k: {"type": "string"} for k in ("to", "subject", "body")}
            return {"type": "function", "function": {"name": self.name, "description": self.description,
                    "parameters": {"type": "object", "properties": props, "required": list(props)}}}

        def run(self, context, **kwargs):
            sent.append(kwargs["to"])
            return ToolOutput(text=f"sent to {kwargs['to']}")

    queue = ApprovalQueue()
    agent = Agent(llm=haiku, tools=[SendEmail()], permissions=PermissionEngine(ask=["send_email"]), approvals=queue)
    print(agent.run("Email ops@example.com that the deploy finished.").output[:200])
    print("pending:", [(a.tool, a.arguments["to"], a.arguments["subject"]) for a in queue.pending()])
    print("sent before approval:", sent)
    queue.approve_all(by="lead")
    print("sent after approval: ", sent)
    """),
    md("""
    ## 9 · Hooks: watch every call

    `AgentHooks` runs your functions before and after each model call and tool call.
    """),
    code("""
    from shipit_agent import AgentHooks

    hooks = AgentHooks()

    @hooks.on_before_llm
    def before_llm(messages, tools):
        print(f"  model call: {len(messages)} messages, {len(tools)} tools")

    @hooks.on_before_tool
    def before_tool(name, arguments):
        print(f"  tool start: {name} {arguments}")

    @hooks.on_after_tool
    def after_tool(name, result):
        print(f"  tool done:  {name} ({len(result.output)} chars)")

    agent = Agent.with_builtins(llm=haiku, project_root=str(project), hooks=hooks, deferred_tools=True)
    print(agent.run("How many lines is src/calc.py?").output)
    """),
    md("""
    ## 10 · Hooks as guardrails

    A `before_tool` hook that raises stops the whole run with that error: a hard stop. To refuse one call and
    let the model carry on, use a deny rule or a `permission_callback` (section 7) instead.
    """),
    code("""
    guard = AgentHooks()

    @guard.on_before_tool
    def no_web(name, arguments):
        if name in {"web_search", "open_url"}:
            raise PermissionError(f"{name} is blocked: this agent must stay offline")

    agent = Agent.with_builtins(llm=haiku, project_root=str(project), hooks=guard)
    try:
        agent.run("Search the web for the latest pytest version.")
    except PermissionError as error:
        print("run stopped:", error)

    soft = Agent.with_builtins(llm=haiku, project_root=str(project), disallowed_tools=["web_search", "open_url"])
    print("\\nwith deny rules instead:", soft.run("Search the web for the latest pytest version.").output[:250])
    """),
    md("""
    ## 11 · The OS sandbox

    With the sandbox on, `bash` commands run inside the operating system's sandbox (Seatbelt on macOS,
    bubblewrap on Linux): they can read the machine but write only in the project, with no network unless you
    allow it. Here the tool is called directly, so each command's result is plain to see.
    """),
    code("""
    from shipit_agent.sandbox import SandboxPolicy
    from shipit_agent.tools import BashTool
    from shipit_agent.tools.base import ToolContext

    policy = SandboxPolicy.from_settings({"enabled": True, "filesystem": {"denyWrite": [".env"]}})
    bash = BashTool(root_dir=str(project), sandbox_policy=policy)
    outside = Path.home() / "shipit_sandbox_probe.txt"

    for command in [
        f"{sys.executable} -m pytest -q -p no:cacheprovider 2>&1 | tail -1",
        "echo built > build.txt && cat build.txt",
        "echo hacked >> .env",
        f"echo escaped > {outside}",
        "curl -sS -m 5 https://example.com -o /dev/null && echo online",
    ]:
        out = bash.run(ToolContext(prompt="demo"), command=command)
        shown = command.replace(sys.executable, "python").replace(str(Path.home()), "~")
        print(f"$ {shown}\\n  {out.text.strip().splitlines()[-1][:100] if out.text.strip() else '(no output)'}")
    print("\\nfile outside the project exists:", outside.exists(), "| .env untouched:", "hacked" not in (project / ".env").read_text())
    """),
    md("""
    ## 12 · A sandboxed agent

    Give the agent the sandboxed tool. Commands it runs can't reach past the project, so `bypassPermissions`
    is a reasonable choice inside it.
    """),
    code("""
    agent = Agent(llm=haiku, project_root=str(project), tools=[bash], permission_mode="bypassPermissions",
                  prompt="You work in this project with bash. Be brief.")
    result = agent.run("Run the tests, then try to save a note to ~/notes.txt, and tell me what happened.")
    for r in result.tool_results:
        print(f"$ {r.output.strip().splitlines()[-1][:90] if r.output.strip() else ''}")
    print("\\n" + result.output[:500])
    """),
    md("""
    ## 13 · The same rules on Gemma 4
    """),
    code("""
    agent = Agent.with_builtins(llm=gemma, project_root=str(project), permissions=engine)
    result = agent.run("Run the tests with pytest -q, then push to origin main.")
    for r in result.tool_results:
        print(f"{r.name:6} {r.output.strip()[:90]}")
    print("\\n" + result.output[:400])
    """),
    md("""
    ## 14 · Clean up
    """),
    code("""
    shutil.rmtree(project, ignore_errors=True)
    """),
    md("""
    ## 15 · Summary

    - `PermissionEngine(allow, deny, ask)` rules plus a mode decide every call; `check()` tests a policy offline.
    - Denied calls go back to the model; `plan` mode only reads; `dontAsk` refuses instead of asking.
    - `permission_callback` decides in code; `ApprovalQueue` parks calls that can wait (`await_decision = False`).
    - `AgentHooks` observe every call; a hook that raises stops the run.
    - `SandboxPolicy` confines commands to the project, with no network, at the OS level.

    **Next:** Guide 10 — sub-agents and the verifier.
    """),
]
