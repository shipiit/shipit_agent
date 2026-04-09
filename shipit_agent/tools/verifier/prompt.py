from __future__ import annotations

VERIFIER_PROMPT = """
Verify whether content satisfies explicit criteria.

Use this when:
- you need a final quality gate before returning work
- the user asked for validation, checking, or conformance

Rules:
- verify against concrete criteria
- clearly identify missing or failed checks
""".strip()
