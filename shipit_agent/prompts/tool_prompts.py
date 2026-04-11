"""
Compatibility re-exports for tool prompts.

The per-tool package `prompt.py` modules are the source of truth so each tool
owns its own prompt contract. This module keeps the original centralized import
surface available for callers that still rely on `shipit_agent.prompts`.
"""

FUNCTION_TOOL_PROMPT = """
Call a direct Python function tool.

Use this when:
- a deterministic local function can solve the task directly
- code-free execution is preferable to a heavier tool or model call

Rules:
- pass only the needed arguments
- prefer these tools for stable utility operations
""".strip()
