"""Normalize cache accounting without changing provider-reported counters."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def normalize_token_usage(
    usage: Any,
    *,
    input_key: str = "prompt_tokens",
    output_key: str = "completion_tokens",
) -> dict[str, int]:
    """Keep valid provider counters; missing usage is unknown, never zero.

    Accept SDK objects and mapping responses. Do not infer either input or
    output from totals: cache semantics differ between providers.
    """
    result: dict[str, int] = {}
    for target, source in (
        ("prompt_tokens", input_key),
        ("completion_tokens", output_key),
        ("total_tokens", "total_tokens"),
    ):
        value = (
            usage.get(source) if isinstance(usage, Mapping)
            else getattr(usage, source, None)
        )
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            result[target] = value
    if "total_tokens" not in result and all(
        key in result for key in ("prompt_tokens", "completion_tokens")
    ):
        result["total_tokens"] = result["prompt_tokens"] + result["completion_tokens"]
    return result


def has_complete_token_usage(response) -> bool:
    """Whether normalized input/output counters can enforce a task budget.

    A cache-only or total-only report is not sufficient for the runtime's
    cache-aware accounting. Explicit zero counters are valid; omitted values
    must not silently be treated as free work.
    """
    usage = response.usage or {}
    return all(
        isinstance(usage.get(key), int)
        and not isinstance(usage.get(key), bool)
        and usage[key] >= 0
        for key in ("prompt_tokens", "completion_tokens")
    )


def input_token_counts(response):
    """Return uncached/read/write/total input; unknown adapters retain legacy semantics."""
    usage = response.usage or {}
    prompt = max(0, int(usage.get("prompt_tokens", 0) or 0))
    read = max(0, int(usage.get("cache_read_input_tokens", 0) or 0))
    write = max(0, int(usage.get("cache_creation_input_tokens", 0) or 0))
    inclusive = response.metadata.get("prompt_tokens_include_cache", False)
    uncached = max(0, prompt - read - write) if inclusive else prompt
    total = prompt if inclusive else prompt + read + write
    return uncached, read, write, total
