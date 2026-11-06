"""How a CostTracker finds a model's prices and turns tokens into dollars."""

from __future__ import annotations

import logging

from .pricing import MODEL_ALIASES, resolve_pricing_key

# The tracker's logger, so warnings keep the name callers filter on.
logger = logging.getLogger("shipit_agent.costs.tracker")


class PricingLookupMixin:
    """Prices per million tokens, by model id, alias or prefix."""

    _pricing: dict[str, dict[str, float]]

    def calculate_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        *,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
    ) -> float:
        """Calculate cost in USD for a given token count.

        If the model is not found in the pricing table the cost is
        returned as ``0.0`` and a warning is logged.
        """
        resolved = self._resolve_model(model)
        prices = self._pricing.get(resolved)

        if prices is None:
            logger.warning("No pricing data for model '%s' — cost will be $0.00", model)
            return 0.0

        per_million = 1_000_000.0
        cost = (
            input_tokens * prices.get("input", 0.0) / per_million
            + output_tokens * prices.get("output", 0.0) / per_million
            + cache_read_tokens * prices.get("cache_read", 0.0) / per_million
            + cache_write_tokens * prices.get("cache_write", 0.0) / per_million
        )
        return cost

    def add_model(self, model_id: str, pricing: dict[str, float]) -> None:
        """Register pricing for a custom or new model.

        Args:
            model_id: The model identifier string.
            pricing:  Dict with keys like ``"input"``, ``"output"``,
                      ``"cache_read"``, ``"cache_write"`` mapping to
                      per-million-token prices in USD.
        """
        self._pricing[model_id] = pricing

    def has_pricing(self, model: str) -> bool:
        """True when *model* (or an alias or prefix of it) is in the pricing table."""
        return self._resolve_model(model) in self._pricing

    def _resolve_model(self, model: str) -> str:
        """Resolve a model id to its pricing key.

        Returns the id unchanged when nothing matches, so the caller's
        ``resolved not in self._pricing`` unknown-model check still works.
        """
        return resolve_pricing_key(model, self._pricing) or MODEL_ALIASES.get(
            model, model
        )
