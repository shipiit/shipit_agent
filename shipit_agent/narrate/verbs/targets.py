"""What a call is about: the argument worth naming, per tool and by fallback."""

from __future__ import annotations

from typing import Any, Callable
from urllib.parse import urlparse

from .spec import VerbSpec, _clip, _usable_target

# ── Target extraction ────────────────────────────────────────────────────
# A few tools have a more interesting target than "the first argument".

def _first_code_line(args: dict[str, Any]) -> str | None:
    """First non-blank line of a code/command argument — the readable part."""
    for key in ("code", "command", "cmd", "source", "script", "query", "sql"):
        raw = args.get(key)
        if not isinstance(raw, str):
            continue
        for line in raw.splitlines():
            stripped = line.strip()
            if stripped:
                return _clip(stripped)
    return None


def _url_host(args: dict[str, Any]) -> str | None:
    """A URL's host — ``https://github.com/x/y?z=1`` → ``github.com``."""
    raw = args.get("url")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        host = urlparse(raw).netloc
    except ValueError:
        host = ""
    return host or _clip(raw)


_TARGET_EXTRACTORS: dict[str, Callable[[dict[str, Any]], str | None]] = {
    "bash": _first_code_line,
    "run_code": _first_code_line,
    "sql": _first_code_line,
    "open_url": _url_host,
    "download_file": _url_host,
    "playwright_browse": _url_host,
    "custom_api": _url_host,
}


# ── Whole-summary overrides ──────────────────────────────────────────────
# For the handful of tools whose *verb* changes with the call, not just the
# target. `sub_agent` is the case: starting work and collecting its results
# are different actions behind one tool name, and "Delegated results" reads
# as nonsense. Returns (past, present, target).

def _summarize_sub_agent(args: dict[str, Any]) -> tuple[str, str, str | None]:
    collect = args.get("collect")
    if isinstance(collect, str) and collect.strip():
        target = "results" if collect.strip().lower() == "all" else collect.strip()
        return "Collected", "Collecting", target
    task = args.get("task")
    target = _clip(task) if isinstance(task, str) and task.strip() else None
    if args.get("background"):
        return "Started", "Starting", target
    return "Delegated", "Delegating", target


def _summarize_connections(args: dict[str, Any]) -> tuple[str, str, str | None]:
    action = str(args.get("action") or "list").lower()
    target = args.get("connection")
    target = _clip(target) if isinstance(target, str) and target.strip() else None
    if action == "request":
        return "Requested a connection to", "Requesting a connection to", target
    if action == "check":
        return "Checked", "Checking", target
    return "Listed connectable resources", "Listing connectable resources", None


_SUMMARY_OVERRIDES: dict[str, Callable[[dict[str, Any]], tuple[str, str, str | None]]] = {
    "sub_agent": _summarize_sub_agent,
    "connections": _summarize_connections,
}


def _fallback_target(args: dict[str, Any]) -> str | None:
    """First short scalar argument — the best guess for an unknown tool."""
    for value in args.values():
        if isinstance(value, str) and value.strip():
            return _clip(value)
        if isinstance(value, (int, float, bool)):
            return str(value)
    return None


def _extract_target(name: str, args: dict[str, Any], spec: VerbSpec | None) -> str | None:
    return _usable_target(_raw_target(name, args, spec))


def _raw_target(name: str, args: dict[str, Any], spec: VerbSpec | None) -> str | None:
    extractor = _TARGET_EXTRACTORS.get(name)
    if extractor is not None:
        found = extractor(args)
        if found:
            return found
    if spec is not None:
        for key in spec.args:
            value = args.get(key)
            if isinstance(value, str) and value.strip():
                return _clip(value)
            if isinstance(value, (int, float)):
                return str(value)
        # A spec that names no argument (or whose arguments are absent) still
        # falls through to the generic guess rather than showing nothing.
    return _fallback_target(args)
