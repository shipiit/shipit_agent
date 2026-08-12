"""Deferred tool loading — the tool catalogue on demand.

An agent with 50+ tools pays for every JSON schema on every step, even
though a typical run touches three or four of them. Deferral splits the
catalogue on demand:

- A small **core set** keeps its full schema in every request.
- Every other tool is listed **by name only** in the system prompt.
- ``tool_search`` finds *and loads* deferred tools mid-run: once loaded,
  a tool's schema rides along on every later step of the run.
- Calling a deferred tool directly still works — the registry always has
  every tool — and the call marks it loaded for subsequent steps.

The mechanism is provider-agnostic: it changes what schemas are *sent*,
not how any provider formats them.

Enable with ``Agent(deferred_tools=True)`` (defer everything outside the
default core set) or ``Agent(deferred_tools=["slack", "jira"])`` (defer
exactly those tools).
"""

from .core import (
    DEFAULT_CORE_TOOLS,
    DEFERRED_NAMES_KEY,
    LOADED_NAMES_KEY,
    SCHEMAS_BY_NAME_KEY,
    deferred_index,
    resolve_deferred_names,
    select_schemas,
    signature_line,
)

__all__ = [
    "DEFAULT_CORE_TOOLS",
    "DEFERRED_NAMES_KEY",
    "LOADED_NAMES_KEY",
    "SCHEMAS_BY_NAME_KEY",
    "deferred_index",
    "resolve_deferred_names",
    "select_schemas",
    "signature_line",
]
