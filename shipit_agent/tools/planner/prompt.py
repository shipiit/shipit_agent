from __future__ import annotations

PLANNER_PROMPT = """

## plan_task
Generate a structured execution plan for a complex or multi-stage task.

**When to use:**
- The task has 3+ distinct stages, dependencies, or decision points
- The scope is ambiguous and needs to be broken down before execution
- Multiple tools or approaches could apply and sequencing matters
- The user asks for a plan, roadmap, or implementation strategy

**Rules:**
- Return **concrete, ordered steps** — not vague advice or bullet-point brainstorming
- Each step should be actionable: specify what tool to use, what input to provide, what to check
- Include constraints, assumptions, and checkpoints where they matter
- Call out dependencies between steps (e.g., "step 3 requires output from step 2")
- Flag risks or decision points that may need user input before continuing
- Keep the plan scoped to what the agent can actually execute with its available tools
""".strip()
