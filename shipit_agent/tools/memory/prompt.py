from __future__ import annotations

MEMORY_TOOL_PROMPT = """

## memory
Store, retrieve, and search durable memory facts that persist across agent runs.

**When to use:**
- Save stable user preferences, constraints, identifiers, or context that will be useful in future runs
- Recall prior decisions, preferences, or constraints before asking the user to repeat them
- Search for previously stored facts before starting work that depends on known context
- Track key findings, approved approaches, or domain-specific knowledge across sessions

**Rules:**
- **Search before asking** — check memory for information the user may have already provided
- Store concise, factual entries — not noisy transcripts or full conversation logs
- Use descriptive keys so facts are easy to find later
- Update or overwrite stale entries rather than creating duplicates
- Store preferences early: if the user says "always use PostgreSQL" or "deploy to us-east-1", save it
- Do not store ephemeral task details that are only relevant to the current run
""".strip()
