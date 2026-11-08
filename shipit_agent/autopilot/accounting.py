"""Autopilot's per-iteration accounting: tool calls, tokens, dollars and final status."""

from __future__ import annotations

from typing import Any

from .events import looks_like_tool_event
from .pricing import _lookup_dollars


class _AutopilotAccounting:
    """Autopilot's per-iteration accounting: tool calls, tokens, dollars and final status."""

    @staticmethod
    def _count_tool_calls(result: Any) -> int:
        meta = getattr(result, "metadata", None)
        if isinstance(meta, dict) and isinstance(meta.get("tool_calls"), int):
            return meta["tool_calls"]
        for attr in ("step_outputs", "steps", "events"):
            items = getattr(result, attr, None)
            if items is not None:
                try:
                    return sum(1 for i in items if looks_like_tool_event(i))
                except Exception:
                    continue
        return 0

    @staticmethod
    def _count_tokens(result: Any) -> int:
        meta = getattr(result, "metadata", None)
        if isinstance(meta, dict):
            usage = meta.get("usage")
            if isinstance(usage, dict):
                total = usage.get("total_tokens")
                if isinstance(total, int):
                    return total
                return int(usage.get("prompt_tokens", 0)) + int(
                    usage.get("completion_tokens", 0)
                )
        return 0

    def _count_dollars(self, result: Any, iteration_tokens: int) -> float:
        """Best-effort dollar attribution for one iteration.

        Order of preference:
          1. An explicit :class:`CostTracker` was passed — delegate to it.
          2. Result carries ``metadata.cost_usd`` — trust the provider.
          3. Result has a model name + token counts — look up pricing.
          4. Fall back to a coarse $/1k estimate from token counts.
        """
        if not self.track_dollars:
            return 0.0

        meta = getattr(result, "metadata", None) or {}
        if isinstance(meta, dict):
            explicit = meta.get("cost_usd")
            if isinstance(explicit, (int, float)):
                return float(explicit)

        # Attempt pricing-table lookup for known models.
        model = None
        if isinstance(meta, dict):
            model = meta.get("model") or meta.get("model_name")
        usage = meta.get("usage") if isinstance(meta, dict) else None
        input_tok = 0
        output_tok = 0
        if isinstance(usage, dict):
            input_tok = int(
                usage.get("prompt_tokens") or usage.get("input_tokens") or 0
            )
            output_tok = int(
                usage.get("completion_tokens") or usage.get("output_tokens") or 0
            )

        if model and (input_tok or output_tok):
            dollars = _lookup_dollars(model, input_tok, output_tok)
            if dollars > 0:
                return dollars

        # Fallback: a very rough blended $0.002 / 1k tokens estimate. Good
        # enough to keep the dollar counter non-zero for providers we don't
        # have pricing for — better than silently reporting $0 forever.
        if iteration_tokens and model:
            return iteration_tokens * 0.002 / 1000.0
        return 0.0

    @staticmethod
    def _classify_status(criteria_met: list[bool]) -> str:
        if criteria_met and all(criteria_met):
            return "completed"
        if criteria_met and any(criteria_met):
            return "partial"
        return "halted"
