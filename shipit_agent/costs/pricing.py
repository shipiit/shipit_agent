"""Per-million-token pricing for supported LLM providers.

Prices are in USD per 1 million tokens.  Updated as of April 2026.
Users can override or extend via :meth:`CostTracker.add_model`.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Canonical pricing table
# ---------------------------------------------------------------------------

MODEL_PRICING: dict[str, dict[str, float]] = {
    # ── Anthropic Claude ──────────────────────────────────────────────
    "claude-opus-4-20250514": {
        "input": 15.00,
        "output": 75.00,
        "cache_read": 1.50,
        "cache_write": 18.75,
    },
    "claude-sonnet-4-20250514": {
        "input": 3.00,
        "output": 15.00,
        "cache_read": 0.30,
        "cache_write": 3.75,
    },
    "claude-haiku-4-20250514": {
        "input": 0.80,
        "output": 4.00,
        "cache_read": 0.08,
        "cache_write": 1.00,
    },
    # Aliases without dates.
    "claude-opus-4": {
        "input": 15.00,
        "output": 75.00,
        "cache_read": 1.50,
        "cache_write": 18.75,
    },
    "claude-sonnet-4": {
        "input": 3.00,
        "output": 15.00,
        "cache_read": 0.30,
        "cache_write": 3.75,
    },
    "claude-haiku-4": {
        "input": 0.80,
        "output": 4.00,
        "cache_read": 0.08,
        "cache_write": 1.00,
    },
    # ── OpenAI ────────────────────────────────────────────────────────
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4.1": {"input": 2.00, "output": 8.00},
    "gpt-4.1-mini": {"input": 0.40, "output": 1.60},
    "gpt-4.1-nano": {"input": 0.10, "output": 0.40},
    "o3": {"input": 10.00, "output": 40.00},
    "o3-mini": {"input": 1.10, "output": 4.40},
    "o4-mini": {"input": 1.10, "output": 4.40},
    # ── Google ────────────────────────────────────────────────────────
    "gemini-2.5-pro": {"input": 1.25, "output": 10.00},
    "gemini-2.5-flash": {"input": 0.15, "output": 0.60},
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    # ── Meta / Open models (via Groq / Together) ─────────────────────
    "llama-4-scout": {"input": 0.11, "output": 0.34},
    "llama-4-maverick": {"input": 0.50, "output": 0.77},
    # ── AWS Bedrock (same models, different IDs) ─────────────────────
    # Cache rates use Anthropic's standard multipliers (read 0.1×, write
    # 1.25× of input) — prompt caching is on by default for these models,
    # and entries without cache rates silently price cached tokens at $0.
    "anthropic.claude-sonnet-4-20250514-v1:0": {
        "input": 3.00,
        "output": 15.00,
        "cache_read": 0.30,
        "cache_write": 3.75,
    },
    "anthropic.claude-haiku-4-20250514-v1:0": {
        "input": 0.80,
        "output": 4.00,
        "cache_read": 0.08,
        "cache_write": 1.00,
    },
    # ── Google Gemma 4 on AWS Bedrock (bedrock-mantle) ────────────────
    # Without these, the model doing all the work reported $0.00 — and zero
    # reads as *free*, not *unknown*. Keys match after the resolver peels the
    # `bedrock-mantle/` prefix. Verify rates against the Bedrock pricing page;
    # the relative ordering matters most. (No prompt caching on Gemma.)
    "google.gemma-4-31b": {
        "input": 0.30, "output": 0.50, "cache_read": 0.075, "cache_write": 0.0,
    },
    "google.gemma-4-26b-a4b": {
        "input": 0.12, "output": 0.20, "cache_read": 0.03, "cache_write": 0.0,
    },
    "google.gemma-4-e2b": {
        "input": 0.05, "output": 0.10, "cache_read": 0.0125, "cache_write": 0.0,
    },
}

# ---------------------------------------------------------------------------
# Short aliases for convenience
# ---------------------------------------------------------------------------

MODEL_ALIASES: dict[str, str] = {
    "opus": "claude-opus-4",
    "sonnet": "claude-sonnet-4",
    "haiku": "claude-haiku-4",
    "gpt4o": "gpt-4o",
    "gpt4o-mini": "gpt-4o-mini",
}


def resolve_pricing_key(
    model: str | None, pricing: dict[str, dict[str, float]]
) -> str | None:
    """Find the pricing key for *model*, or ``None`` if nothing matches.

    A plain dict lookup is the wrong shape here, and quietly so. Real model ids
    arrive carrying vendor routing prefixes and version suffixes —
    ``bedrock/openai.gpt-oss-120b-1:0``, ``us.anthropic.claude-opus-5``,
    ``anthropic/claude-sonnet-4`` — while the table is keyed by family. An
    exact lookup misses every one of them, and a miss does not raise: the call
    is priced at $0.00, so a configured budget can never be exceeded and the
    only symptom is a log line. That failure mode is silent in exactly the
    situation the budget exists for.

    So this mirrors the matcher ``compaction.get_model_limits`` already uses,
    for the same ids:

    1. an explicit alias,
    2. an exact key,
    3. the **longest** matching key prefix — longest so ``claude-opus-4-1``
       never resolves to the shorter, differently-priced ``claude-opus-4``,
    4. failing that, peel vendor prefixes one ``/`` or ``.`` segment at a time.

    Step 4 runs only after step 3 has failed on the whole id, because model
    names legitimately contain dots: splitting eagerly would turn
    ``gemini-2.5-pro`` into ``5-pro`` and lose a match that was there.
    """
    if not model:
        return None

    def _longest_prefix(name: str) -> str | None:
        best: tuple[int, str] | None = None
        for key in pricing:
            lowered = key.lower()
            if name.startswith(lowered) and (best is None or len(lowered) > best[0]):
                best = (len(lowered), key)
        return best[1] if best else None

    aliased = MODEL_ALIASES.get(model, model)
    if aliased in pricing:
        return aliased

    normalized = str(aliased).lower()
    for key in pricing:
        if key.lower() == normalized:
            return key

    found = _longest_prefix(normalized)
    if found:
        return found

    remainder = normalized
    while True:
        cut = min(
            (remainder.index(sep) for sep in ("/", ".") if sep in remainder),
            default=-1,
        )
        if cut < 0:
            return None
        remainder = remainder[cut + 1 :]
        found = _longest_prefix(remainder)
        if found:
            return found
