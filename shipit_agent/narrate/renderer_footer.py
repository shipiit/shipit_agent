"""The transcript's footer: tokens, cost and model, right-aligned."""

from __future__ import annotations

from typing import Any

from .terminal import _terminal_width


class RendererFooterMixin:
    """The footer line of :class:`~shipit_agent.narrate.renderer.NarratorRenderer`."""

    _acc: Any
    _cost_tracker: Any
    _model: str | None

    def _footer(self) -> str:
        """``18,240 tokens · $0.12 · claude-opus-5``, right-aligned and dim."""
        usage = self._acc.usage or {}
        tokens = int(usage.get("total_tokens") or 0)
        if not tokens:
            tokens = int(usage.get("prompt_tokens") or 0) + int(
                usage.get("completion_tokens") or 0
            )
        parts: list[str] = []
        if tokens:
            parts.append(f"{tokens:,} tokens")
        cost = self._cost()
        if cost is not None:
            parts.append(f"${cost:,.2f}" if cost >= 0.01 else f"${cost:.4f}")
        if self._model:
            parts.append(self._model)
        if not parts:
            return ""
        text = self._sep().join(parts)
        pad = max(0, _terminal_width() - len(text) - 2)
        return " " * pad + self._c("dim", text)

    def _cost(self) -> float | None:
        """Run cost in USD, when a tracker was supplied and knows the model."""
        tracker = self._cost_tracker
        if tracker is None:
            return None
        usage = self._acc.usage or {}
        try:
            if self._model:
                return float(
                    tracker.calculate_cost(
                        model=self._model,
                        input_tokens=int(usage.get("prompt_tokens") or 0),
                        output_tokens=int(usage.get("completion_tokens") or 0),
                    )
                )
            return float(tracker.total_cost())
        except Exception:
            # A missing price or an unexpected tracker shape must never take
            # the transcript down — just omit the dollar figure.
            return None
