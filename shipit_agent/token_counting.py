"""Real, per-model token counts — with a safe fall-back to the estimate.

The compaction trigger and the fixed-prefix accounting want to know how many
tokens a piece of text will really cost *this* model, not a ``chars/4`` guess
that is off by a model- and content-specific factor. shipit already runs on
LiteLLM, whose ``token_counter`` carries the real tokenizer for the OpenAI and
Anthropic families and a sensible default for the rest — so the real number is
already available at no network cost.

This module wraps it with three guarantees:

* **Never raises.** A missing tokenizer, an unknown model, or a LiteLLM import
  error falls back to :func:`shipit_agent.compaction.estimate_tokens` (the
  ``chars/4`` heuristic). Token counting must never be able to take a run down.
* **Cheap and cached.** Tokenizing the same fixed prefix on every step would be
  wasteful, so results are memoised by ``(model, text)`` with a bounded LRU.
* **Honest about approximation.** For a model LiteLLM has no exact tokenizer for
  (many Bedrock / self-hosted ids), the count is an approximation — good enough
  for a cold start, and the ``TokenCalibrator`` then corrects it against the
  provider's *actually reported* ``prompt_tokens``, which is the real ground
  truth no local tokenizer can beat.

So the accurate-from-turn-one path is: **real count here → calibrator refines**.
"""
from __future__ import annotations

from functools import lru_cache

__all__ = ["count_tokens", "count_message_tokens", "real_counting_available"]

#: Tokenizer to assume when the caller names no model. cl100k-based; a
#: reasonable default that LiteLLM also falls back to for unknown ids.
_DEFAULT_MODEL = "gpt-4o"


def real_counting_available() -> bool:
    """True when LiteLLM's token counter can be used at all."""
    try:
        import litellm  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


@lru_cache(maxsize=2048)
def _litellm_count(model: str, text: str) -> int | None:
    try:
        import litellm

        return int(litellm.token_counter(model=model, text=text))
    except Exception:  # noqa: BLE001 — any failure means "use the estimate"
        return None


def count_tokens(text: object, model: str | None = None) -> int:
    """Real token count of *text* for *model*, or the ``chars/4`` estimate.

    Accepts any value; non-strings are stringified (a tool schema is often a
    dict). Empty input is 0.
    """
    if not text:
        return 0
    if not isinstance(text, str):
        try:
            import json

            text = json.dumps(text, default=str)
        except Exception:  # noqa: BLE001
            text = str(text)
    exact = _litellm_count(model or _DEFAULT_MODEL, text)
    if exact is not None:
        return exact
    from shipit_agent.compaction import estimate_tokens

    return estimate_tokens(text)


def count_message_tokens(messages, model: str | None = None) -> int:
    """Real token count across a message list, summing per-message content.

    Block-shaped (multimodal) content is counted as its text parts plus the
    same flat per-image allowance compaction uses, since a tokenizer cannot see
    the pixels.
    """
    total = 0
    for message in messages or []:
        content = getattr(message, "content", None)
        if isinstance(content, list):
            from shipit_agent.compaction import estimate_tokens

            total += estimate_tokens(content)  # already text+image aware
        else:
            total += count_tokens(content or "", model)
    return total
