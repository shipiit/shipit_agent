"""Preparing a tool schema for a provider once, and reusing it."""

from __future__ import annotations

import json
from typing import Any

from .normalize import normalize_schema
from .refs import logger, resolve_refs
from .sanitize import sanitize_for

_CACHE: dict[tuple[str, str], dict[str, Any]] = {}


_HITS = _MISSES = 0


def prepare_schema(
    schema: dict[str, Any], *, dialect: str, tool_name: str = ""
) -> dict[str, Any]:
    """``resolve_refs`` → ``normalize`` → ``sanitize_for``, memoised.

    Keyed by ``(schema_hash, dialect)`` so the cost is paid once per distinct
    schema per dialect, not once per model call. Never raises: on any internal
    failure the input schema is returned unchanged, because a tool that is
    slightly wrong for the provider still beats a run that died in schema prep.
    """
    global _HITS, _MISSES
    if not isinstance(schema, dict) or not schema:
        return schema or {"type": "object", "properties": {}}
    try:
        key = (json.dumps(schema, sort_keys=True, default=str), dialect)
    except (TypeError, ValueError):
        key = None  # type: ignore[assignment]
    if key is not None and key in _CACHE:
        _HITS += 1
        return _CACHE[key]
    _MISSES += 1
    try:
        prepared = sanitize_for(
            normalize_schema(resolve_refs(schema)), dialect, tool_name=tool_name
        )
    except Exception:  # noqa: BLE001 — schema prep must never break a run
        logger.exception("Schema preparation failed for %s; using raw", tool_name)
        return schema
    if key is not None:
        _CACHE[key] = prepared
    return prepared


def prepare_tool_schema(tool_schema: dict[str, Any], *, dialect: str) -> dict[str, Any]:
    """Prepare a full OpenAI-style ``{"type":"function","function":{...}}`` entry.

    Only ``function.parameters`` is transformed; name and description are left
    exactly as authored, since they are what the model reasons about.
    """
    if not isinstance(tool_schema, dict):
        return tool_schema
    function = tool_schema.get("function")
    if not isinstance(function, dict):
        return tool_schema
    parameters = function.get("parameters")
    if not isinstance(parameters, dict):
        return tool_schema
    prepared = prepare_schema(
        parameters, dialect=dialect, tool_name=str(function.get("name", ""))
    )
    if prepared is parameters:
        return tool_schema
    return {
        **tool_schema,
        "function": {**function, "parameters": prepared},
    }


def clear_schema_cache() -> None:
    """Empty the prepared-schema cache and reset its hit counters."""
    global _HITS, _MISSES
    _CACHE.clear()
    _HITS = _MISSES = 0


def schema_cache_stats() -> dict[str, int]:
    """For ``doctor`` — confirms preparation is paid once, not per call."""
    return {"entries": len(_CACHE), "hits": _HITS, "misses": _MISSES}
