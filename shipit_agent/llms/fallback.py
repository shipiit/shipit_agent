"""Turning an Agent's ``fallback_model`` into the adapters a run falls back to.

A model id (or a comma-separated list, as in the Claude Agent SDK) becomes
a copy of the primary adapter with that model, so it keeps the primary's
provider, credentials and settings. An adapter instance is used as given,
which is how to fall back to another provider.
"""

from __future__ import annotations

import copy
from typing import Any

__all__ = ["fallback_llms"]


def fallback_llms(primary: Any, spec: Any) -> list[Any]:
    """The adapters to try, in order, after *primary* fails."""
    if spec is None:
        return []
    items = spec if isinstance(spec, (list, tuple)) else [spec]
    resolved: list[Any] = []
    for item in items:
        if isinstance(item, str):
            resolved.extend(_with_model(primary, name.strip()) for name in item.split(",") if name.strip())
        elif callable(getattr(item, "complete", None)):
            resolved.append(item)
        else:
            raise TypeError(
                f"fallback_model takes model ids or model adapters, not {type(item).__name__}"
            )
    return resolved


def _with_model(primary: Any, model: str) -> Any:
    if not hasattr(primary, "model"):
        raise ValueError(
            f"fallback_model {model!r} is a model id, but {type(primary).__name__} has no "
            "'model' to change; pass an adapter instance instead"
        )
    clone = copy.copy(primary)
    clone.model = model
    return clone
