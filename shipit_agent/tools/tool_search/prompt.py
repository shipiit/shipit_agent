from __future__ import annotations

TOOL_SEARCH_PROMPT = """

## tool_search
Search the current toolset to find the right tool for a task. Useful when many tools are available.

**When to use:**
- You have many tools available and are unsure which one fits the current sub-task
- The user describes a capability need (e.g., "search the web", "edit a file") and you need the right tool name
- No already loaded tool fits the task; you need another capability

**Rules:**
- Search by **task intent and capability**, not only exact tool names
- Review the returned tool descriptions before choosing — pick the most specific tool available
- Use an already loaded matching tool directly; do not search just to confirm it exists
- If no tool matches, report the missing capability or ask a focused clarification; never invent a tool or bypass source/access restrictions
- Do not search repeatedly for the same capability within one run
""".strip()
