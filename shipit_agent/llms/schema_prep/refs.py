"""Inlining ``$ref`` pointers, with a placeholder where a schema refers back to itself."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


#: Keys that hold a *definition table*, not a subschema.
_DEF_KEYS = ("$defs", "definitions")


#: Keys whose value is a single subschema.
_SUBSCHEMA_KEYS = ("items", "additionalProperties", "not", "if", "then", "else")


#: Keys whose value is a list of subschemas.
_SUBSCHEMA_LIST_KEYS = ("oneOf", "anyOf", "allOf", "prefixItems")


#: Keys whose value is a mapping of name → subschema.
_SUBSCHEMA_MAP_KEYS = ("properties", "patternProperties", "$defs", "definitions")


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
