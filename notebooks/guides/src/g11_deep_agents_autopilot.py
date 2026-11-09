"""Guide 11: deep agents, crews and autopilot."""

from cells import code, md

TITLE = "Deep agents and autopilot"

CELLS = [
    md("""
    # Guide 11 · Deep agents and autopilot

    For work that takes many steps, shipit has agents with structure built in:

    - **GoalAgent** works towards explicit success criteria and reports which it met.
    - **ReflectiveAgent** drafts, critiques its own draft, and revises.
    - **Supervisor** plans and delegates to named workers.
    - **ShipCrew** runs a set of tasks with dependencies between them (a DAG).
    - **DeepAgent** plans, keeps a workspace and verifies, for long open-ended tasks.
    - **Autopilot** runs towards a goal under a budget, with checkpoints you can resume.

    Every output below is real, from Haiku 5.5 (Anthropic) and Gemma 4 31B (Bedrock).
    """),
    md("""
    ## 1 · Models
    """),
    code("""
    import os
    import shutil
    from pathlib import Path

    from shipit_agent import Agent
    from shipit_agent.llms import build_llm_from_env
    from shipit_agent.llms.factory import build_llm_from_settings

    os.environ["SHIPIT_ANTHROPIC_MODEL"] = "claude-haiku-5-5"
    haiku = build_llm_from_env("anthropic")
    gemma = build_llm_from_settings({"model": "google.gemma-4-31b"}, provider="bedrock")
    """),
    md("""
    ## 2 · GoalAgent: work against success criteria

    A `Goal` has an objective, success criteria and a step limit. `criteria_met` is the agent's own check of each
    criterion, so treat it as a claim to verify: below it reports "at most 6 items" as met for a longer list.
    """),
    code("""
    from shipit_agent.deep import Goal, GoalAgent

    goal = Goal(
        objective="Write a short onboarding checklist for a new backend engineer.",
        success_criteria=["Has at most 6 items", "Mentions getting production access", "Mentions the on-call rotation"],
        max_steps=3,
    )
    result = GoalAgent(llm=haiku, goal=goal).run()
    print("status:", result.goal_status, "| criteria met:", result.criteria_met, "| steps:", result.steps_taken)
    print(result.output[:700])
    """),
    md("""
    ## 3 · ReflectiveAgent: draft, critique, revise

    It drafts, scores its own work against a reflection prompt, and revises until it passes the quality bar or
    runs out of rounds.
    """),
    code("""
    from shipit_agent.deep import ReflectiveAgent

    writer = ReflectiveAgent(llm=haiku, max_reflections=2, quality_threshold=0.85,
                             reflection_prompt="Is it accurate, specific, and under 60 words?")
    result = writer.run("Explain what a database index is, for a product manager.")
    print("iterations:", result.iterations, "| final quality:", result.final_quality, "| revisions:", len(result.revisions))
    for i, r in enumerate(result.reflections, 1):
        print(f"  reflection {i}: {str(r)[:160]}")
    print("\\n" + result.output)
    """),
    md("""
    ## 4 · Supervisor: plan, then delegate to workers

    Workers are ordinary agents with a name and capabilities. The supervisor plans, hands each part to the right
    worker, and writes the final answer. Here the workers run on different models.
    """),
    code("""
    from shipit_agent.deep import Supervisor, Worker
    from shipit_agent.tools import FunctionTool

    SALES = {"EMEA": [120, 135, 160], "NA": [300, 310, 305], "APAC": [80, 95, 130]}

    def quarterly_sales(region: str) -> str:
        \"\"\"Monthly sales (k$) for the three months of last quarter. region is one of EMEA, NA, APAC.\"\"\"
        return str(SALES.get(region.upper(), "unknown region"))

    analyst = Worker(name="analyst", capabilities=["sales numbers", "growth"],
                     agent=Agent(llm=gemma, prompt="You compute growth from sales data. Show numbers.",
                                 tools=[FunctionTool.from_callable(quarterly_sales, read_only=True)]))
    writer = Worker(name="writer", capabilities=["summaries"],
                    agent=Agent(llm=haiku, prompt="You write crisp three-line executive summaries."))

    supervisor = Supervisor(llm=haiku, workers=[analyst, writer], max_delegations=4)
    result = supervisor.run("Which region grew fastest last quarter? Give an executive summary.")
    print("delegations:", [(d.get("worker"), str(d.get("task"))[:60]) if isinstance(d, dict) else str(d)[:80]
                           for d in result.delegations])
    print("\\n" + result.output)
    """),
    md("""
    ## 5 · ShipCrew: tasks with dependencies

    A crew is named agents plus tasks. A task names its agent and the tasks it depends on; outputs flow into
    later tasks through `{placeholders}`. The crew works out the order.
    """),
    code("""
    from shipit_agent.deep import ShipCrew
    from shipit_agent.deep.ship_crew import ShipAgent, ShipTask

    crew = ShipCrew(
        name="release-notes",
        coordinator_llm=haiku,
        agents=[
            ShipAgent(name="engineer", role="Engineer", agent=Agent(llm=gemma, prompt="You list technical changes tersely.")),
            ShipAgent(name="writer", role="Writer", agent=Agent(llm=haiku, prompt="You write friendly release notes.")),
        ],
        tasks=[
            ShipTask(name="changes", agent="engineer", output_key="changes",
                     description="From these commits, list the user-visible changes:\\n{commits}"),
            ShipTask(name="notes", agent="writer", depends_on=["changes"],
                     description="Write release notes for version {version} from:\\n{changes}"),
        ],
    )
    print("valid:", crew.validate() or "no errors")
    result = crew.run(version="3.1.0", commits="fix: retry webhooks on 5xx\\nfeat: CSV export up to 100k rows\\nchore: bump deps")
    print("order:", result.execution_order, "| failed:", result.failed_tasks)
    print("\\n" + result.output)
    """),
    md("""
    ## 6 · DeepAgent: plan, work, verify

    `DeepAgent` adds planning, a scratch workspace and self-verification on top of the agent loop. Give it a
    folder to work in and an open-ended task.
    """),
    code("""
    from shipit_agent.deep import DeepAgent

    project = Path("deep_demo").resolve()
    shutil.rmtree(project, ignore_errors=True)
    project.mkdir()
    (project / "orders.csv").write_text(
        "id,region,amount,status\\n1,EMEA,120,paid\\n2,NA,300,refunded\\n3,EMEA,80,paid\\n4,APAC,95,paid\\n5,NA,50,paid\\n")

    deep = DeepAgent.with_builtins(llm=haiku, project_root=str(project))
    result = deep.run("Read orders.csv and report paid revenue per region, and which region leads.")
    print("tools used:", sorted({r.name for r in result.tool_results}))
    print(result.output[:600])
    """),
    md("""
    ## 7 · Autopilot: a goal, a budget, checkpoints

    Autopilot iterates towards a goal until the criteria are met or a budget runs out (time, tool calls, tokens,
    dollars or iterations). Every iteration is checkpointed, so a stopped run can resume.
    """),
    code("""
    from shipit_agent.autopilot import Autopilot, BudgetPolicy

    checkpoints = Path("autopilot_checkpoints").resolve()
    auto_goal = Goal(
        objective="Explain three Python dict gotchas.",
        success_criteria=["Three gotchas, each with a code snippet", "A one-line tip per gotcha"],
    )
    first = Autopilot(llm=haiku, goal=auto_goal, checkpoint_dir=checkpoints, install_signal_handlers=False,
                      budget=BudgetPolicy(max_iterations=1, max_dollars=0.5)).run(run_id="dict-gotchas")
    print("status:", first.status, "| iterations:", first.iterations, "| halt:", first.halt_reason)
    print("usage:", {k: round(v, 4) if isinstance(v, float) else v for k, v in first.usage.items()})
    print("checkpoint:", sorted(p.name for p in checkpoints.iterdir()))
    """),
    md("""
    ## 8 · Resume with a bigger budget

    The same `run_id` picks up where the checkpoint stopped. Here the first run already met every criterion, so
    the resumed run has no work left: it returns the checkpointed result almost at once, spending nothing.
    """),
    code("""
    second = Autopilot(llm=haiku, goal=auto_goal, checkpoint_dir=checkpoints, install_signal_handlers=False,
                       budget=BudgetPolicy(max_iterations=4, max_dollars=0.5)).resume("dict-gotchas")
    print("status:", second.status, "| iterations:", second.iterations, "| criteria met:", second.criteria_met)
    print("usage:", {k: v for k, v in second.usage.items() if k in ("tool_calls", "tokens", "dollars", "seconds")})
    print("\\n" + second.output[:700])
    """),
    md("""
    ## 9 · The same GoalAgent on Gemma 4
    """),
    code("""
    result = GoalAgent(llm=gemma, goal=goal).run()
    print("status:", result.goal_status, "| criteria met:", result.criteria_met)
    print(result.output[:500])
    """),
    md("""
    ## 10 · Clean up
    """),
    code("""
    shutil.rmtree(project, ignore_errors=True)
    shutil.rmtree(checkpoints, ignore_errors=True)
    """),
    md("""
    ## 11 · Summary

    - `GoalAgent` reports `goal_status` and `criteria_met`; `ReflectiveAgent` critiques and revises.
    - `Supervisor` plans and delegates to `Worker`s, which can run different models.
    - `ShipCrew` runs tasks in dependency order, passing outputs through `{placeholders}`.
    - `DeepAgent` adds planning, a workspace and verification for open-ended work.
    - `Autopilot` works under a `BudgetPolicy`, checkpoints every iteration, and resumes by `run_id`.

    **Next:** Guide 12 — cost, tracing, serving and output.
    """),
]
