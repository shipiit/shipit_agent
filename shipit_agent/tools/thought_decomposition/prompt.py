from __future__ import annotations

THOUGHT_DECOMPOSITION_PROMPT = """

## decompose_problem
Break a complex task into a structured reasoning frame with clear dimensions, assumptions, and checkpoints.

**When to use:**
- The task is large, ambiguous, or cross-functional and needs structured breakdown
- Multiple workstreams, stakeholders, or constraints interact
- You need explicit goals, assumptions, risks, and next actions before diving into execution
- The user asks to "think through" or "break down" a complex problem

**Rules:**
- Organize the task into **clear dimensions** (e.g., technical, organizational, timeline, risk)
- Keep the output concise and actionable — not a wall of text
- Surface hidden assumptions explicitly
- Identify dependencies between workstreams
- Focus on visible reasoning artifacts: goals, assumptions, risks, checkpoints, and next actions
- Pair with `plan_task` for execution planning and `decision_matrix` for option evaluation
""".strip()
