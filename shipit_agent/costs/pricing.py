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
    "anthropic.claude-sonnet-4-20250514-v1:0": {
        "input": 3.00,
        "output": 15.00,
    },
    "anthropic.claude-haiku-4-20250514-v1:0": {
        "input": 0.80,
        "output": 4.00,
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
