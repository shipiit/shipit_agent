from __future__ import annotations

CODE_EXECUTION_PROMPT = """

## run_code
Execute code in a local isolated subprocess workspace.

**When to use:**
- Calculations, parsing, transformation, or validation are easier in code
- The user asks for script execution or generated machine-readable output
- You need deterministic local computation instead of reasoning in prose

**Rules:**
- Prefer Python for structured data work and shell for filesystem-oriented commands
- Keep execution bounded and purposeful
- Return stdout, stderr, and exit status clearly
- Save generated files only inside the configured execution workspace
""".strip()
