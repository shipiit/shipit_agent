"""Telling read-only, mutating and file-editing tools apart by name, when a tool does not say."""

from __future__ import annotations

import fnmatch

# Default name heuristics. Overridable per-engine, and a tool may declare its
# own ``read_only: bool`` attribute which always wins over these.
_DEFAULT_READ_ONLY: tuple[str, ...] = (
    "read*",
    "*read*",
    "view*",
    "list*",
    "glob*",
    "grep*",
    "search*",
    "web_search",
    "open_url",
    "get_*",
    "fetch*",
    "*_get",
    "*_list",
    "*_search",
    "plan*",
    "decompose*",
    "synthesize*",
    "decision*",
    "verify*",
    "build_prompt",
    "tool_search",
    "ask_user",
    "human_review",
)


_DEFAULT_MUTATING: tuple[str, ...] = (
    "write*",
    "edit*",
    "*write*",
    "bash",
    "run_code",
    "code_execution",
    "*_create",
    "*_update",
    "*_delete",
    "*send*",
    "*_post",
    "sql",
    "build_artifact",
    "*_patch",
)


_EDIT_TOOLS: tuple[str, ...] = ("write*", "edit*", "*write*", "build_artifact")


def _matches_any(name: str, patterns: tuple[str, ...] | list[str]) -> bool:
    return any(fnmatch.fnmatch(name, p) for p in patterns)
