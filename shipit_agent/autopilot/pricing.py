"""Dollar pricing lookups for Autopilot's spend accounting."""

from __future__ import annotations


def _lookup_dollars(model: str, input_tokens: int, output_tokens: int) -> float:
    """Lookup (input_tokens, output_tokens) → USD using the pricing table.

    Imported lazily because the costs module is optional — the Autopilot
    core shouldn't hard-fail just because a caller isn't interested in
    dollar tracking.
    """
    try:
        from shipit_agent.costs.pricing import MODEL_PRICING
    except Exception:  # noqa: BLE001
        return 0.0

    prices = _resolve_pricing(model, MODEL_PRICING)
    if not prices:
        return 0.0

    per_million = 1_000_000.0
    return (
        input_tokens * float(prices.get("input", 0.0)) / per_million
        + output_tokens * float(prices.get("output", 0.0)) / per_million
    )


def _resolve_pricing(
    model: str, table: dict[str, dict[str, float]]
) -> dict[str, float] | None:
    """Find a pricing row that best matches a model id.

    Handles Bedrock-style prefixes (``bedrock/anthropic.claude-…``) and
    LiteLLM-style suffixes (``openai/gpt-4o-mini``) by also checking the
    name without the leading provider segment.
    """
    if model in table:
        return table[model]
    # Strip up to two leading provider segments.
    candidate = model
    for _ in range(2):
        if "/" in candidate:
            candidate = candidate.split("/", 1)[1]
            if candidate in table:
                return table[candidate]
    # Substring match as a last resort (e.g. "claude-sonnet-4-20250514" → "claude-sonnet-4").
    for key, row in table.items():
        if key and key in model:
            return row
    return None

