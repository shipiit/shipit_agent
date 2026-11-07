"""Make a tool's JSON Schema acceptable to whichever model is about to see it.

An MCP server built on Pydantic or FastMCP emits ``$defs`` and ``$ref`` for any
nested argument model. OpenAI tolerates that. A strict OpenAI-*compatible*
validator — which is what ``bedrock-mantle`` is — often does not, and neither
does the Gemini function-calling subset. The failure is invisible in the worst
way: simple tools keep working, tools with nested arguments quietly stop being
callable, and the model reads as stupid rather than blocked.

So every tool schema passes through one pipeline before it reaches a model:

    resolve_refs  →  normalize  →  sanitize_for(dialect)

* ``resolve_refs`` runs for **every** provider. Inlining a local ``$ref`` is
  never wrong; leaving one in is wrong for several.
* ``normalize`` fixes what is malformed or pointlessly provider-hostile
  regardless of dialect (``type: [null, "string"]``, stray ``$schema``).
* ``sanitize_for`` is the only lossy step, and it is gated on a declarative
  dialect rule (see :mod:`schema_rules`) so an unmatched model loses nothing.

Two properties, both deliberate and both mirroring ``capabilities.py``:

* **A missing rule is harmless.** An unknown dialect falls back to
  ``PERMISSIVE``, which strips nothing. This layer only ever removes keywords a
  provider is known to reject; it never invents structure.
* **Every removal is logged.** A keyword that vanishes silently is worse than
  one that 400s, because the 400 at least names itself.

Cycles are real (a ``Node`` with ``children: list[Node]``). A cycle cannot be
inlined, so it collapses to a permissive ``{"type": "object"}`` with a note in
the description rather than recursing forever.
"""

from __future__ import annotations

from .cache import (
    clear_schema_cache,
    prepare_schema,
    prepare_tool_schema,
    schema_cache_stats,
)
from .normalize import normalize_schema
from .refs import logger, resolve_refs
from .sanitize import sanitize_for

__all__ = [
    "clear_schema_cache",
    "logger",
    "normalize_schema",
    "prepare_schema",
    "prepare_tool_schema",
    "resolve_refs",
    "sanitize_for",
    "schema_cache_stats",
]
