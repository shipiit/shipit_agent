"""Normalising a tool schema into the shape every provider accepts."""

from __future__ import annotations

from typing import Any

from .refs import _SUBSCHEMA_KEYS, _SUBSCHEMA_LIST_KEYS, _SUBSCHEMA_MAP_KEYS

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
