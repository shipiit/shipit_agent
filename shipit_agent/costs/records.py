"""One priced LLM call, and reading token usage off any provider's response."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class CostRecord:
    """Record of a single LLM call's cost.

    Attributes:
        call_number:        Monotonically increasing call index.
        model:              Model identifier used for pricing lookup.
        input_tokens:       Number of prompt tokens.
        output_tokens:      Number of completion tokens.
        cache_read_tokens:  Tokens read from prompt cache (Anthropic).
        cache_write_tokens: Tokens written to prompt cache (Anthropic).
        cost_usd:           Computed cost in US dollars.
        timestamp:          UTC time of the call.
    """

    call_number: int
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: float
    timestamp: datetime
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dictionary."""
        return {
            "call_number": self.call_number,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "timestamp": self.timestamp.isoformat(),
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# Helper functions for extracting usage from diverse LLM responses
# ---------------------------------------------------------------------------


def _extract_usage(response: Any) -> dict[str, int] | None:
    """Best-effort extraction of token usage from an LLM response object."""
    # Pattern 1: response.usage as a dict-like object.
    if hasattr(response, "usage"):
        usage = response.usage
        if isinstance(usage, dict):
            return usage
        # Anthropic / OpenAI SDK objects expose attributes.
        if hasattr(usage, "input_tokens"):
            result: dict[str, int] = {
                "input_tokens": getattr(usage, "input_tokens", 0),
                "output_tokens": getattr(usage, "output_tokens", 0),
            }
            # Anthropic cache fields.
            for key in (
                "cache_read_input_tokens",
                "cache_creation_input_tokens",
            ):
                val = getattr(usage, key, 0)
                if val:
                    result[key] = val
            return result
        if hasattr(usage, "prompt_tokens"):
            return {
                "prompt_tokens": getattr(usage, "prompt_tokens", 0),
                "completion_tokens": getattr(usage, "completion_tokens", 0),
            }

    # Pattern 2: response.metadata["usage"].
    if hasattr(response, "metadata") and isinstance(response.metadata, dict):
        usage = response.metadata.get("usage")
        if isinstance(usage, dict):
            return usage

    # Pattern 3: shipit_agent LLMResponse with raw_response.
    if hasattr(response, "raw_response"):
        return _extract_usage(response.raw_response)

    return None


def _extract_model(response: Any) -> str | None:
    """Best-effort extraction of the model name from an LLM response."""
    if hasattr(response, "model"):
        return str(response.model)
    if hasattr(response, "metadata") and isinstance(response.metadata, dict):
        return response.metadata.get("model")
    if hasattr(response, "raw_response") and hasattr(response.raw_response, "model"):
        return str(response.raw_response.model)
    return None
