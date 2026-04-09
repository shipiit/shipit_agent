from __future__ import annotations

DECISION_MATRIX_PROMPT = """
Compare options using explicit criteria and visible tradeoffs.

Use this when:
- the agent must choose between several approaches
- a recommendation needs transparent reasoning artifacts

Rules:
- compare options against criteria directly
- produce a recommendation with tradeoffs and a fallback option
""".strip()
