from __future__ import annotations

TOOL_SEARCH_PROMPT = """
Search the current toolset to find the right tool for a task.

Use this when:
- many tools are available and tool choice is unclear
- the agent should reason about capability selection before acting

Rules:
- search by task intent and capability, not only exact tool names
""".strip()
