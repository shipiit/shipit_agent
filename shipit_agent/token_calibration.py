"""Learn the error in our token estimate and correct it, per model.

The compaction trigger runs on an *estimate* — ``len(text) // 4`` — because an
exact count needs the provider's tokenizer, which we cannot assume is
installed. That estimate is systematically wrong in a model-specific,
content-specific way: dense JSON tool output runs ~2.5–3 characters per token,
English prose ~4, and every provider tokenizes differently. A static divisor is
therefore too low for tool-heavy runs — which is precisely the shape that most
needs compacting — so the trigger fires late and the provider rejects the
overflow.

Every completion already tells us the truth: ``usage.prompt_tokens`` (plus the
prompt-cache counters) is the real size of what we sent. This module compares
that truth to what we estimated and keeps a running correction factor per
model, so the *next* trigger decision uses a calibrated number.

Three rules make the correction safe rather than merely clever:

* **Keyed by model.** Gemma, Claude and GPT tokenize differently; one model's
  ratio must never leak onto another (the same class of bug as an unkeyed
  cache).
* **Asymmetric clamp.** The factor may raise the estimate freely but never
  lower it below the raw ``chars/4`` (floor at ``1.0``). Over-estimating
  compacts a little early and the run survives; under-estimating overflows and
  the run dies. When unsure, err toward the survivable direction.
* **Warm-up.** The factor stays at ``1.0`` until a minimum number of samples
  have been seen, so one early outlier cannot move the trigger.

The correction never touches :func:`shipit_agent.compaction.estimate_tokens`
itself — that stays a pure function. Callers multiply by :meth:`factor` at the
decision point, so the estimate used for the snapshot and the estimate used for
the trigger are always the same number.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Dict

__all__ = ["TokenCalibrator"]

#: EMA weight for a new observation. Low enough that the factor is stable across
#: turns, high enough that it tracks a genuine shift within a long conversation.
DEFAULT_ALPHA = 0.25

#: Observations required before the factor is allowed to leave ``1.0``. One
#: sample is noise; a handful is a trend.
DEFAULT_MIN_SAMPLES = 3

#: Hard ceiling on the correction. A ratio above this is a broken usage report
#: (or a caller dividing the wrong two numbers), not real tokenizer drift, and
#: must not be allowed to force pathological early compaction.
DEFAULT_MAX_FACTOR = 4.0


@dataclass
class _ModelStat:
    ratio: float = 1.0
    samples: int = 0


@dataclass
class TokenCalibrator:
    """Per-model EMA of ``actual_tokens / estimated_tokens``.

    Thread-safe: a runtime may complete on more than one thread, and the
    correction is shared process state.
    """

    alpha: float = DEFAULT_ALPHA
    min_samples: int = DEFAULT_MIN_SAMPLES
    max_factor: float = DEFAULT_MAX_FACTOR
    _stats: Dict[str, _ModelStat] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def observe(self, model: str | None, estimated: int, actual: int) -> None:
        """Record one (estimated, actual) pair for *model*.

        ``estimated`` must be the SAME full-context number the trigger uses —
        system prompt + tool schemas + messages — not messages alone, or the
        ratio measures how many tools are attached rather than tokenizer error.
        ``actual`` must include the prompt-cache counters, because on a cache
        hit ``prompt_tokens`` alone is far below what was really sent and would
        drag the factor down — the exact failure this exists to prevent.
        """
        if estimated <= 0 or actual <= 0:
            return
        observed = actual / estimated
        # Cap a single observation so one broken usage report cannot blow up the
        # EMA; the warm-up and floor handle the rest.
        observed = min(observed, self.max_factor)
        key = self._key(model)
        with self._lock:
            stat = self._stats.get(key)
            if stat is None:
                stat = _ModelStat(ratio=observed, samples=1)
                self._stats[key] = stat
                return
            stat.ratio = (1 - self.alpha) * stat.ratio + self.alpha * observed
            stat.samples += 1

    def factor(self, model: str | None) -> float:
        """The multiplier to apply to an estimate for *model*.

        ``1.0`` until warm-up completes, then the learned ratio clamped to
        ``[1.0, max_factor]`` — never below the raw estimate.
        """
        key = self._key(model)
        with self._lock:
            stat = self._stats.get(key)
            if stat is None or stat.samples < self.min_samples:
                return 1.0
            return max(1.0, min(stat.ratio, self.max_factor))

    def calibrated(self, model: str | None, estimated: int) -> int:
        """*estimated* scaled by the current factor for *model*."""
        return int(estimated * self.factor(model))

    def to_dict(self) -> dict[str, dict[str, float | int]]:
        """Serializable calibration state for durable chat sessions."""
        with self._lock:
            return {
                key: {"ratio": stat.ratio, "samples": stat.samples}
                for key, stat in self._stats.items()
            }

    def restore(self, value: object) -> None:
        """Merge previously persisted model statistics, ignoring bad data."""
        if not isinstance(value, dict):
            return
        restored: dict[str, _ModelStat] = {}
        for key, raw in value.items():
            if not isinstance(key, str) or not isinstance(raw, dict):
                continue
            try:
                ratio = max(1.0, min(float(raw.get("ratio", 1.0)), self.max_factor))
                samples = max(0, int(raw.get("samples", 0)))
            except (TypeError, ValueError):
                continue
            restored[key] = _ModelStat(ratio=ratio, samples=samples)
        with self._lock:
            for key, stat in restored.items():
                current = self._stats.get(key)
                if current is None or stat.samples > current.samples:
                    self._stats[key] = stat

    @staticmethod
    def _key(model: str | None) -> str:
        return (model or "").strip().lower() or "_default"
