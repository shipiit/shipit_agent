from __future__ import annotations

PLANNER_PROMPT = """
Generate an execution plan for a larger task.

Use this when:
- the task is complex, multi-stage, or ambiguous
- you need a clear ordered plan before execution

Rules:
- return concrete steps, not vague advice
- include constraints and checkpoints when they matter
""".strip()
