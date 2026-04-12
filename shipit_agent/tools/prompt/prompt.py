from __future__ import annotations

PROMPT_TOOL_PROMPT = """

## build_prompt
Build or refine a system prompt for another agent, workflow, or LLM call.

**When to use:**
- The user wants a better, more effective prompt for their use case
- A downstream agent or sub-agent needs clearer instructions, constraints, or behavioral guidance
- You are constructing a multi-agent workflow and need to define each agent's system prompt
- Refining an existing prompt to improve output quality, reduce hallucination, or add guardrails

**Rules:**
- Optimize for **specificity and operational clarity** — vague prompts produce vague results
- Make the prompt usable as-is without further editing
- Include: role definition, task scope, constraints, output format, and edge case handling
- Prefer structured sections (role, context, instructions, rules, output format) over free-form prose
- Test the prompt mentally: would an LLM given only this prompt know exactly what to do?
""".strip()
