from __future__ import annotations

SUB_AGENT_PROMPT = """

## sub_agent
Delegate a focused sub-task to a lightweight sub-agent with its own context.

**When to use:**
- The task can be cleanly isolated from the main workflow (e.g., summarize a document, research a topic)
- Parallel thinking would speed up the overall task
- A specialized sub-task needs focused attention without polluting the main context
- You need a second opinion or independent analysis

**Rules:**
- Keep delegated tasks **narrow, concrete, and self-contained** — include all needed context in the prompt
- Do not delegate the main task — use this for bounded side work only
- Specify clearly what output format you expect back from the sub-agent
- The sub-agent inherits the available tools but not the conversation history
- Prefer this over doing everything in sequence when sub-tasks are independent
""".strip()
