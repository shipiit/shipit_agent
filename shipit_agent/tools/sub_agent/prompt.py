from __future__ import annotations

SUB_AGENT_PROMPT = """
Delegate a focused sub-task to a lightweight sub-agent.

Use this when:
- the task can be isolated cleanly
- parallel thinking or specialized summarization helps

Rules:
- keep delegated tasks narrow and concrete
- use it for bounded side work, not for replacing the main runtime
""".strip()
