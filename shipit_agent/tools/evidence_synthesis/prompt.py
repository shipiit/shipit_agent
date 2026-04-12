from __future__ import annotations

EVIDENCE_SYNTHESIS_PROMPT = """

## synthesize_evidence
Combine multiple facts, observations, or data points into grounded findings with clear confidence levels.

**When to use:**
- Multiple sources of information need to be reconciled into a coherent summary
- Research, web searches, or file reads have produced scattered findings that need consolidation
- The agent needs a clear picture of what is known, what is uncertain, and what to investigate next
- Before making a recommendation, synthesize the evidence base first

**Rules:**
- Separate **facts** (observed), **inferences** (derived), **gaps** (unknown), and **recommendations** (next steps)
- Prefer concise synthesis over long free-form analysis
- Assign confidence levels: high (multiple sources agree), medium (single source), low (inferred)
- Flag contradictions between sources rather than silently picking one
- Pair with `web_search` / `grep_files` for gathering and `decision_matrix` for acting on findings
""".strip()
