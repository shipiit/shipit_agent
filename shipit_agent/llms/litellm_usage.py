"""Reading prompt-cache usage and reasoning text off a LiteLLM response."""

from __future__ import annotations

from typing import Any


def _extract_cache_usage(usage_obj: Any) -> dict[str, int]:
    """Best-effort extraction of prompt-cache token counts from a usage object.

    LiteLLM normalises providers inconsistently, so several shapes are tried:

    * Anthropic-style attributes promoted onto ``usage``
      (``cache_read_input_tokens`` / ``cache_creation_input_tokens``),
    * OpenAI-style ``usage.prompt_tokens_details.cached_tokens``.

    The returned keys (``cache_read_input_tokens`` /
    ``cache_creation_input_tokens``) are exactly what ``CostTracker.as_hooks``
    reads, so cache reads bill at the discounted rate automatically. Returns an
    empty dict (and never raises) when no cache info is present.
    """
    out: dict[str, int] = {}
    try:
        cache_read = getattr(usage_obj, "cache_read_input_tokens", 0) or 0
        cache_creation = getattr(usage_obj, "cache_creation_input_tokens", 0) or 0
        if not cache_read:
            details = getattr(usage_obj, "prompt_tokens_details", None)
            if details is not None:
                cache_read = getattr(details, "cached_tokens", 0) or 0
        if cache_read:
            out["cache_read_input_tokens"] = int(cache_read)
        if cache_creation:
            out["cache_creation_input_tokens"] = int(cache_creation)
    except Exception:
        return {}
    return out


def _extract_reasoning(message: Any) -> str | None:
    """Pull thinking/reasoning content out of a litellm response message.

    Handles multiple provider shapes:
    - OpenAI o-series / gpt-oss / DeepSeek R1 → `message.reasoning_content`
    - Anthropic Claude extended thinking → `message.thinking_blocks[*].thinking`
    - Bedrock Llama 4 direct → raw `{"type": "reasoning", "content": ...}` dicts
    - Fallback → inspect `message.model_dump()` for any of the above keys
    """
    # 1. Flat reasoning_content attribute (most providers via litellm)
    reasoning = getattr(message, "reasoning_content", None)
    if reasoning:
        return reasoning if isinstance(reasoning, str) else str(reasoning)

    # 2. Anthropic-style thinking blocks
    thinking_blocks = getattr(message, "thinking_blocks", None)
    if thinking_blocks:
        parts: list[str] = []
        for block in thinking_blocks:
            if isinstance(block, dict):
                text = block.get("thinking") or block.get("text") or ""
            else:
                text = getattr(block, "thinking", "") or getattr(block, "text", "")
            if text:
                parts.append(text)
        if parts:
            return "\n".join(parts)

    # 3. Fallback — inspect the pydantic/dict form
    dump: dict[str, Any] | None = None
    if hasattr(message, "model_dump"):
        try:
            dump = message.model_dump()
        except Exception:
            dump = None
    if dump:
        if dump.get("reasoning_content"):
            return str(dump["reasoning_content"])
        blocks = dump.get("thinking_blocks") or []
        parts = [
            b.get("thinking") or b.get("text") or ""
            for b in blocks
            if isinstance(b, dict)
        ]
        parts = [p for p in parts if p]
        if parts:
            return "\n".join(parts)

    return None
