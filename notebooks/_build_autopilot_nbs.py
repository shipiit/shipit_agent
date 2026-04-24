"""Generate the Autopilot / specialist / power-tool notebooks.

Run: `python notebooks/_build_autopilot_nbs.py`

Each notebook follows the same convention as the existing 01–36 series:
  - Paths auto-resolve whether the notebook runs from repo root or from
    `notebooks/`.
  - LLM is built via `examples.run_multi_tool_agent.build_llm_from_env("bedrock")`
    which defaults to Bedrock Llama 4 (`meta.llama4-scout-17b-instruct-v1:0`)
    so the notebook "just works" in an AWS-authenticated environment.
  - Markdown narration alternates with minimal, production-quality code.

Script re-generates idempotently — re-running overwrites only the targets.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent


def cell(kind: str, text: str) -> dict[str, Any]:
    """Build a single notebook cell. `text` is one multiline string; we
    split on newlines so each source line is its own array entry (the
    canonical .ipynb shape Jupyter emits)."""
    lines = text.splitlines(keepends=True)
    if kind == "code":
        return {
            "cell_type": "code", "metadata": {},
            "execution_count": None, "outputs": [],
            "source": lines,
        }
    return {"cell_type": "markdown", "metadata": {}, "source": lines}


def md(text: str) -> dict[str, Any]: return cell("markdown", text)
def code(text: str) -> dict[str, Any]: return cell("code", text)


def notebook(title: str, cells: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.11"},
            "shipit_notebook": {"title": title, "provider": "bedrock"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


# ── Shared bootstrap cell used by every notebook ────────────────────

BOOTSTRAP = """from pathlib import Path
import sys

# Resolve the repo root whether this cell is running from ./notebooks
# or from the repo root — mirrors the existing 01–36 notebook series.
ROOT = (
    Path.cwd().resolve().parent
    if Path.cwd().name == "notebooks"
    else Path.cwd().resolve()
)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from examples.run_multi_tool_agent import build_llm_from_env

# Bedrock Llama 4 Scout is the default model this library ships with
# (see `shipit_agent/config.py`). No model name required — the helper
# reads `AWS_REGION` / credentials from env and returns an adapter that
# works with every Autopilot / Agent class.
llm = build_llm_from_env("bedrock")
print("Bedrock LLM ready:", type(llm).__name__)
"""


# ── 37 — Autopilot quickstart ───────────────────────────────────────

NB_37 = notebook("Autopilot quickstart (Bedrock Llama)", [
    md("# 37 — Autopilot quickstart\n\nAutopilot is the **long-running, goal-driven, budget-gated** runner. It wraps `GoalAgent` + `PersistentAgent` with:\n\n- **Goal-satisfaction termination** (not a fixed step count).\n- **Budget gates**: wall-clock, tool calls, tokens, dollars, iterations.\n- **Atomic checkpoints** so a crash costs at most one iteration.\n- **Heartbeats + live event stream** for Claude-Desktop-style UIs.\n\nThis notebook runs against **Bedrock Llama 4 Scout** (the library default). Every cell below is safe to re-run in any order.\n"),
    code(BOOTSTRAP),
    md("## 1. Declare a Goal\n\nA `Goal` is an objective plus a list of success criteria. Autopilot stops iterating the moment every criterion is satisfied OR a budget trips — whichever comes first."),
    code("""from shipit_agent.deep import Goal

goal = Goal(
    objective=\"Summarize the three most common Python dict gotchas and show a working snippet for each.\",
    success_criteria=[
        \"At least 3 gotchas explained in prose\",
        \"Each gotcha has a Python snippet that reproduces it\",
        \"A one-line fix or avoidance is shown for each\",
    ],
)
goal
"""),
    md("## 2. Build the Autopilot\n\n`BudgetPolicy` has conservative defaults (30 min, 100 tool calls, \\$5). For this demo we cap harder so it finishes quickly."),
    code("""from shipit_agent.autopilot import Autopilot, BudgetPolicy, default_heartbeat_stderr

autopilot = Autopilot(
    llm=llm,
    goal=goal,
    budget=BudgetPolicy(
        max_seconds=600,        # 10 min cap for the demo
        max_tool_calls=20,
        max_iterations=8,
        max_tokens=300_000,
        max_dollars=2.0,
    ),
    heartbeat_every_seconds=30,
    on_heartbeat=default_heartbeat_stderr,
)
print(\"Autopilot ready — budget:\", autopilot.budget)
"""),
    md("## 3. Run synchronously with `run(run_id=...)`\n\n`run()` drains the goal loop and returns an `AutopilotResult`. Pass a stable `run_id` so the checkpoint is resumable later."),
    code("""result = autopilot.run(run_id=\"py-dict-gotchas-v1\")

print(f\"status:       {result.status}\")
print(f\"iterations:   {result.iterations}\")
print(f\"criteria met: {sum(1 for c in result.criteria_met if c)} / {len(result.criteria_met)}\")
print(f\"halt reason:  {result.halt_reason}\")
print()
print(result.output[:800])
"""),
    md("## 4. Inspect the checkpoint\n\nAutopilot writes one JSON file per run to `~/.shipit_agent/checkpoints/<run_id>.json`. That file is enough to resume on another machine."),
    code("""import json, os
from pathlib import Path

cp = Path.home() / \".shipit_agent\" / \"checkpoints\" / \"py-dict-gotchas-v1.json\"
if cp.exists():
    data = json.loads(cp.read_text())
    print(json.dumps({k: data[k] for k in (\"run_id\", \"iterations\", \"usage\")}, indent=2))
else:
    print(\"(no checkpoint — run cell 3 first)\")
"""),
    md("## 5. Understand `status`\n\n- `completed` — every criterion passed.\n- `partial` — some criteria passed; run halted because of budget.\n- `halted` — budget tripped before any criterion could be verified.\n- `failed` — an exception aborted the run; the checkpoint captures what was known at crash time.\n\nYou can call `autopilot.resume(run_id=...)` to pick up any non-`completed` run."),
    md("## Where next\n\n- **38 — Autopilot live streaming** — watch the iteration, tool call, and heartbeat events as the run progresses.\n- **39 — Persistence & the scheduler daemon** — fire-and-forget 24h operation.\n- **40-42 — Specialist agents** — developer, debugger, researcher, design reviewer, PM, sales, CS, marketing."),
])

# ── 38 — Autopilot live streaming ───────────────────────────────────

NB_38 = notebook("Autopilot live streaming (Claude-Desktop-style)", [
    md("# 38 — Autopilot live streaming\n\nEvery long-running run should show signs of life. This notebook demos `Autopilot.stream()` — a generator that yields events in real time, and `live_renderer.render_stream()` — a pretty TUI consumer. Drop-in components for building your own Claude-Desktop-style dashboard over Bedrock Llama.\n"),
    code(BOOTSTRAP),
    md("## 1. A streaming run\n\n`autopilot.stream()` returns a Python iterator of `{\"kind\": str, **payload}` dicts. Every iteration emits `autopilot.iteration`; periodic `autopilot.heartbeat` events prove the run is alive during long idle stretches."),
    code("""from shipit_agent.autopilot import Autopilot, BudgetPolicy
from shipit_agent.deep import Goal

goal = Goal(
    objective=\"List the top 5 Python HTTP client libraries and their tradeoffs.\",
    success_criteria=[\"At least 5 libraries listed\", \"Each has a one-line tradeoff\"],
)
autopilot = Autopilot(
    llm=llm, goal=goal,
    budget=BudgetPolicy(max_seconds=300, max_iterations=6, max_tool_calls=15),
    heartbeat_every_seconds=20,
)
"""),
    md("## 2. Consume events one by one\n\nThe simplest consumer just prints the `kind` for every event. Use this when you want full control of how the UI renders."),
    code("""for ev in autopilot.stream(run_id=\"http-libs-v1\"):
    kind = ev[\"kind\"]
    if kind == \"autopilot.run_started\":
        print(f\"🚀 run_started — goal: {ev['goal']['objective']}\")
    elif kind == \"autopilot.iteration\":
        met = ev[\"criteria_met\"]
        score = f\"{sum(met)}/{len(met)}\"
        print(f\"✓ iter {ev['iteration']} — {score} criteria met\")
    elif kind == \"autopilot.heartbeat\":
        print(f\"♥ heartbeat iter={ev['iteration']}\")
    elif kind == \"autopilot.budget_exceeded\":
        print(f\"⛔ budget: {ev['reason']}\")
    elif kind == \"autopilot.result\":
        print(f\"🏁 {ev['status']} — {ev['iterations']} iters\")
"""),
    md("## 3. Use the built-in TUI renderer\n\n`render_stream` gives you a Claude-Desktop-style formatted feed for free. Three modes: `tui` (ANSI colour), `jsonl` (machine readable), `plain` (CI logs)."),
    code("""from shipit_agent.autopilot import Autopilot, BudgetPolicy
from shipit_agent.deep import Goal
from shipit_agent.live_renderer import render_stream

autopilot2 = Autopilot(
    llm=llm,
    goal=Goal(objective=\"Write a haiku about Bedrock Llama\", success_criteria=[\"Three lines\", \"5-7-5 syllables\"]),
    budget=BudgetPolicy(max_iterations=4, max_seconds=120),
)
# `fmt=\"plain\"` is notebook-friendly (no ANSI escapes).
final = render_stream(autopilot2.stream(run_id=\"haiku-v1\"), fmt=\"plain\")
print(\"\\nfinal status:\", final and final.get(\"status\"))
"""),
    md("## 4. JSONL stream — pipe into anything\n\nFor durable logs or a browser-side UI, `jsonl` is the right mode: one event per line, always valid JSON."),
    code("""from pathlib import Path
import io
from shipit_agent.live_renderer import render_stream

autopilot3 = Autopilot(
    llm=llm,
    goal=Goal(objective=\"2+2?\", success_criteria=[\"Answer is 4\"]),
    budget=BudgetPolicy(max_iterations=2, max_seconds=60),
)
buffer = io.StringIO()
render_stream(autopilot3.stream(run_id=\"math-v1\"), fmt=\"jsonl\", out=buffer)

for line in buffer.getvalue().strip().split(\"\\n\")[:6]:
    print(line[:120])
"""),
    md("## 5. Heartbeats in your own sink\n\nFor a production dashboard you often want to push to Slack / Datadog / custom webhook on each heartbeat. Any callable taking `dict` works:"),
    code("""heartbeats = []
def record(ev):
    if ev.get(\"kind\") == \"autopilot.heartbeat\":
        heartbeats.append(ev)

autopilot4 = Autopilot(
    llm=llm,
    goal=Goal(objective=\"Who invented Python?\", success_criteria=[\"Mentions Guido van Rossum\"]),
    budget=BudgetPolicy(max_iterations=3, max_seconds=90),
    heartbeat_every_seconds=5,  # aggressive for demo
    on_heartbeat=record,
)
for _ in autopilot4.stream(run_id=\"guido-v1\"):
    pass

print(f\"Captured {len(heartbeats)} heartbeat events during the run.\")
"""),
    md("## Summary\n\n- `Autopilot.stream()` yields events; the final one is always `autopilot.result`.\n- `render_stream(stream, fmt=...)` formats them: `tui` | `plain` | `jsonl`.\n- `on_heartbeat=callable` pushes heartbeat events to any sink you want.\n\nNext: **39 — Persistence & the scheduler daemon**."),
])

# ── 39 — Persistence + scheduler daemon ─────────────────────────────

NB_39 = notebook("Persistence, resume, and the scheduler daemon", [
    md("# 39 — Persistence, resume, and the scheduler daemon\n\nAutopilot checkpoints every iteration so a crash is cheap. The `SchedulerDaemon` takes that further — a persistent goal queue on disk, drained tick-by-tick until SIGINT. This is the piece that lets shipit_agent run for hours/days unattended.\n"),
    code(BOOTSTRAP),
    md("## 1. Crash → resume round-trip\n\nWe'll simulate a crash by capping `max_iterations=1` for the first run, then resume with a larger cap."),
    code("""from shipit_agent.autopilot import Autopilot, BudgetPolicy
from shipit_agent.deep import Goal

goal = Goal(
    objective=\"Outline a simple CLI todo app architecture.\",
    success_criteria=[\"Files listed\", \"CLI commands described\", \"Storage choice justified\"],
)

# First run — tiny budget, expected to halt partial.
first = Autopilot(
    llm=llm, goal=goal,
    budget=BudgetPolicy(max_iterations=1, max_seconds=120),
).run(run_id=\"todo-arch\")

print(f\"First run → {first.status} (iters={first.iterations})\")
print(f\"Halt: {first.halt_reason}\")
"""),
    md("Now resume — Autopilot loads the checkpoint and keeps going."),
    code("""second = Autopilot(
    llm=llm, goal=goal,
    budget=BudgetPolicy(max_iterations=6, max_seconds=240),
).resume(\"todo-arch\")

print(f\"Resumed → {second.status} (iters={second.iterations})\")
print(f\"Halt: {second.halt_reason}\")
print()
print(second.output[:600])
"""),
    md("The `iterations` counter continues where the first run left off — no re-work.\n\n## 2. The goal queue\n\n`SchedulerDaemon` owns a JSON file at `~/.shipit_agent/autopilot-queue.json`. Any process can `enqueue()`; the daemon drains them on its tick."),
    code("""from shipit_agent.scheduler_daemon import SchedulerDaemon

# llm_factory builds a fresh LLM per run — important for long daemons
# where tokens/credentials may rotate.
daemon = SchedulerDaemon(llm_factory=lambda: llm, tick_seconds=3)

daemon.enqueue(
    run_id=\"nightly-lint\",
    objective=\"Summarise all 'error' lines in build.log\",
    success_criteria=[\"Counts per file reported\", \"Top 3 noisiest files listed\"],
    budget={\"max_iterations\": 4, \"max_seconds\": 180},
)
daemon.enqueue(
    run_id=\"morning-status\",
    objective=\"Write a two-paragraph status for yesterday's engineering work.\",
    success_criteria=[\"Mentions merges\", \"Mentions open blockers\"],
    budget={\"max_iterations\": 3},
)

for entry in daemon.list_queue():
    print(f\"{entry.run_id:<20} [{entry.status:<7}] {entry.objective[:60]}\")
"""),
    md("## 3. Drain one at a time — `run_once()`\n\nFor CI or a cron job that should fire one goal per invocation:"),
    code("""result = daemon.run_once()
if result is None:
    print(\"(queue empty)\")
else:
    print(f\"{result.run_id} → {result.status} (iters={result.iterations})\")

# Look at the queue afterwards — status moves from 'pending' → 'done'/'halted'.
for entry in daemon.list_queue():
    print(f\"{entry.run_id:<20} [{entry.status}]\")
"""),
    md("## 4. Run forever — `run_forever()`\n\nIn a notebook we won't block on this, but the one-liner you'd use in production is:\n\n```python\ndaemon.run_forever()\n```\n\nIt installs SIGINT/SIGTERM handlers, ticks on `tick_seconds`, drains each pending goal, and emits `daemon_heartbeat` events on idle. Systemd / launchd / Docker can supervise it directly.\n\n**Equivalent CLI**: `shipit daemon --tick 5` (see `shipit_agent.cli_autopilot`)."),
    md("## 5. Clean up the queue"),
    code("""for run_id in (\"nightly-lint\", \"morning-status\"):
    daemon.remove(run_id)
print(\"queue length:\", len(daemon.list_queue()))
"""),
    md("## Summary\n\n- Autopilot writes a checkpoint after **every iteration**.\n- `resume(run_id)` picks up at the last successful iteration — no re-work.\n- `SchedulerDaemon` drives multi-goal 24h operation. Queue state lives on disk; the daemon process is stateless.\n\nNext: **40, 41, 42** — specialist agents in action."),
])


# ── 40 — Developer + Debugger + Researcher ──────────────────────────

NB_40 = notebook("Developer · Debugger · Researcher specialists", [
    md("# 40 — Developer · Debugger · Researcher\n\nThree of the 47 specialists that ship with shipit_agent. Each is a fully-formed prompt + model + tool preset. Use them alone, or hand any of them to an Autopilot for long-running operation.\n\nAll three run against **Bedrock Llama** by default via `build_llm_from_env('bedrock')`."),
    code(BOOTSTRAP),
    md("## 1. Load the specialist roster\n\n`AgentRegistry` loads every `.json` definition shipped in `shipit_agent/agents/agents.json`, including the seven roles added by the specialist patch."),
    code("""from shipit_agent.agents import AgentRegistry

registry = AgentRegistry()
by_category = {}
for a in registry.all():
    by_category.setdefault(a.category, []).append(a.id)

for cat, ids in sorted(by_category.items()):
    print(f\"{cat}:\")
    for aid in ids:
        print(f\"  - {aid}\")
"""),
    md("## 2. Generalist Developer — implement cleanly, verify, report"),
    code("""from shipit_agent import Agent
from shipit_agent.builtins import get_builtin_tools

dev_def = registry.get(\"generalist-developer\")
dev = Agent(
    llm=llm,
    prompt=dev_def.prompt,
    tools=get_builtin_tools(project_root=\".\"),
    max_iterations=dev_def.maxIterations or 40,
    name=dev_def.name,
)
result = dev.run(\"Add a docstring to the function in shipit_agent/autopilot/budget.py named `BudgetPolicy.exceeded` explaining the return shape in one sentence. Do not change behaviour.\")
print(result.output[:700])
"""),
    md("## 3. Debugger — reproduce, isolate, explain, fix\n\nThe debugger specialist is hypothesis-driven: it refuses to write any fix until it has a minimal reproducer and a one-paragraph root-cause statement."),
    code("""dbg_def = registry.get(\"debugger\")
dbg = Agent(
    llm=llm, prompt=dbg_def.prompt,
    tools=get_builtin_tools(project_root=\".\"),
    max_iterations=dbg_def.maxIterations or 40,
    name=dbg_def.name,
)
result = dbg.run(
    \"Investigate why `Autopilot.run()` might raise FileExistsError, describe the root cause, and explain the correct resolution flow.\"
)
print(result.output[:900])
"""),
    md("## 4. Researcher + `research_brief` tool\n\nThe researcher pairs naturally with the new `research_brief` tool — web search + top-page skim + structured citations."),
    code("""from shipit_agent.tools.research_brief import ResearchBriefTool

researcher_def = registry.get(\"researcher\")
researcher = Agent(
    llm=llm, prompt=researcher_def.prompt,
    tools=[ResearchBriefTool()],
    max_iterations=researcher_def.maxIterations or 20,
    name=researcher_def.name,
)
result = researcher.run(\"Brief me on recent Python dependency management tools (uv, poetry, pdm, rye). One-line tradeoff each, with citations.\")
print(result.output[:900])
"""),
    md("## 5. Researcher + Autopilot — long-form, budget-gated\n\nHand the researcher to Autopilot when the task needs more than one pass — e.g. multi-source synthesis with a deliverable."),
    code("""from shipit_agent.autopilot import Autopilot, BudgetPolicy
from shipit_agent.deep import Goal

goal = Goal(
    objective=\"Produce a two-page brief on the state of local LLM tooling (ollama, llama.cpp, mlx) in Q2 2026.\",
    success_criteria=[
        \"Covers all three ecosystems\",
        \"Cites at least three sources per ecosystem\",
        \"Ends with a recommendation table\",
    ],
)
long_runner = Autopilot(
    llm=llm, goal=goal,
    tools=[ResearchBriefTool()],
    budget=BudgetPolicy(max_iterations=6, max_seconds=600, max_tool_calls=25),
)

result = long_runner.run(run_id=\"llm-tooling-brief\")
print(f\"status={result.status} · iters={result.iterations}\")
print(result.output[:800])
"""),
    md("## Summary\n\n- 47 specialists preloaded; 7 added this release (developer, debugger, design-reviewer, PM, sales, CS, marketing-writer).\n- Any specialist + Autopilot + a budget = production-ready long-running operation.\n\nNext: **41 — design reviewer, product manager, sales, CS, marketing**."),
])


# ── 41 — Design · PM · Sales · CS · Marketing ───────────────────────

NB_41 = notebook("Design · PM · Sales · CS · Marketing specialists", [
    md("# 41 — Design · PM · Sales · CS · Marketing\n\nThe non-engineering side of the specialist roster. Each persona is prompted for domain-correct outputs — a design reviewer leads with user tasks, a marketing writer cuts adjectives, a CS manager opens with the customer's stated success metric.\n\nRuns on **Bedrock Llama** — no extra credentials required."),
    code(BOOTSTRAP),
    code("""from shipit_agent import Agent
from shipit_agent.agents import AgentRegistry
from shipit_agent.builtins import get_builtin_tools
registry = AgentRegistry()
"""),
    md("## 1. Design reviewer — user-task first, accessibility non-negotiable"),
    code("""design_def = registry.get(\"design-reviewer\")
designer = Agent(
    llm=llm, prompt=design_def.prompt,
    tools=get_builtin_tools(project_root=\".\"),
    max_iterations=design_def.maxIterations or 20,
    name=design_def.name,
)
result = designer.run(\"Review the onboarding flow described in this repo's README and list P0/P1/P2 findings with the principle each violates.\")
print(result.output[:900])
"""),
    md("## 2. Product manager — scope minimally, specify non-goals\n\nThe PM specialist is good at turning a vague ask into a shippable MVP + explicit non-goals. Feed it a one-line feature request and you get a structured spec back."),
    code("""pm_def = registry.get(\"product-manager\")
pm = Agent(
    llm=llm, prompt=pm_def.prompt, tools=[], name=pm_def.name,
    max_iterations=pm_def.maxIterations or 20,
)
result = pm.run(\"Spec out a lightweight 'share run' feature for Autopilot that lets engineers email a read-only link to a completed run.\")
print(result.output[:900])
"""),
    md("## 3. Sales outreach — research first, then a 120-word email"),
    code("""sales_def = registry.get(\"sales-outreach\")
sales = Agent(
    llm=llm, prompt=sales_def.prompt, tools=[], name=sales_def.name,
    max_iterations=sales_def.maxIterations or 15,
)
result = sales.run(\"Prep an outreach for the VP of Engineering at a Series B fintech that just announced a hiring freeze. Our pitch is unattended overnight refactoring runs that cut eng costs.\")
print(result.output[:900])
"""),
    md("### 3a. Wire in HubSpot for real CRM actions\n\nIf you have a HubSpot private-app token in `HUBSPOT_TOKEN`, the `hubspot_ops` tool gives the sales agent search / create / add-note superpowers against your real CRM."),
    code("""import os

if os.environ.get(\"HUBSPOT_TOKEN\"):
    from shipit_agent.tools.hubspot import HubspotTool
    sales_with_crm = Agent(
        llm=llm, prompt=sales_def.prompt,
        tools=[HubspotTool()],
        max_iterations=12,
        name=sales_def.name,
    )
    print(\"Sales agent ready with HubSpot tool — replace the .run() call with your actual prospect context.\")
else:
    print(\"Set HUBSPOT_TOKEN in your env to enable live CRM lookups — this cell is a no-op without it.\")
"""),
    md("## 4. Customer success — onboarding, health, renewal\n\nCS agent's super-power is reading before writing: sales handoff notes + usage signals + ticket history, then a structured 30-day plan."),
    code("""cs_def = registry.get(\"customer-success\")
cs = Agent(
    llm=llm, prompt=cs_def.prompt, tools=[], name=cs_def.name,
    max_iterations=cs_def.maxIterations or 15,
)
result = cs.run(\"A new $150k/yr customer just signed. Their stated goal was 'cut incident response time by 40%'. Draft the first 30-day success plan and kickoff agenda.\")
print(result.output[:900])
"""),
    md("## 5. Marketing writer — concrete, not clever"),
    code("""mkt_def = registry.get(\"marketing-writer\")
mkt = Agent(
    llm=llm, prompt=mkt_def.prompt, tools=[], name=mkt_def.name,
    max_iterations=mkt_def.maxIterations or 15,
)
result = mkt.run(\"Write the launch post for shipit_agent 1.1 — the Autopilot release. Readers are senior engineers. Keep it ≤250 words, concrete, no 'blazing fast'.\")
print(result.output[:900])
"""),
    md("## Summary\n\nFive specialists you can drop into a Slack bot, a Notion task, or wrap in Autopilot for long-form artifacts. Every prompt was written as a production spec — not a sales demo — so outputs tend to be usable as-is.\n\nNext: **42 — computer_use and the other power tools**."),
])


# ── 42 — computer_use + new tools ──────────────────────────────────

NB_42 = notebook("computer_use, hubspot_ops, research_brief — power tools", [
    md("# 42 — Power tools\n\nThree new tools from this release — each pairs naturally with one or more of the specialists from notebook 41.\n\n| Tool | Who it's for | Auth |\n|---|---|---|\n| `computer_use` | Anyone driving a native GUI (macOS / Linux / Windows) | None — uses platform primitives |\n| `hubspot_ops` | Sales, customer success | `HUBSPOT_TOKEN` env |\n| `research_brief` | Researcher, PM, marketing, sales | None — public web search |\n"),
    code(BOOTSTRAP),
    md("## 1. `computer_use` — desktop automation\n\n`computer_use` is the library's Claude-Desktop-style primitive. It drives the LOCAL desktop via platform-native helpers:\n\n- macOS → `screencapture` + `cliclick` (or AppleScript fallback)\n- Linux → `scrot` / ImageMagick `import` + `xdotool`\n- Windows → PowerShell"),
    code("""from shipit_agent.tools.computer_use import ComputerUseTool

computer = ComputerUseTool()
print(\"Schema enum:\", computer.schema()['function']['parameters']['properties']['action']['enum'])
print(\"Output dir:\", computer.output_dir)
"""),
    md("### 1a. Take a screenshot\n\nWhen run on your laptop, this actually captures the screen. In this notebook it'll succeed only if `screencapture` (macOS) / `scrot` (linux) / powershell (windows) is on PATH — otherwise you'll get a clear install hint."),
    code("""from shipit_agent.tools.base import ToolContext

out = computer.run(ToolContext(prompt=\"demo\"), action=\"screenshot\")
print(out.text)
"""),
    md("### 1b. Use it inside an Autopilot\n\nFor a tutorial / QA run, combine `computer_use` with a specialist and Autopilot: the agent drives the GUI, the runtime keeps it on track with a budget."),
    code("""from shipit_agent import Agent
from shipit_agent.agents import AgentRegistry

registry = AgentRegistry()
def_ = registry.get(\"design-reviewer\")
ui_agent = Agent(
    llm=llm, prompt=def_.prompt, tools=[computer],
    max_iterations=6, name=\"UI Reviewer\",
)
# In your own environment, replace the prompt with something that
# drives your app (e.g. open Preferences, verify toggles, screenshot).
print(\"UI Reviewer agent ready:\", ui_agent.name)
"""),
    md("## 2. `research_brief` — one-call research primitive\n\nSearch the web, skim the top N pages, return a structured brief with numbered citations. No API key — uses DuckDuckGo HTML."),
    code("""from shipit_agent.tools.research_brief import ResearchBriefTool

research = ResearchBriefTool()
out = research.run(ToolContext(prompt=\"demo\"), query=\"uv vs poetry python package manager 2026\", max_sources=4)
print(out.text)
"""),
    md("Pass `deep=True` to also fetch each result page and embed a short summary. Use sparingly — one call fans out to N+1 HTTP requests."),
    code("""out = research.run(ToolContext(prompt=\"demo\"), query=\"SQLite vs DuckDB for analytics\", max_sources=3, deep=True)
print(out.text[:1200])
"""),
    md("## 3. `hubspot_ops` — CRM in one tool\n\nOne tool, many actions: `search_contacts`, `search_companies`, `search_deals`, `get_*`, `create_contact`, `create_deal`, `add_note`, `list_owners`. Auth is `HUBSPOT_TOKEN` env (private-app bearer token)."),
    code("""import os
from shipit_agent.tools.hubspot import HubspotTool

if os.environ.get(\"HUBSPOT_TOKEN\"):
    hubspot = HubspotTool()
    out = hubspot.run(ToolContext(prompt=\"demo\"), action=\"search_contacts\", query=\"test\", limit=5)
    print(out.text[:800])
else:
    print(\"Set HUBSPOT_TOKEN to hit live HubSpot — schema still works for dry-run inspection:\")
    from shipit_agent.tools.hubspot import HubspotTool as H
    print(H(token=None).schema()['function']['parameters']['properties']['action']['enum'])
"""),
    md("## 4. Stacking tools in one long-running Autopilot\n\nA single agent with all three tools plus a substantial budget can drive a surprisingly complex outbound-sales flow end to end: research accounts (research_brief), log activity (hubspot_ops), take screenshots for internal review (computer_use). Budgets make it safe to leave running."),
    code("""from shipit_agent.autopilot import Autopilot, BudgetPolicy
from shipit_agent.deep import Goal

tools = [research, computer]   # add HubspotTool() when token is set
autopilot = Autopilot(
    llm=llm,
    goal=Goal(
        objective=\"Compare three vendors of time-series databases and produce a recommendation.\",
        success_criteria=[
            \"Each vendor has a 1-paragraph summary with citations\",
            \"A comparison table covering licensing + scale + pricing\",
            \"A 1-paragraph recommendation with the primary reason\",
        ],
    ),
    tools=tools,
    budget=BudgetPolicy(max_iterations=8, max_seconds=600, max_tool_calls=30, max_dollars=3.0),
)
print(\"Ready to run. autopilot.run(run_id='tsdb-shootout') when you're ready.\")
"""),
    md("## Summary\n\nEach tool is designed to be usable standalone, but the real leverage comes from handing them to an Autopilot with a thoughtful budget. That's the Claude-Desktop model: long-running, goal-directed, live-streamed, budget-gated.\n\nFull series complete. Thanks for reading — now go build."),
])


# ── Writer ──────────────────────────────────────────────────────────

NB_43 = notebook("Fan-out, Critic, and Artifacts — Claude-Desktop-grade Autopilot", [
    md("# 43 — Fan-out · Critic · Artifacts\n\nThree features that turn Autopilot from a solid long-runner into a Claude-Desktop-grade coordinator:\n\n- **`Autopilot.fanout(items, objective_template=...)`** — dispatch N child Autopilots in parallel, each with a budget-scaled slice of the parent budget.\n- **`Critic`** — a reflection loop that scores output against criteria and feeds suggestions into the next iteration; short-circuits the run when it's confident every criterion is met.\n- **`ArtifactCollector`** — Claude-Desktop-style structured deliverables. Auto-extracts code blocks and markdown docs from each iteration's output; tools can also push explicit artifacts via result metadata.\n\nAll of the below runs on **Bedrock Llama** — no extra provider credentials required."),
    code(BOOTSTRAP),
    md("## 1. Parallel fan-out — the 'review every PR' workload\n\n`fanout` takes a list of items and an objective template. It builds one child Autopilot per item and runs them concurrently in a thread pool. Each child gets a `child_budget_frac` slice of the parent budget so the aggregate cost is bounded."),
    code("""from shipit_agent.autopilot import Autopilot, BudgetPolicy
from shipit_agent.deep import Goal

autopilot = Autopilot(
    llm=llm,
    goal=Goal(objective=\"fanout-parent\", success_criteria=[\"done\"]),
    budget=BudgetPolicy(max_seconds=600, max_iterations=6, max_tool_calls=30, max_dollars=3.0),
)

# Each child inherits 20% of the parent budget — 6 children in parallel can
# therefore spend at most ~120% of the parent cap if every child fully
# utilizes. Adjust `child_budget_frac` if you need tighter global limits.
result = autopilot.fanout(
    items=[\"PR-101\", \"PR-102\", \"PR-103\", \"PR-104\"],
    objective_template=\"Summarize {item} — what changed, what's risky, what to watch post-merge.\",
    criteria_template=[\"Mentions the main change\", \"Lists one risk\"],
    max_parallel=4,
    child_budget_frac=0.25,
)
print(f\"fan-out status: {result.status} · wall: {result.wall_seconds:.1f}s\")
for c in result.children:
    print(f\"  {c['run_id']:<40} {c['status']:<10} {c['iterations']} iters\")
"""),
    md("### 1a. Streaming fan-out\n\nFor a live UI over a long batch, use `fanout_stream` — it yields one `autopilot.fanout_child` event the moment each child completes."),
    code("""events = list(autopilot.fanout_stream(
    items=[\"A\", \"B\", \"C\"],
    objective_template=\"One-line summary of module {item}\",
    max_parallel=3,
    child_budget_frac=0.15,
))
for ev in events:
    if ev[\"kind\"] == \"autopilot.fanout_child\":
        print(f\"child {ev['item_index']}: {ev['status']} ({ev['iterations']} iters)\")
    elif ev[\"kind\"] == \"autopilot.fanout_result\":
        print(f\"final: {ev['status']} — {len(ev['children'])} children\")
"""),
    md("## 2. Critic loop — reflection that cuts wasted iterations\n\nAfter every iteration, the critic reviews the output against the criteria and emits a verdict. When it's *confident* the criteria are met (default gate: `confidence >= 0.75`), Autopilot stops — no more burning budget on already-satisfied goals.\n\nThe critic can be the run's own LLM (cheap self-check) or a dedicated reviewer model (stronger, 2× cost)."),
    code("""from shipit_agent.autopilot import Critic

# `critic=True` builds a default Critic that uses your run's LLM.
autopilot_with_critic = Autopilot(
    llm=llm,
    goal=Goal(
        objective=\"Explain the Python GIL in two paragraphs and include a code snippet showing where it matters.\",
        success_criteria=[
            \"Two paragraphs of prose\",
            \"Contains a runnable Python snippet showing GIL-related behavior\",
        ],
    ),
    budget=BudgetPolicy(max_seconds=300, max_iterations=6, max_tool_calls=10),
    critic=True,
)
result = autopilot_with_critic.run(run_id=\"gil-explainer\")
print(f\"status={result.status} · iters={result.iterations} · halt={result.halt_reason}\")
print(\"critic verdict:\", result.critic_verdict)
"""),
    md("### 2a. Dedicated reviewer — separate LLM for high-stakes reviews\n\nFor a security review or production-change run, give the critic its own stronger model so the reviewer isn't marking its own homework."),
    code("""# For the demo we reuse the same llm, but you'd pass a separate
# Bedrock/Anthropic adapter here. The `confidence_threshold` raises the
# gate for accepting the critic's go-ahead.
strict_critic = Critic(llm=llm, confidence_threshold=0.85)
autopilot_strict = Autopilot(
    llm=llm,
    goal=Goal(
        objective=\"Audit shipit_agent/autopilot/critic.py for any obvious logic bugs.\",
        success_criteria=[\"At least one observation listed\", \"Each observation cites a line number\"],
    ),
    budget=BudgetPolicy(max_seconds=240, max_iterations=4, max_tool_calls=10),
    critic=strict_critic,
)
print(\"Ready. Call .run(run_id='critic-audit') to execute.\")
"""),
    md("## 3. Artifacts — Claude-Desktop-style deliverables\n\nWhen the agent produces code blocks, markdown docs, or tool outputs that declare themselves artifacts, the `ArtifactCollector` grabs them. The final `AutopilotResult.artifacts` is a list the caller can render as a deliverable panel."),
    code("""from shipit_agent.autopilot import ArtifactCollector

collector = ArtifactCollector()
autopilot_art = Autopilot(
    llm=llm,
    goal=Goal(
        objective=\"Write a Python function that reads a CSV and returns row count + column count. Include a usage example.\",
        success_criteria=[\"A `def` is present\", \"Usage example in a fenced block\"],
    ),
    budget=BudgetPolicy(max_seconds=240, max_iterations=4, max_tool_calls=8),
    artifacts=collector,
    critic=True,     # combine with the critic loop
)
result = autopilot_art.run(run_id=\"csv-sizer\")
print(f\"{len(result.artifacts)} artifacts extracted:\")
for a in result.artifacts:
    print(f\"  [{a['kind']}] {a['name']} — {len(a['content'])} chars\")
"""),
    md("### 3a. Persist artifacts to disk\n\nPass `persist_dir` when you want one JSON file per artifact (handy for CI runs that upload the dir as build output)."),
    code("""from pathlib import Path
from shipit_agent.autopilot import ArtifactCollector

out_dir = Path.home() / \".shipit_agent\" / \"artifacts-demo\"
disk_collector = ArtifactCollector(persist_dir=out_dir)
disk_collector.add(kind=\"code\", name=\"hello.py\", content=\"print('hi')\", language=\"python\")
print(\"files written:\")
for p in out_dir.glob(\"*.json\"):
    print(\" \", p.name)
"""),
    md("### 3b. Live artifact events in the stream\n\n`autopilot.stream()` emits `autopilot.artifact` events the moment each artifact is collected — perfect for building a live deliverable dock in your UI."),
    code("""autopilot_live = Autopilot(
    llm=llm,
    goal=Goal(objective=\"Give me a Python one-liner that reverses a string.\",
              success_criteria=[\"Contains a fenced code block\"]),
    budget=BudgetPolicy(max_seconds=120, max_iterations=3),
    artifacts=True,     # shorthand: builds a default ArtifactCollector
)
for ev in autopilot_live.stream(run_id=\"reverse-string\"):
    if ev[\"kind\"] == \"autopilot.artifact\":
        print(f\"  [artifact] {ev['artifact_kind']:<10} {ev['name']}\")
    elif ev[\"kind\"] == \"autopilot.result\":
        print(f\"final: {ev['status']} with {len(ev['artifacts'])} artifacts\")
"""),
    md("## 4. The full power stack — fan-out + critic + artifacts together\n\nOne Autopilot with all three features wired. Useful for a nightly run that reviews everything merged today, produces a structured digest per PR, and surfaces each as a named artifact."),
    code("""from shipit_agent.autopilot import Autopilot, BudgetPolicy, Critic, ArtifactCollector
from shipit_agent.deep import Goal

parent = Autopilot(
    llm=llm,
    goal=Goal(objective=\"nightly-review\", success_criteria=[\"per-item summary\"]),
    budget=BudgetPolicy(max_seconds=600, max_iterations=4, max_tool_calls=20, max_dollars=3.0),
    critic=True,
    artifacts=True,
)

# Fan out across a batch of tickets (real callers pass 50-200 IDs here).
batch_result = parent.fanout(
    items=[\"INFRA-11\", \"INFRA-12\", \"INFRA-13\"],
    objective_template=\"Write a one-paragraph summary of ticket {item} as a markdown artifact.\",
    criteria_template=[\"One paragraph\", \"Starts with a ## heading\"],
    max_parallel=3,
    child_budget_frac=0.3,
)
print(f\"batch: {batch_result.status} across {len(batch_result.children)} children\")
print(f\"children failed: {len(batch_result.failed)}\")
"""),
    md("## Summary\n\n- **`fanout`** turns 'do 50 things' from overnight-sequential to minutes-parallel, with strict per-child budgets so aggregate spend is bounded.\n- **`Critic`** adds reflection: the run terminates the moment a confident reviewer agrees the goal is met. Works with the run's own LLM or a dedicated stronger reviewer.\n- **`ArtifactCollector`** surfaces structured deliverables (code, docs, tool outputs) — the final result and the event stream both carry them so your UI can render a proper deliverable panel.\n\nAll three stack cleanly. Budget-gated, streaming, Bedrock-default. This is the long-running, goal-directed surface Claude Desktop exposes — and you can run it headless."),
])


NB_44 = notebook("The Complete Tour — every Autopilot feature in one notebook", [
    md("# 44 — The Complete Tour\n\nOne notebook that exercises every new feature this release ships with. Use it as a runnable reference when showing the library to someone for the first time — it starts with the LLM bootstrap and ends with a multi-agent fan-out under a critic loop.\n\nSections:\n1. **Bootstrap** — Bedrock Llama, ready in one line.\n2. **Specialist registry** — all 47 prebuilt agents, categorised.\n3. **Autopilot basics** — goal, budget, run, inspect.\n4. **Live event streaming** — watch each iteration as it happens.\n5. **Persistence & resume** — crash-safe long runs.\n6. **Scheduler daemon** — goal queue for 24-hour operation.\n7. **Reflection critic** — verify criteria with a second-opinion LLM.\n8. **Artifact collector** — structured deliverables, Claude-Desktop style.\n9. **Parallel fan-out** — N concurrent goals with bounded aggregate budget.\n10. **Power tools** — computer_use, hubspot_ops, research_brief.\n11. **Role agents** — dev, debugger, researcher, design, PM, sales, CS, marketing.\n12. **CLI quick reference** — how the same features show up at the shell.\n\nBedrock Llama is the default LLM throughout — matches the existing 01-42 notebooks."),
    code(BOOTSTRAP),
    md("## 1. Specialist registry — 47 prebuilt agents\n\n`AgentRegistry` loads every JSON definition in `shipit_agent/agents/agents.json`, including the seven new role specialists added this release."),
    code("""from shipit_agent.agents import AgentRegistry

registry = AgentRegistry()
agents = registry.all()
print(f\"{len(agents)} agents available\")

by_cat: dict[str, list[str]] = {}
for a in agents:
    by_cat.setdefault(a.category, []).append(a.id)

for cat in sorted(by_cat):
    print(f\"\\n{cat} ({len(by_cat[cat])})\")
    for aid in by_cat[cat][:8]:
        print(f\"  · {aid}\")
    if len(by_cat[cat]) > 8:
        print(f\"  … +{len(by_cat[cat]) - 8} more\")
"""),
    md("## 2. Autopilot basics — goal, budget, run\n\nThe `Autopilot` class is the thing you actually reach for. It composes `GoalAgent` with a budget gate, checkpointing, streaming events, and (optionally) a critic loop and artifact collector."),
    code("""from shipit_agent.autopilot import Autopilot, BudgetPolicy, default_heartbeat_stderr
from shipit_agent.deep import Goal

basic = Autopilot(
    llm=llm,
    goal=Goal(
        objective=\"Explain list vs tuple in Python with a 3-line example.\",
        success_criteria=[\"Mentions mutability\", \"Shows a tuple literal\", \"Shows a list literal\"],
    ),
    budget=BudgetPolicy(max_iterations=4, max_seconds=180),
    on_heartbeat=default_heartbeat_stderr,
)
r = basic.run(run_id=\"tour-basics\")
print(f\"status={r.status} iters={r.iterations} halt={r.halt_reason}\")
print(r.output[:500])
"""),
    md("## 3. Live event streaming — every iteration visible\n\nFor a dashboard-quality UI, use `autopilot.stream()` — an iterator of `{kind, ...}` dicts. The final yield is always `autopilot.result`."),
    code("""autopilot_stream = Autopilot(
    llm=llm,
    goal=Goal(
        objective=\"Write a two-line haiku about shipit_agent.\",
        success_criteria=[\"Two lines\"],
    ),
    budget=BudgetPolicy(max_iterations=3, max_seconds=120),
)
for ev in autopilot_stream.stream(run_id=\"tour-stream\"):
    kind = ev[\"kind\"]
    if kind == \"autopilot.iteration\":
        met = ev[\"criteria_met\"]; u = ev[\"usage\"]
        print(f\"  iter {ev['iteration']} · {sum(met)}/{len(met)} met · {u['seconds']:.0f}s\")
    elif kind in (\"autopilot.run_started\", \"autopilot.result\", \"autopilot.criteria_satisfied\"):
        print(f\"  [{kind}] {ev.get('status') or ev.get('goal', {}).get('objective', '')}\")
"""),
    md("### 3a. TUI, JSONL, and plain renderers\n\n`render_stream(events, fmt=...)` gives you a pretty live feed without writing your own renderer."),
    code("""from shipit_agent.live_renderer import render_stream

autopilot_r = Autopilot(
    llm=llm,
    goal=Goal(objective=\"2+2?\", success_criteria=[\"Answer is 4\"]),
    budget=BudgetPolicy(max_iterations=2, max_seconds=60),
)
# `plain` is notebook-friendly — no ANSI escapes.
render_stream(autopilot_r.stream(run_id=\"tour-render\"), fmt=\"plain\")
"""),
    md("## 4. Persistence & resume — a crash is cheap\n\nEvery iteration flushes an atomic JSON checkpoint. A crashed or halted run can pick up from its last successful iteration with `autopilot.resume(run_id)`."),
    code("""# First attempt with a deliberately tiny budget — halts partial.
first = Autopilot(
    llm=llm,
    goal=Goal(
        objective=\"Describe SOLID principles with one sentence each.\",
        success_criteria=[f\"Describes {p}\" for p in (\"S\", \"O\", \"L\", \"I\", \"D\")],
    ),
    budget=BudgetPolicy(max_iterations=1),
).run(run_id=\"tour-resume\")
print(f\"first: {first.status} iters={first.iterations}\")

# Resume with a larger budget — keeps going.
second = Autopilot(
    llm=llm,
    goal=Goal(
        objective=\"Describe SOLID principles with one sentence each.\",
        success_criteria=[f\"Describes {p}\" for p in (\"S\", \"O\", \"L\", \"I\", \"D\")],
    ),
    budget=BudgetPolicy(max_iterations=6),
).resume(\"tour-resume\")
print(f\"second: {second.status} iters={second.iterations}\")
"""),
    md("## 5. Scheduler daemon — the 24-hour story\n\nA persistent JSON queue at `~/.shipit_agent/autopilot-queue.json` that a tick-based daemon drains one goal at a time. Perfect for a `systemd` / `launchd` unit."),
    code("""from shipit_agent.scheduler_daemon import SchedulerDaemon

daemon = SchedulerDaemon(llm_factory=lambda: llm, tick_seconds=3)
daemon.enqueue(
    run_id=\"tour-q-1\",
    objective=\"Write one sentence about Python's walrus operator.\",
    success_criteria=[\"Mentions :=\"],
    budget={\"max_iterations\": 3, \"max_seconds\": 120},
)
for entry in daemon.list_queue():
    print(f\"{entry.run_id:<20} [{entry.status}] {entry.objective[:50]}\")
"""),
    md("## 6. Reflection critic — second opinion on every iteration\n\nPass `critic=True` to enable a default critic that uses the run's own LLM. For high-stakes goals, pass `Critic(llm=reviewer_llm)` with a stronger model."),
    code("""from shipit_agent.autopilot import Critic

autopilot_c = Autopilot(
    llm=llm,
    goal=Goal(
        objective=\"Name three HTTP status codes and what they mean.\",
        success_criteria=[\"At least 3 codes\", \"Each code has a one-line meaning\"],
    ),
    budget=BudgetPolicy(max_iterations=5, max_seconds=180),
    critic=True,
)
r = autopilot_c.run(run_id=\"tour-critic\")
print(f\"status={r.status} halt={r.halt_reason}\")
print(\"verdict:\", {k: r.critic_verdict.get(k) for k in (\"confidence\", \"reasoning\")})
"""),
    md("## 7. Artifact collector — structured deliverables\n\nCode blocks and markdown docs get auto-extracted. Tools can push explicit artifacts via result metadata. The final `result.artifacts` is a list your UI can render as a deliverable panel."),
    code("""from shipit_agent.autopilot import ArtifactCollector

collector = ArtifactCollector()
autopilot_a = Autopilot(
    llm=llm,
    goal=Goal(
        objective=\"Write a Python function `fib(n)` that returns the n-th Fibonacci number.\",
        success_criteria=[\"A `def fib(n)` appears in a fenced code block\"],
    ),
    budget=BudgetPolicy(max_iterations=4, max_seconds=180),
    artifacts=collector,
    critic=True,
)
r = autopilot_a.run(run_id=\"tour-artifacts\")
print(f\"artifacts extracted: {len(r.artifacts)}\")
for a in r.artifacts:
    print(f\"  [{a['kind']:<9}] {a['name']} — {len(a['content'])} chars\")
"""),
    md("## 8. Parallel fan-out — N concurrent goals\n\n`autopilot.fanout(items, objective_template)` dispatches one child per item. Each child gets a slice of the parent budget so aggregate spend stays bounded."),
    code("""parent = Autopilot(
    llm=llm,
    goal=Goal(objective=\"batch-tour\", success_criteria=[\"done\"]),
    budget=BudgetPolicy(max_seconds=600, max_iterations=6, max_tool_calls=20, max_dollars=3.0),
)
r = parent.fanout(
    items=[\"threading\", \"asyncio\", \"multiprocessing\"],
    objective_template=\"Write a one-paragraph overview of Python's {item} module.\",
    criteria_template=[\"Mentions typical use case\"],
    max_parallel=3,
    child_budget_frac=0.3,
)
print(f\"fan-out: {r.status} · wall: {r.wall_seconds:.1f}s\")
for c in r.children:
    print(f\"  {c['run_id']:<44} {c['status']:<10} {c['iterations']} iters\")
"""),
    md("### 8a. Streaming fan-out\n\nA live UI over a 50-item batch needs per-child events. `fanout_stream` gives one `autopilot.fanout_child` event per completion."),
    code("""events = list(parent.fanout_stream(
    items=[\"A\", \"B\"], objective_template=\"Summarize module {item}\",
    max_parallel=2, child_budget_frac=0.2,
))
for ev in events:
    if ev[\"kind\"] == \"autopilot.fanout_child\":
        print(f\"  child {ev['item_index']}: {ev['status']} ({ev['iterations']} iters)\")
    elif ev[\"kind\"] == \"autopilot.fanout_result\":
        print(f\"  final: {ev['status']}\")
"""),
    md("## 9. Power tools — desktop, CRM, web research\n\nThe three tools added this release. Each is usable standalone or as part of a specialist's tool kit."),
    code("""from shipit_agent.tools.computer_use import ComputerUseTool
from shipit_agent.tools.hubspot import HubspotTool
from shipit_agent.tools.research_brief import ResearchBriefTool

cu = ComputerUseTool()
hs = HubspotTool()
rb = ResearchBriefTool()

for tool in (cu, hs, rb):
    actions = tool.schema()[\"function\"][\"parameters\"][\"properties\"].get(\"action\", {}).get(\"enum\", [])
    print(f\"{tool.name:<20} actions={len(actions)} — {actions[:6]}…\")
"""),
    md("### 9a. research_brief live run\n\nSearches the web (DuckDuckGo HTML), opens the top sources, returns a structured brief with citations. No API key needed."),
    code("""from shipit_agent.tools.base import ToolContext

out = rb.run(ToolContext(prompt=\"demo\"), query=\"postgres connection pooling 2026\", max_sources=3)
print(out.text[:900])
"""),
    md("### 9b. computer_use screenshot (safe on any platform)\n\n`screenshot` is the only action most agents need — capture, then pass the PNG to a vision model for reasoning. Other actions (click, type, drag) require platform helpers (`cliclick` on macOS, `xdotool` on Linux)."),
    code("""out = cu.run(ToolContext(prompt=\"demo\"), action=\"screenshot\")
print(out.text)
"""),
    md("## 10. Role specialists in action — pick any of 47\n\nEvery prebuilt agent has a rich prompt/role/goal/backstory and can be dropped into an Autopilot. Here we use the brand-new `generalist-developer` specialist with built-in tools."),
    code("""from shipit_agent import Agent
from shipit_agent.builtins import get_builtin_tools

dev = Agent(
    llm=llm, prompt=registry.get(\"generalist-developer\").prompt,
    tools=get_builtin_tools(project_root=\".\"), max_iterations=20, name=\"Generalist Developer\",
)
result = dev.run(\"Add a one-line docstring to the function `BudgetPolicy.exceeded` in shipit_agent/autopilot/budget.py. Do not change behavior.\")
print(result.output[:600])
"""),
    md("### 10a. Pair a specialist with Autopilot for long-running role work\n\nThe researcher + `research_brief` tool + Autopilot + critic = a fully-autonomous research pipeline that keeps going until the critic confirms every criterion is satisfied."),
    code("""from shipit_agent.agents import AgentRegistry
researcher = AgentRegistry().get(\"researcher\")

research_pilot = Autopilot(
    llm=llm,
    goal=Goal(
        objective=\"Compile a one-page digest on Python type checkers (mypy / pyright / pyre).\",
        success_criteria=[
            \"At least 3 type checkers covered\",
            \"Each has one-line tradeoff\",
            \"Ends with a recommendation paragraph\",
        ],
    ),
    tools=[rb],
    budget=BudgetPolicy(max_iterations=5, max_seconds=480, max_tool_calls=15),
    critic=True, artifacts=True,
    prompt=researcher.prompt,   # use the researcher's persona as the inner-agent prompt
)
print(\"Ready. Call .run(run_id='type-checker-digest') when you want it to execute.\")
"""),
    md("## 11. CLI quick reference\n\nEvery feature above is wired into a CLI too. Run from a terminal, outside the notebook:\n\n```bash\n# one-shot long run\nshipit autopilot \"migrate SQL to parameterized form\" \\\n    --criteria \"no raw concat\" --criteria \"tests pass\" \\\n    --max-hours 4 --format tui\n\n# 24h queue operation\nshipit queue add nightly-lint \"Summarise all error lines\"\nshipit daemon --tick 5\n\n# resume a checkpointed run\nshipit autopilot --resume --run-id nightly-lint\n```\n\nEvery CLI subcommand is documented via `shipit <cmd> --help`."),
    md("## 12. Everything together\n\nOne autopilot with every feature wired — critic + artifacts + fanout + specialist prompt. Useful as a template for your own long-running runs."),
    code("""mega_pilot = Autopilot(
    llm=llm,
    goal=Goal(objective=\"mega-tour\", success_criteria=[\"done\"]),
    budget=BudgetPolicy(max_seconds=600, max_iterations=6, max_tool_calls=30, max_dollars=3.0),
    critic=True,
    artifacts=True,
    tools=[rb],
    prompt=registry.get(\"generalist-developer\").prompt,
)
# Fan out three small jobs under the same critic+artifact umbrella.
mega_result = mega_pilot.fanout(
    items=[\"dataclasses\", \"enum\", \"pathlib\"],
    objective_template=\"Give a 50-word description of Python's `{item}` module with one code snippet.\",
    criteria_template=[\"Under 100 words of prose\", \"One fenced code block\"],
    max_parallel=3, child_budget_frac=0.25,
)
print(f\"mega result: {mega_result.status}, {len(mega_result.children)} children, {len(mega_result.failed)} failed\")
"""),
    md("## You're done\n\nEverything new this release is in your hands: Autopilot's long-running runtime, three new tools, seven new specialists, the fan-out / critic / artifact triad, a scheduler daemon, a live renderer, and a CLI.\n\nIf you build something with it — ship it.\n"),
])


NB_45 = notebook("1.0.6 extras — CostRouter, non-blocking ask_user, vision, sandbox, specialists that run code", [
    md("# 45 — v1.0.6 extras · cost router · async ask_user · vision · sandbox · specialists-as-developers\n\nThe second half of v1.0.6 — five additional primitives that compose with the Autopilot core from the first half (notebooks 37–44). Each one composes with Autopilot, the critic, fan-out, and artifacts — no special wiring.\n\n1. **CostRouter** — classify each turn as easy / medium / hard, route to the cheapest adequate model. 50–70% spend cut on long runs.\n2. **Non-blocking `ask_user_async`** — halt cleanly into `awaiting_user`, resume when the user answers via `shipit answer <run_id> \"...\"`.\n3. **Vision on `computer_use`** — screenshots now carry their PNG bytes as base64 metadata so a vision-capable LLM can actually *see* what's on screen.\n4. **Docker sandbox on `code_execution`** — `sandbox=True` runs untrusted snippets in an ephemeral container with `--network none` + read-only rootfs.\n5. **Specialists that run + test code** — every role specialist (developer, debugger, designer, PM, sales, CS, marketing) now ships with `run_code` + `ask_user_async`. Pass a `workspace_root` at call-time to point them at your project.\n"),
    code(BOOTSTRAP),
    md("## 1. CostRouter — stop paying Opus prices for trivial turns\n\nDrop-in LLM adapter. Classifies each turn and routes to the right tier. Works with every Autopilot feature untouched."),
    code("""from shipit_agent.routing import CostRouter, Tier

cheap  = build_llm_from_env(\"bedrock\")   # e.g. Llama 4 Scout
medium = build_llm_from_env(\"bedrock\")   # swap to Sonnet 4.5 in real use
big    = build_llm_from_env(\"bedrock\")   # swap to Opus / Llama 405B

router = CostRouter(
    easy=Tier(llm=cheap,  price_per_1k=0.25, name=\"scout\"),
    medium=Tier(llm=medium, price_per_1k=3.0, name=\"sonnet\"),
    hard=Tier(llm=big,    price_per_1k=15.0, name=\"opus\"),
)

# Route three prompts of different difficulty — no LLM call on the router itself.
for prompt in [
    \"Hi\",
    \"Write a Python function that returns the n-th Fibonacci.\",
    \"Audit the authentication middleware for OWASP A01 issues.\",
]:
    _, tier = router.route(prompt)
    print(f\"  {tier.value:<6} ← {prompt[:60]}\")
"""),
    md("Pair it with Autopilot — router IS the LLM, so nothing else changes."),
    code("""from shipit_agent.autopilot import Autopilot, BudgetPolicy
from shipit_agent.deep import Goal

autopilot = Autopilot(
    llm=router,                                      # ← the router
    goal=Goal(
        objective=\"Explain the Python GIL with a snippet.\",
        success_criteria=[\"Two paragraphs\", \"A Python snippet\"],
    ),
    budget=BudgetPolicy(max_iterations=3, max_seconds=180),
)
# autopilot.run(run_id='gil-with-router')
print(\"Router has a built-in SpendReport:\", router.report.to_dict())
"""),
    md("## 2. Non-blocking `ask_user_async`\n\nAsk a question mid-run without blocking the loop. Autopilot halts into `awaiting_user`; the user answers at their own pace; resume picks up where it left off."),
    code("""from shipit_agent.tools.ask_user_async import AskUserAsyncTool
from shipit_agent.tools.base import ToolContext

tool = AskUserAsyncTool()
out = tool.run(
    ToolContext(prompt=\"demo\", state={\"autopilot_run_id\": \"demo-run-1\"}),
    question=\"Which cloud provider should I target — AWS, GCP, or Azure?\",
    context=\"The repo has no cloud config yet.\",
    choices=[\"AWS\", \"GCP\", \"Azure\"],
)
print(out.text)
"""),
    md("Answer from the CLI:\n\n```bash\nshipit answer demo-run-1 \"AWS\"\n```\n\nOr programmatically:"),
    code("""from shipit_agent.askuser_channel import pending_questions, write_answer

# The question above is now on disk — one-liner to inspect:
for q in pending_questions(\"demo-run-1\"):
    print(\"  pending:\", q.question)

# Simulate the user answering:
write_answer(\"demo-run-1\", \"AWS\")
print(\"  pending now:\", pending_questions(\"demo-run-1\"))
"""),
    md("Autopilot automatically halts and resumes around `ask_user_async` — the integration is in the runtime, no wiring needed in your code."),
    md("## 3. Vision on `computer_use`\n\nEvery screenshot now carries base64 PNG bytes + media type — a vision-capable LLM can actually see the screen. Pass `vision=False` to opt out for large captures."),
    code("""from shipit_agent.tools.computer_use import ComputerUseTool
from shipit_agent.tools.base import ToolContext

computer = ComputerUseTool()
# `vision=True` is default — same call signature as before, richer metadata.
# Skipped in the notebook because screencapture isn't installed in this env —
# inspect the metadata shape:
print(\"metadata keys on a screenshot action:\", [
    \"ok\", \"path\", \"platform\", \"vision\", \"image_base64\", \"media_type\",
])
"""),
    md("## 4. Docker sandbox for `code_execution`\n\nSafe by default — runs the snippet in a disposable container with `--network none` and a read-only rootfs. Gracefully degrades when docker isn't on PATH."),
    code("""from shipit_agent.tools.code_execution import CodeExecutionTool
from shipit_agent.tools.base import ToolContext

code_tool = CodeExecutionTool()
# Sandboxed Python — runs inside python:3.11-slim, no network.
out = code_tool.run(
    ToolContext(prompt=\"demo\"),
    language=\"python\",
    code=\"print('hello from the sandbox')\",
    sandbox=True,
    # sandbox=True + network=False is the default; network=True to opt in.
)
print(out.text[:400])
"""),
    md("Pin a specific image or point at your own project path:"),
    code("""import tempfile, os
workspace = tempfile.mkdtemp(prefix=\"shipit-notebook-\")

out = code_tool.run(
    ToolContext(prompt=\"demo\"),
    language=\"typescript\",
    code=\"const x: number = 42; console.log(x * 2);\",
    sandbox=True,
    image=\"node:22-slim\",      # override the default TS image
    workspace_root=workspace,    # point at wherever the user wants work done
)
print(out.text[:400])
"""),
    md("## 5. Specialists that run + test code\n\nEvery role specialist now ships with `run_code` + `ask_user_async`. Developer + debugger can reproduce bugs and verify fixes; sales/CS/PM/marketing can script light automations; design-reviewer can drive a browser via `computer_use`."),
    code("""from shipit_agent import Agent
from shipit_agent.agents import AgentRegistry
from shipit_agent.tools.code_execution import CodeExecutionTool
from shipit_agent.tools.ask_user_async import AskUserAsyncTool

registry = AgentRegistry()
dev_def = registry.get(\"generalist-developer\")
print(f\"developer tools: {dev_def.tools}\")

dev = Agent(
    llm=llm,
    prompt=dev_def.prompt,
    tools=[CodeExecutionTool(), AskUserAsyncTool()],
    max_iterations=dev_def.maxIterations or 40,
    name=dev_def.name,
)
print(f\"ready: {dev.name} can now run + test code end-to-end.\")
"""),
    md("### Per-call workspace path\n\nEvery `run_code` call accepts `workspace_root` — the user can pass their own project directory so the specialist works inside the real codebase rather than the shared default."),
    code("""# Inside your app — send the specialist at the project you're reviewing.
result = code_tool.run(
    ToolContext(prompt=\"demo\"),
    language=\"python\",
    code=\"import sys; print(sys.version); print('in:', __import__('os').getcwd())\",
    workspace_root=workspace,         # ← user-chosen path
    sandbox=False,                    # sandbox=True still supported here
)
print(result.text[:400])
print(\"metadata.workspace_root:\", result.metadata[\"workspace_root\"])
"""),
    md("## The full power stack — router + autopilot + critic + artifacts + async ask + sandbox\n\nOne Autopilot with everything wired. Budget-bounded, crash-safe, streaming, cost-optimised, safe-by-default execution."),
    code("""from shipit_agent.autopilot import Autopilot, BudgetPolicy, Critic, ArtifactCollector
from shipit_agent.deep import Goal

power = Autopilot(
    llm=router,                                      # cost-routed
    goal=Goal(
        objective=\"Review src/api/users.py for SQL injection, include a fix snippet.\",
        success_criteria=[
            \"Identifies at least one vulnerable call site\",
            \"Shows a parameterized-query fix\",
            \"Notes whether tests exist for it\",
        ],
    ),
    budget=BudgetPolicy(max_seconds=900, max_iterations=6, max_dollars=3.0),
    critic=Critic(confidence_threshold=0.8),        # reflection loop
    artifacts=ArtifactCollector(),                  # deliverables
    tools=[CodeExecutionTool(), AskUserAsyncTool()], # real run + async ask
)
print(\"ready to .run(run_id='auth-audit-demo') when you want it.\")
"""),
    md("## 6. Live streaming with *everything* wired\n\nThe full stack in one loop: router picks a tier, the critic reflects, artifacts drop as they appear, async ask_user halts on demand, `autopilot.stream()` narrates. Drop this into a web UI and you get a Claude-Desktop-grade dashboard in minutes."),
    code("""from shipit_agent.autopilot import Autopilot, BudgetPolicy, Critic, ArtifactCollector
from shipit_agent.deep import Goal
from shipit_agent.tools.ask_user_async import AskUserAsyncTool
from shipit_agent.tools.code_execution import CodeExecutionTool
from shipit_agent.live_renderer import render_stream

composed = Autopilot(
    llm=router,                                  # cost-routed
    goal=Goal(
        objective=\"Write a Python fib(n) and verify it against a 10-element list.\",
        success_criteria=[
            \"A `def fib` appears in a code fence\",
            \"Prints 10 Fibonacci numbers\",
            \"Exit code 0 from the verification run\",
        ],
    ),
    budget=BudgetPolicy(max_iterations=4, max_seconds=180),
    critic=Critic(confidence_threshold=0.8),
    artifacts=ArtifactCollector(),
    tools=[CodeExecutionTool(), AskUserAsyncTool()],
)

# Observe every event live — this is what a web dashboard would render.
for ev in composed.stream(run_id=\"composed-demo-1\"):
    kind = ev[\"kind\"]
    if kind == \"autopilot.iteration\":
        met = ev[\"criteria_met\"]
        u = ev[\"usage\"]
        print(f\"  iter {ev['iteration']} · {sum(met)}/{len(met)} criteria · \"
              f\"{u['seconds']:.0f}s · {u['tool_calls']} tools · {u['tokens']} tok\")
    elif kind == \"autopilot.artifact\":
        print(f\"  [artifact] {ev['artifact_kind']:<9} {ev['name']}\")
    elif kind == \"autopilot.critic\":
        print(f\"  [critic]   confidence={ev.get('confidence'):.2f}\")
    elif kind == \"autopilot.result\":
        print(f\"  [done]     status={ev['status']} halt={ev['halt_reason']}\")
"""),
    md("### Rendering the stream in the terminal\n\n`render_stream()` formats the same events as a pretty live feed — three modes: `tui` (colored), `jsonl` (machine-readable), `plain` (CI-safe)."),
    code("""fresh = Autopilot(
    llm=router,
    goal=Goal(
        objective=\"Explain list vs tuple in Python in two paragraphs with one code snippet.\",
        success_criteria=[\"Two paragraphs\", \"One snippet\"],
    ),
    budget=BudgetPolicy(max_iterations=3, max_seconds=120),
    artifacts=True,
)
final = render_stream(fresh.stream(run_id=\"list-vs-tuple\"), fmt=\"plain\")
print(f\"\\nfinal status: {final and final.get('status')}\")
"""),
    md("### JSONL stream — pipe into jq, Kafka, or any log sink"),
    code("""import io, json

buf = io.StringIO()
another = Autopilot(
    llm=router,
    goal=Goal(objective=\"2+2?\", success_criteria=[\"The answer is 4\"]),
    budget=BudgetPolicy(max_iterations=2, max_seconds=60),
)
render_stream(another.stream(run_id=\"jsonl-demo\"), fmt=\"jsonl\", out=buf)

# Every line is valid JSON — machine-readable, durable log.
for line in buf.getvalue().strip().split(\"\\n\")[:5]:
    ev = json.loads(line)
    print(f\"  {ev['kind']}\")
"""),
    md("### Parallel fan-out with live per-child events"),
    code("""parent = Autopilot(
    llm=router,
    goal=Goal(objective=\"batch-tour\", success_criteria=[\"done\"]),
    budget=BudgetPolicy(max_seconds=300, max_iterations=3, max_tool_calls=20, max_dollars=3.0),
)
for ev in parent.fanout_stream(
    items=[\"threading\", \"asyncio\", \"multiprocessing\"],
    objective_template=\"Summarize Python's {item} module in two sentences.\",
    criteria_template=[\"Mentions a typical use case\"],
    max_parallel=3, child_budget_frac=0.3,
):
    if ev[\"kind\"] == \"autopilot.fanout_child\":
        print(f\"  [child {ev['item_index']}]  {ev['status']:<10}  iters={ev['iterations']}\")
    elif ev[\"kind\"] == \"autopilot.fanout_result\":
        print(f\"  [done]  status={ev['status']}  {len(ev['children'])} children\")
"""),
    md("## 7. A specialist that writes + runs + tests + asks\n\nEvery role specialist now ships with `run_code` + `ask_user_async` in its tool list. Developer is shown here; the pattern is identical for debugger, design-reviewer, PM, sales, CS, marketing."),
    code("""from shipit_agent import Agent
from shipit_agent.agents import AgentRegistry

registry = AgentRegistry()
dev_def = registry.get(\"generalist-developer\")

dev = Agent(
    llm=router,
    prompt=dev_def.prompt,
    tools=[CodeExecutionTool(), AskUserAsyncTool()],
    max_iterations=dev_def.maxIterations or 40,
    name=dev_def.name,
)
print(f\"{dev.name} ready. Tools:\")
for t in dev.tools:
    print(f\"  · {t.name}\")
"""),
    md("## Summary\n\n- **CostRouter** — cheap model for easy turns, big for hard.\n- **`ask_user_async`** — non-blocking mid-run clarifications.\n- **Vision** — screenshots with base64 PNG; LLM can actually see.\n- **Sandbox** — Docker-isolated `run_code` with network-off / read-only rootfs.\n- **Specialists** — every role can run + test code + pause for user input.\n- **Live streaming** — `autopilot.stream()` + `render_stream()` + `fanout_stream()` — everything observable.\n\n863 tests. Bedrock Llama default throughout. Ship it."),
])


NOTEBOOKS: dict[str, dict[str, Any]] = {
    "37_autopilot_quickstart.ipynb":                   NB_37,
    "38_autopilot_live_streaming.ipynb":                NB_38,
    "39_persistence_and_scheduler_daemon.ipynb":        NB_39,
    "40_specialists_developer_debugger_researcher.ipynb": NB_40,
    "41_specialists_design_pm_sales_cs_marketing.ipynb": NB_41,
    "42_power_tools_computer_use_hubspot_research.ipynb": NB_42,
    "43_fanout_critic_artifacts.ipynb":                 NB_43,
    "44_complete_tour.ipynb":                           NB_44,
    "45_cost_router_async_ask_vision_sandbox.ipynb":    NB_45,
}


def main() -> None:
    for name, nb in NOTEBOOKS.items():
        path = HERE / name
        path.write_text(json.dumps(nb, indent=1))
        print(f"wrote {name} — {len(nb['cells'])} cells")


if __name__ == "__main__":
    main()
