from __future__ import annotations

MEMORY_TOOL_PROMPT = """
Store and retrieve durable memory facts.

Use this when:
- facts from the current or prior runs should be reused later
- the user shares stable preferences, constraints, or identifiers
- the agent needs to search prior stored facts

Rules:
- store concise facts, not noisy transcripts
- search memory before asking for information that may already be known
""".strip()
