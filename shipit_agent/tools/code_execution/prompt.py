from __future__ import annotations

CODE_EXECUTION_PROMPT = """

## run_code
Execute code in a local isolated subprocess workspace. Supports Python and shell scripts.

**When to use:**
- Calculations, data parsing, transformation, or validation are easier expressed in code than in prose
- The user asks for script execution, data processing, or generated machine-readable output
- You need deterministic local computation (math, JSON parsing, CSV processing, API calls)
- Testing a code snippet before including it in a file
- Generating structured output (JSON, CSV, tables) from raw data

**Decision tree:**
1. Simple shell command? → use `bash` instead
2. File read/write/edit? → use dedicated file tools instead
3. Data processing, math, or complex logic? → `run_code` (this tool)
4. Need to install a package first? → `bash` for install, then `run_code`

**Rules:**
- Prefer Python for structured data work, parsing, and computation
- Prefer shell for filesystem-oriented commands and system checks
- Keep execution bounded and purposeful — avoid infinite loops or unbounded recursion
- Return stdout, stderr, and exit status clearly
- Save generated files only inside the configured execution workspace
- Do not use this for operations that have dedicated tools (file read/write/edit, grep, glob)
""".strip()
