"""Normalize cache accounting without changing provider-reported counters."""
from __future__ import annotations


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
