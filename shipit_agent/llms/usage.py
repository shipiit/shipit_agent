"""Normalize cache accounting without changing provider-reported counters."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _count(usage: Any, key: str) -> int | None:
    """A token counter the provider actually reported, or ``None``."""
    value = usage.get(key) if isinstance(usage, Mapping) else getattr(usage, key, None)
    valid = isinstance(value, int) and not isinstance(value, bool) and value >= 0
    return value if valid else None


def normalize_token_usage(
    usage: Any, *, input_key: str = "prompt_tokens", output_key: str = "completion_tokens"
) -> dict[str, int]:
    """A provider's usage as ``prompt_tokens`` / ``completion_tokens`` / ``total_tokens``.

    A counter the provider left out, or sent as something other than a
    non-negative integer, is left out here too. Writing 0 for it would report
    the work as free, and a token budget would never stop the run.
    """
    if not usage:
        return {}
    prompt, completion, total = _count(usage, input_key), _count(usage, output_key), _count(usage, "total_tokens")
    out: dict[str, int] = {}
    if prompt is not None:
        out["prompt_tokens"] = prompt
    if completion is not None:
        out["completion_tokens"] = completion
    if total is not None:
        out["total_tokens"] = total
    elif prompt is not None and completion is not None:
        out["total_tokens"] = prompt + completion
    return out


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
