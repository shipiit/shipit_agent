from __future__ import annotations

DECISION_MATRIX_PROMPT = """

## decision_matrix
Compare options using explicit criteria, weighted scoring, and visible tradeoffs.

**When to use:**
- The agent must choose between 2+ approaches, tools, technologies, or strategies
- A recommendation needs transparent reasoning — not just "I picked option A"
- The user asks for a comparison, evaluation, or pros/cons analysis
- After evidence synthesis, use this to convert findings into a decision

**Rules:**
- Define **explicit criteria** (e.g., cost, complexity, risk, time, quality) before scoring
- Compare all options against the same criteria consistently
- Produce a clear recommendation with the top choice, runner-up, and key tradeoffs
- Include a **fallback option** in case the top choice is blocked
- Keep the matrix readable: criteria as rows, options as columns
- Pair with `synthesize_evidence` for input and `plan_task` for execution of the chosen option
""".strip()
