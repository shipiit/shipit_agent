"""Tool availability gating — hide tools whose dependencies are missing.

A tool that needs a CLI binary (``git``, ``cliclick``), a running daemon, an
env var, or an API key is useless when that dependency is absent — and worse
than useless in an agent loop: its schema still costs tokens on every request,
and the model wastes a turn calling it only to get an error back.

This module lets a tool **declare** what it needs, and the agent **strips it
from the advertised set** when the need isn't met. A tool declares any of:

- ``requires_command`` — a CLI name (or list) that must be on ``PATH``.
- ``requires_env`` — an env var (or list) that must be set and non-empty.
- ``check_fn`` — a callable returning ``bool`` for anything more specific
  (a port open, a package importable, a socket reachable).

A tool that declares **none** of these is always available, so gating is fully
backward-compatible: nothing is hidden until a tool opts in. Expensive checks
(``PATH`` lookups, ``check_fn``) are cached briefly so re-assembling the tool
set each turn stays cheap; env checks are already cheap and read live.
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from typing import Any

logger = logging.getLogger(__name__)

#: How long a positive/negative probe result is trusted before re-checking.
#: Short enough that installing a missing binary mid-session is picked up soon,
#: long enough that a per-turn re-assembly doesn't re-probe the filesystem.
_CACHE_TTL_SECONDS = 30.0

_probe_cache: dict[str, tuple[float, bool]] = {}


def _now() -> float:
    return time.monotonic()


def _cached_probe(key: str, probe: Any) -> bool:
    hit = _probe_cache.get(key)
    now = _now()
    if hit is not None and now - hit[0] < _CACHE_TTL_SECONDS:
        return hit[1]
    try:
        value = bool(probe())
    except Exception as exc:  # noqa: BLE001 — a failing probe means "unavailable"
        logger.debug("availability probe %s raised: %s", key, exc)
        value = False
    _probe_cache[key] = (now, value)
    return value


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value]


def is_available(tool: Any) -> tuple[bool, str]:
    """Return ``(available, reason)`` for a tool.

    ``reason`` is empty when available, else a short human phrase naming the
    missing dependency. A tool that declares no requirements is always available.
    """
    for command in _as_list(getattr(tool, "requires_command", None)):
        if not _cached_probe(f"cmd:{command}", lambda c=command: shutil.which(c) is not None):
            return False, f"'{command}' not on PATH"

    for var in _as_list(getattr(tool, "requires_env", None)):
        if not os.environ.get(var):
            return False, f"env {var} not set"

    check = getattr(tool, "check_fn", None)
    if callable(check):
        name = str(getattr(tool, "name", id(check)))
        if not _cached_probe(f"fn:{name}", check):
            return False, "availability check failed"

    return True, ""


def filter_available(tools: list[Any]) -> tuple[list[Any], list[tuple[str, str]]]:
    """Split tools into ``(available, skipped)``.

    ``skipped`` is a list of ``(tool_name, reason)`` for tools whose declared
    dependency is missing — surfaced so a UI or log can explain the absence
    rather than leaving a tool mysteriously gone.
    """
    available: list[Any] = []
    skipped: list[tuple[str, str]] = []
    for tool in tools:
        ok, reason = is_available(tool)
        if ok:
            available.append(tool)
        else:
            skipped.append((str(getattr(tool, "name", "?")), reason))
    return available, skipped


def clear_cache() -> None:
    """Forget cached probe results (mainly for tests)."""
    _probe_cache.clear()
