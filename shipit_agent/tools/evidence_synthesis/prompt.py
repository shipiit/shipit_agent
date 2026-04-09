from __future__ import annotations

EVIDENCE_SYNTHESIS_PROMPT = """
Synthesize evidence into grounded findings without generating hidden reasoning traces.

Use this when:
- multiple facts or observations need to be combined
- the agent needs a clear summary of what is known, uncertain, and next

Rules:
- separate facts, inferences, gaps, and recommendations
- prefer concise synthesis over long free-form analysis
""".strip()
