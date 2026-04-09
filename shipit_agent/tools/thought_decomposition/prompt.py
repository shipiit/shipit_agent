from __future__ import annotations

THOUGHT_DECOMPOSITION_PROMPT = """
Break a complex task into a structured reasoning frame without exposing hidden chain-of-thought.

Use this when:
- the task is large, ambiguous, or cross-functional
- you need explicit workstreams, assumptions, and checkpoints

Rules:
- organize the task into clear dimensions
- keep the output concise and actionable
- focus on visible reasoning artifacts such as goals, assumptions, risks, and next actions
""".strip()
