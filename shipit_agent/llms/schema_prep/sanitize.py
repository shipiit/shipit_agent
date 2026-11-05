"""Removing what one provider's schema dialect rejects."""

from __future__ import annotations

from typing import Any

from shipit_agent.llms.schema_rules import SchemaRules, rules_for_dialect

from .refs import _SUBSCHEMA_KEYS, _SUBSCHEMA_LIST_KEYS, _SUBSCHEMA_MAP_KEYS, logger


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
    if isinstance(out.get("required"), list) and isinstance(
        out.get("properties"), dict
    ):
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
