"""The table of model families: a pattern on the model id, and that family's capabilities."""

from __future__ import annotations

import re
from dataclasses import replace

from .model import ModelCapabilities


def _both_spellings(*names: str) -> frozenset[str]:
    """``top_p`` and ``topP`` are the same parameter to a provider, and
    different keys to a dict. Every rule needs both or it half-works."""
    out: set[str] = set()
    for name in names:
        out.add(name)
        head, *rest = name.split("_")
        out.add(head + "".join(part.title() for part in rest))
    return frozenset(out)


#: Sampling parameters that reasoning/thinking models reject.
_SAMPLING = _both_spellings(
    "temperature",
    "top_p",
    "top_k",
    "presence_penalty",
    "frequency_penalty",
    "logit_bias",
    "logprobs",
)


#: Everything bedrock-mantle rejects for Gemma 4. AWS documents sampling as
#: ``temperature`` and ``top_p`` only, so every other knob is a 400 waiting to
#: happen — including the numeric thinking budget a qualitative effort replaced.
_GEMMA_BLOCKED = _both_spellings(
    "top_k",
    "presence_penalty",
    "frequency_penalty",
    "logit_bias",
    "logprobs",
    "thinking_budget",
    "reasoning_effort",
) | frozenset({"n", "modify_params"})


#: Shared by every Gemma 4 variant; E2B differs only in effort and window.
_GEMMA_4 = ModelCapabilities(
    blocked_params=_GEMMA_BLOCKED,
    recommended_params={"temperature": 1.0, "top_p": 0.95},
    supports_vision=True,
    supports_reasoning=True,
    supports_prompt_cache=True,
    supports_service_tier=True,
    supports_parallel_tool_calls=False,
    reasoning_history="strip",
    reasoning_channel="responses_api",
    prompt_cache_mode="implicit",
    image_sources=frozenset({"base64", "s3"}),
    content_block_order="image_first",
    schema_dialect="openai_strict",
    context_window=256_000,
    output_reserve=16_384,
    reason=(
        "Gemma 4 on bedrock-mantle: temperature/top_p only, reasoning via the "
        "Responses API, prior reasoning must not be replayed"
    ),
)


#: (pattern, capabilities). Ordered — the FIRST match wins, so the most
#: specific pattern must come first. `-e2b` before the Gemma 4 family and
#: `-lite` before `-flash` are not cosmetic: the general rule listed first
#: would swallow every specific variant.
RULES: list[tuple[re.Pattern[str], ModelCapabilities]] = [
    # ── Gemma 4 E2B ───────────────────────────────────────────────────────
    # The smallest variant reasons extensively by default; a high effort keeps
    # that in the dedicated reasoning channel instead of leaking into the
    # answer. Its window is half the larger variants'.
    (
        re.compile(r"gemma[-_]?4[-_]?e2b", re.I),
        replace(
            _GEMMA_4,
            default_reasoning_effort="high",
            context_window=128_000,
            output_reserve=8_192,
            reason=(
                "Gemma 4 E2B: high reasoning effort keeps thinking in the "
                "reasoning channel, out of the final answer"
            ),
        ),
    ),
    # ── Gemma 4 family (31B, 26B-A4B, and later ids) ──────────────────────
    (re.compile(r"gemma[-_]?([4-9]|\d{2,})", re.I), _GEMMA_4),
    # ── Google: Gemini 3.5+ Flash and later "thinking" models ─────────────
    # These 400 on every sampling parameter and on the numeric thinking
    # budget, which a qualitative `thinking_level` replaced.
    (
        re.compile(r"gemini-([3-9]\.[5-9]|[4-9])|gemini-\d{2,}", re.I),
        ModelCapabilities(
            blocked_params=_SAMPLING | _both_spellings("thinking_budget"),
            supports_vision=True,
            supports_reasoning=True,
            reasoning_history="strip",
            reasoning_channel="param",
            image_sources=frozenset({"base64", "url"}),
            schema_dialect="gemini",
            context_window=1_000_000,
            output_reserve=32_768,
            reason="Gemini 3.5+ rejects sampling params and numeric thinking_budget",
        ),
    ),
    (
        re.compile(r"gemini|vertex_ai", re.I),
        ModelCapabilities(
            supports_vision=True,
            schema_dialect="gemini",
            reason="Gemini function calling accepts only a Schema subset",
        ),
    ),
    # ── DeepSeek thinking mode ────────────────────────────────────────────
    # The inverse contract to Gemma: `reasoning_content` MUST be replayed on
    # every prior assistant message that emitted tool calls, or tool calling
    # breaks across turns.
    (
        re.compile(r"deepseek", re.I),
        ModelCapabilities(
            supports_reasoning=True,
            reasoning_history="replay",
            reasoning_channel="param",
            schema_dialect="openai_strict",
            reason="DeepSeek thinking mode requires reasoning_content replay",
        ),
    ),
    # ── OpenAI reasoning models ───────────────────────────────────────────
    # `gpt-5-chat` and `gpt-5.1` DO accept sampling params, so the negative
    # lookahead is load-bearing — without it, every GPT-5 variant is stripped
    # and the non-reasoning ones silently lose their temperature.
    (
        re.compile(r"\b(o[13]|gpt-5)(?!\.|-chat)(?:-|$)", re.I),
        ModelCapabilities(
            blocked_params=_SAMPLING | frozenset({"n"}),
            renamed_params={"max_tokens": "max_completion_tokens"},
            supports_reasoning=True,
            supports_vision=True,
            reasoning_history="strip",
            reasoning_channel="responses_api",
            schema_dialect="openai_strict",
            reason="o-series/GPT-5 reasoning models reject sampling params",
        ),
    ),
    # ── Anthropic ─────────────────────────────────────────────────────────
    (
        re.compile(r"claude|anthropic", re.I),
        ModelCapabilities(
            supports_vision=True,
            supports_prompt_cache=True,
            supports_reasoning=True,
            prompt_cache_mode="explicit",
            schema_dialect="anthropic",
            context_window=200_000,
            output_reserve=16_384,
            reason="",
        ),
    ),
    # ── Amazon Bedrock, non-Anthropic families ────────────────────────────
    # Nova/Titan/Llama/Mistral reject `modify_params`, which exists only for
    # Bedrock-Claude's strict tool_use/tool_result id pairing.
    (
        re.compile(r"(nova|titan|llama|mistral|cohere|ai21)", re.I),
        ModelCapabilities(
            blocked_params=frozenset({"modify_params"}),
            reason="non-Anthropic Bedrock families reject modify_params",
        ),
    ),
]


#: Everything unmatched. Blocks nothing — an unknown model must not be
#: degraded by a layer whose whole job is to prevent avoidable 400s.
DEFAULT_CAPABILITIES = ModelCapabilities()
