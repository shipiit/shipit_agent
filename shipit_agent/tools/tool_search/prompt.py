"""What the model is told about the tool search tool: when to use it and how."""

from __future__ import annotations

TOOL_SEARCH_PROMPT = """
Find another tool by what you need it to do, when none loaded fits.
- Search by task intent and capability, not only by tool name, and pick the
  most specific match from the results.
- Use an already loaded tool directly; do not search to confirm it exists.
- If nothing matches, say which capability is missing; never invent a tool or
  get around an access restriction.
- Do not search again for the same capability in one run.
""".strip()
