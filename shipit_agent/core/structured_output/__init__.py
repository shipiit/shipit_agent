"""Structured output orchestrator — the public API for v1.0.8.

Wraps any LLM with three battle-tested strategies for getting reliable
typed output:

1. **Tool-call mode** (default for Anthropic / OpenAI / Bedrock when supported) —
   declare a tool whose input schema IS the desired output schema. The model
   "calls" the tool; we extract the args. This is the highest-fidelity path
   because it uses the model's native function-calling guard rails.

2. **JSON-prompt mode** (fallback) — append a schema-shaped instruction to
   the prompt and parse the JSON out of the response. Robust JSON extraction
   handles markdown fences, prose wrappers, trailing commas.

3. **Validation-retry loop** — when parsing or validation fails, send the
   error back into the SAME conversation (no separate "fixing" LLM) and
   try again. Retry budget configurable; conversation history grows with
   each attempt so the model sees what it got wrong.

Streaming variant yields partial parsed objects as tokens arrive.

Example::

    from pydantic import BaseModel
    from shipit_agent.core.structured_output import StructuredOutput

    class Movie(BaseModel):
        title: str
        rating: float

    so = StructuredOutput(llm=llm, schema=Movie, max_retries=2)
    movie = so.run("What's a good movie?")
    # → Movie(title='...', rating=...)

    # Streaming partial
    for partial in so.stream("What's a good movie?"):
        print(partial)  # → {} → {"title": "Inc"} → {"title": "Inception", "rating": 9.0}
"""

from __future__ import annotations

from .retry import validate_with_retry
from .spec import StructuredOutput
from .values import StructuredOutputResult

__all__ = [
    "StructuredOutput",
    "StructuredOutputResult",
    "validate_with_retry",
]
