"""Helpers shared by the OpenAI adapter and its streaming path."""

from __future__ import annotations

import re
from typing import Any

# Models that natively produce reasoning / thinking content.
# Used to auto-pass `reasoning_effort` when the caller doesn't.
_REASONING_MODEL_PATTERNS = [
    re.compile(r"^o1(-|$)"),  # o1, o1-mini, o1-preview
    re.compile(r"^o3(-|$)"),  # o3, o3-mini
    re.compile(r"^o4(-|$)"),  # o4, o4-mini
    re.compile(r"^gpt-5"),  # gpt-5 family
    re.compile(r"^deepseek-r1"),  # DeepSeek R1 via OpenAI-compatible endpoints
]


def _is_reasoning_model(model: str) -> bool:
    m = (model or "").lower()
    return any(p.search(m) for p in _REASONING_MODEL_PATTERNS)


#: Genuine ``OpenAI()`` client-constructor parameters. Anything else a caller
#: passes is a completion/sampling parameter (forwarded to
#: ``chat.completions.create``) or a non-OpenAI flag we drop. Routing all of
#: them to the client used to make it reject ``drop_params`` and silently
#: swallow ``top_p`` (it never reached the model).
_OPENAI_CLIENT_PARAMS = frozenset(
    {
        "base_url",
        "organization",
        "project",
        "timeout",
        "max_retries",
        "default_headers",
        "default_query",
        "http_client",
        "websocket_base_url",
    }
)


#: LiteLLM-only / non-OpenAI knobs that must never reach the OpenAI SDK.
_NON_OPENAI_PARAMS = frozenset(
    {
        "drop_params",
        "modify_params",
        "custom_llm_provider",
        "api_base",
        "aws_region_name",
        "region",
        "prompt_caching",
        "num_retries",
        "aws_bedrock_client",
        "mock_response",
    }
)


# A few OpenAI-compatible gateways acknowledge ``stream=True`` but sometimes
# return a completed response object (Bedrock Mantle can do this after a
# reasoning pass). The provider latency cannot be recovered, but emitting the
# already-buffered text in bounded deltas keeps downstream SSE/rendering
# contracts consistent and avoids one enormous UI update.
_BUFFERED_DELTA_CHARS = 48


def _buffered_deltas(text: str) -> list[str]:
    return [
        text[offset : offset + _BUFFERED_DELTA_CHARS]
        for offset in range(0, len(text), _BUFFERED_DELTA_CHARS)
    ]


def _usage_dict(usage_obj: Any) -> dict[str, int]:
    """Normalize an OpenAI usage object, including automatic-cache counters.

    OpenAI-compatible endpoints — including the Bedrock Mantle / Gemma route —
    do *implicit* prompt caching and report the cached portion under
    ``prompt_tokens_details.cached_tokens`` (and any write under
    ``cache_write_tokens``). Surface those under the same
    ``cache_read_input_tokens`` / ``cache_creation_input_tokens`` keys the cost
    tracker already reads for Anthropic, so cache savings are visible on EVERY
    path — the streaming path (which the agent loop uses) previously dropped
    them, so a real 99%-cached prompt reported as if nothing were cached.
    """
    if not usage_obj:
        return {}
    out: dict[str, int] = {
        "prompt_tokens": getattr(usage_obj, "prompt_tokens", 0) or 0,
        "completion_tokens": getattr(usage_obj, "completion_tokens", 0) or 0,
        "total_tokens": getattr(usage_obj, "total_tokens", 0) or 0,
    }
    try:
        details = getattr(usage_obj, "prompt_tokens_details", None)
        cached = getattr(details, "cached_tokens", None) if details else None
        if cached:
            out["cache_read_input_tokens"] = int(cached)
        written = getattr(details, "cache_write_tokens", None) if details else None
        if written:
            out["cache_creation_input_tokens"] = int(written)
        out_details = getattr(usage_obj, "completion_tokens_details", None)
        reasoning = (
            getattr(out_details, "reasoning_tokens", None) if out_details else None
        )
        if reasoning:
            out["reasoning_tokens"] = int(reasoning)
    except Exception:
        pass
    return out
