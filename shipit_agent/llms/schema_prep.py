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

import json
import logging
from typing import Any

from shipit_agent.llms.schema_rules import SchemaRules, rules_for_dialect

logger = logging.getLogger(__name__)

__all__ = [
    "resolve_refs",
    "normalize_schema",
    "sanitize_for",
    "prepare_schema",
    "prepare_tool_schema",
    "clear_schema_cache",
    "schema_cache_stats",
]

#: Keys that hold a *definition table*, not a subschema.
_DEF_KEYS = ("$defs", "definitions")

#: Keys whose value is a single subschema.
_SUBSCHEMA_KEYS = ("items", "additionalProperties", "not", "if", "then", "else")

#: Keys whose value is a list of subschemas.
_SUBSCHEMA_LIST_KEYS = ("oneOf", "anyOf", "allOf", "prefixItems")

#: Keys whose value is a mapping of name → subschema.
_SUBSCHEMA_MAP_KEYS = ("properties", "patternProperties", "$defs", "definitions")


# --------------------------------------------------------------------------- #
# 1. $ref resolution
# --------------------------------------------------------------------------- #


def _lookup_pointer(root: dict[str, Any], pointer: str) -> Any:
    """Resolve a local JSON Pointer (``#/$defs/Filter``) against *root*."""
    if pointer == "#":
        return root
    if not pointer.startswith("#/"):
        raise KeyError(pointer)
    node: Any = root
    for raw in pointer[2:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(node, list):
            node = node[int(token)]
        elif isinstance(node, dict):
            node = node[token]
        else:
            raise KeyError(pointer)
    return node


def _cycle_placeholder(pointer: str) -> dict[str, Any]:
    return {
        "type": "object",
        "description": (
            f"Recursive structure (was {pointer}); nested occurrences accept "
            "any object."
        ),
        "additionalProperties": True,
    }


def _resolve(node: Any, root: dict[str, Any], seen: tuple[str, ...]) -> Any:
    if isinstance(node, list):
        return [_resolve(item, root, seen) for item in node]
    if not isinstance(node, dict):
        return node

    ref = node.get("$ref")
    if isinstance(ref, str):
        if ref in seen:
            logger.debug("Cycle at %s; collapsing to permissive object", ref)
            return _cycle_placeholder(ref)
        try:
            target = _lookup_pointer(root, ref)
        except (KeyError, IndexError, ValueError):
            # An external or broken ref cannot be inlined. Drop the ref and keep
            # whatever sibling keys exist — a permissive schema beats an
            # unusable one, and beats raising inside a tool binding.
            logger.debug("Unresolvable $ref %r; dropping", ref)
            rest = {k: v for k, v in node.items() if k != "$ref"}
            return _resolve(rest, root, seen) if rest else {"type": "object"}
        if not isinstance(target, dict):
            return target
        # Sibling keys alongside $ref override the target (2020-12 semantics).
        merged = {**target, **{k: v for k, v in node.items() if k != "$ref"}}
        return _resolve(merged, root, seen + (ref,))

    out: dict[str, Any] = {}
    for key, value in node.items():
        if key in _SUBSCHEMA_MAP_KEYS and isinstance(value, dict):
            out[key] = {k: _resolve(v, root, seen) for k, v in value.items()}
        elif key in _SUBSCHEMA_LIST_KEYS and isinstance(value, list):
            out[key] = [_resolve(v, root, seen) for v in value]
        elif key in _SUBSCHEMA_KEYS:
            out[key] = _resolve(value, root, seen)
        else:
            out[key] = value
    return out


def resolve_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Inline every local ``$ref``; drop the definition tables afterwards.

    Safe for all providers, so it runs unconditionally. Cycles collapse to a
    permissive object rather than recursing. Unresolvable refs are dropped with
    a debug line — never raised, because a tool binding must not be able to take
    a run down.
    """
    if not isinstance(schema, dict):
        return schema
    resolved = _resolve(schema, schema, ())
    if isinstance(resolved, dict):
        for key in _DEF_KEYS:
            resolved.pop(key, None)
    return resolved


# --------------------------------------------------------------------------- #
# 2. Provider-neutral normalization
# --------------------------------------------------------------------------- #

#: Meta keywords that are never useful to a model and are rejected by several.
_ALWAYS_DROP = frozenset({"$schema", "$id", "$anchor", "$comment", "$vocabulary"})


def _normalize(node: Any) -> Any:
    if isinstance(node, list):
        return [_normalize(item) for item in node]
    if not isinstance(node, dict):
        return node

    out: dict[str, Any] = {}
    for key, value in node.items():
        if key in _ALWAYS_DROP:
            continue

        # `type: ["string", "null"]` — the Pydantic Optional[...] shape. Most
        # providers want a single type; keep the non-null one and record
        # nullability where it is understood.
        if key == "type" and isinstance(value, list):
            non_null = [t for t in value if t != "null"]
            if len(non_null) == 1:
                out["type"] = non_null[0]
                if len(non_null) != len(value):
                    out.setdefault("nullable", True)
                continue
            if non_null:
                out["type"] = non_null
                continue
            out["type"] = "string"
            continue

        if key in _SUBSCHEMA_MAP_KEYS and isinstance(value, dict):
            out[key] = {k: _normalize(v) for k, v in value.items()}
        elif key in _SUBSCHEMA_LIST_KEYS and isinstance(value, list):
            out[key] = [_normalize(v) for v in value]
        elif key in _SUBSCHEMA_KEYS:
            out[key] = _normalize(value)
        else:
            out[key] = value
    return out


def normalize_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Fix shapes that are malformed or hostile to most providers."""
    result = _normalize(schema)
    return result if isinstance(result, dict) else {"type": "object"}


# --------------------------------------------------------------------------- #
# 3. Dialect-specific sanitization (the only lossy step)
# --------------------------------------------------------------------------- #


def _first_non_null_branch(branches: list[Any]) -> dict[str, Any] | None:
    for branch in branches:
        if isinstance(branch, dict) and branch.get("type") != "null":
            return branch
    return None


def _sanitize(node: Any, rules: SchemaRules, depth: int, dropped: set[str]) -> Any:
    if isinstance(node, list):
        return [_sanitize(item, rules, depth, dropped) for item in node]
    if not isinstance(node, dict):
        return node

    if rules.max_depth is not None and depth > rules.max_depth:
        dropped.add(f"<depth>{rules.max_depth}")
        return {"type": "object", "description": "Nested structure (truncated)."}

    work = dict(node)

    # Collapse a union into its first non-null branch, merging the parent's
    # own keys on top so a `description` written beside the union survives.
    if rules.collapse_unions:
        for union_key in ("anyOf", "oneOf"):
            branches = work.get(union_key)
            if isinstance(branches, list) and branches:
                chosen = _first_non_null_branch(branches)
                dropped.add(union_key)
                siblings = {k: v for k, v in work.items() if k != union_key}
                work = {**(chosen or {"type": "string"}), **siblings}
                if len(branches) > 1:
                    work.setdefault("nullable", True)
                break

    # `const` has no equivalent in the Gemini subset; a string const becomes a
    # one-value enum and a non-string const is dropped.
    if rules.const_to_enum and "const" in work:
        const = work.pop("const")
        dropped.add("const")
        if isinstance(const, str):
            work["enum"] = [const]

    if rules.string_enums_only and isinstance(work.get("enum"), list):
        strings = [v for v in work["enum"] if isinstance(v, str)]
        if len(strings) != len(work["enum"]):
            dropped.add("enum<non-string>")
        if strings:
            work["enum"] = strings
        else:
            work.pop("enum", None)

    if rules.fold_exclusive_bounds:
        if "exclusiveMinimum" in work:
            value = work.pop("exclusiveMinimum")
            dropped.add("exclusiveMinimum")
            if isinstance(value, (int, float)):
                work.setdefault("minimum", value)
        if "exclusiveMaximum" in work:
            value = work.pop("exclusiveMaximum")
            dropped.add("exclusiveMaximum")
            if isinstance(value, (int, float)):
                work.setdefault("maximum", value)

    # Tuple validation has no equivalent; keep the first entry as `items`.
    if "prefixItems" in work:
        prefix = work.pop("prefixItems")
        dropped.add("prefixItems")
        if isinstance(prefix, list) and prefix and "items" not in work:
            work["items"] = prefix[0]

    # `items: true/false` is legal JSON Schema and rejected as a schema object.
    if rules.require_items_object and isinstance(work.get("items"), bool):
        dropped.add("items<bool>")
        work["items"] = {"type": "string"} if work["items"] else {"type": "object"}

    for keyword in rules.strip_keywords:
        if keyword in work:
            work.pop(keyword)
            dropped.add(keyword)

    out: dict[str, Any] = {}
    for key, value in work.items():
        if key in _SUBSCHEMA_MAP_KEYS and isinstance(value, dict):
            out[key] = {
                k: _sanitize(v, rules, depth + 1, dropped) for k, v in value.items()
            }
        elif key in _SUBSCHEMA_LIST_KEYS and isinstance(value, list):
            out[key] = [_sanitize(v, rules, depth + 1, dropped) for v in value]
        elif key in _SUBSCHEMA_KEYS:
            out[key] = _sanitize(value, rules, depth + 1, dropped)
        else:
            out[key] = value

    # `required` must only name properties that survived.
    if isinstance(out.get("required"), list) and isinstance(out.get("properties"), dict):
        kept = [name for name in out["required"] if name in out["properties"]]
        if len(kept) != len(out["required"]):
            dropped.add("required<orphaned>")
        if kept:
            out["required"] = kept
        else:
            out.pop("required", None)

    return out


def sanitize_for(
    schema: dict[str, Any], dialect: str, *, tool_name: str = ""
) -> dict[str, Any]:
    """Strip what *dialect* is known to reject. Unknown dialects strip nothing."""
    rules = rules_for_dialect(dialect)
    if rules.is_permissive:
        return schema
    dropped: set[str] = set()
    result = _sanitize(schema, rules, 0, dropped)
    if dropped:
        logger.debug(
            "Schema for %s: removed %s for dialect %r (%s)",
            tool_name or "<tool>",
            ", ".join(sorted(dropped)),
            dialect,
            rules.reason or "not accepted by this dialect",
        )
    return result if isinstance(result, dict) else {"type": "object"}


# --------------------------------------------------------------------------- #
# 4. The pipeline, cached
# --------------------------------------------------------------------------- #

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


def prepare_tool_schema(
    tool_schema: dict[str, Any], *, dialect: str
) -> dict[str, Any]:
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
    global _HITS, _MISSES
    _CACHE.clear()
    _HITS = _MISSES = 0


def schema_cache_stats() -> dict[str, int]:
    """For ``doctor`` — confirms preparation is paid once, not per call."""
    return {"entries": len(_CACHE), "hits": _HITS, "misses": _MISSES}
