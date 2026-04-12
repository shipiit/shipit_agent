from __future__ import annotations

VERIFIER_PROMPT = """

## verify_output
Verify whether content satisfies explicit criteria. Use as a quality gate before returning work.

**When to use:**
- Final check before returning generated code, text, config, or analysis to the user
- The user asked for validation, conformance checking, or completeness review
- A skill or plan specifies a verification step
- After multi-step work to confirm all requirements were met

**Rules:**
- Verify against **concrete, explicit criteria** — not vague "looks good" checks
- Structure the result as: criteria checked, pass/fail for each, and a summary verdict
- Clearly identify missing items, failed checks, or partial completions
- If verification fails, explain what needs to change — do not just say "failed"
- Prefer this tool over ad-hoc self-review when the task has stated requirements
""".strip()
