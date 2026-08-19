"""Schema preparation: refs, normalization, dialect sanitization."""

from __future__ import annotations

import pytest

from shipit_agent.llms.schema_prep import (
    clear_schema_cache,
    normalize_schema,
    prepare_schema,
    prepare_tool_schema,
    resolve_refs,
    sanitize_for,
    schema_cache_stats,
)


@pytest.fixture(autouse=True)
def _clean_cache():
    clear_schema_cache()
    yield
    clear_schema_cache()


# --------------------------------------------------------------------------- #
# $ref resolution
# --------------------------------------------------------------------------- #

NESTED = {
    "type": "object",
    "properties": {"filter": {"$ref": "#/$defs/Filter"}},
    "$defs": {
        "Filter": {
            "type": "object",
            "properties": {"field": {"type": "string"}, "op": {"$ref": "#/$defs/Op"}},
            "required": ["field"],
        },
        "Op": {"type": "string", "enum": ["eq", "gt"]},
    },
}


def test_two_level_refs_are_inlined():
    resolved = resolve_refs(NESTED)
    filter_schema = resolved["properties"]["filter"]
    assert filter_schema["type"] == "object"
    assert filter_schema["properties"]["op"]["enum"] == ["eq", "gt"]
    assert "$defs" not in resolved
    assert "$ref" not in repr(resolved)


def test_sibling_keys_beside_a_ref_win():
    schema = {
        "type": "object",
        "properties": {
            "f": {"$ref": "#/$defs/Filter", "description": "caller's own words"}
        },
        "$defs": {"Filter": {"type": "object", "description": "generic"}},
    }
    resolved = resolve_refs(schema)
    assert resolved["properties"]["f"]["description"] == "caller's own words"


def test_recursive_ref_collapses_instead_of_recursing():
    schema = {
        "type": "object",
        "properties": {"children": {"type": "array", "items": {"$ref": "#/$defs/Node"}}},
        "$defs": {
            "Node": {
                "type": "object",
                "properties": {
                    "children": {"type": "array", "items": {"$ref": "#/$defs/Node"}}
                },
            }
        },
    }
    resolved = resolve_refs(schema)
    inner = resolved["properties"]["children"]["items"]
    assert inner["type"] == "object"
    assert "$ref" not in repr(resolved)


def test_unresolvable_ref_is_dropped_not_raised():
    schema = {"type": "object", "properties": {"x": {"$ref": "https://elsewhere#/X"}}}
    resolved = resolve_refs(schema)
    assert resolved["properties"]["x"] == {"type": "object"}


# --------------------------------------------------------------------------- #
# Normalization
# --------------------------------------------------------------------------- #


def test_optional_type_list_collapses_to_the_non_null_type():
    normalized = normalize_schema(
        {"type": "object", "properties": {"note": {"type": ["string", "null"]}}}
    )
    note = normalized["properties"]["note"]
    assert note["type"] == "string"
    assert note["nullable"] is True


def test_meta_keywords_are_dropped_everywhere():
    normalized = normalize_schema(
        {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "x", "type": "object"}
    )
    assert normalized == {"type": "object"}


# --------------------------------------------------------------------------- #
# Dialect sanitization
# --------------------------------------------------------------------------- #

GNARLY = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "mode": {"const": "fast"},
        "level": {"type": "integer", "exclusiveMinimum": 0, "multipleOf": 2},
        "choice": {"anyOf": [{"type": "null"}, {"type": "string", "enum": ["a", 2]}]},
        "items": {"type": "array", "prefixItems": [{"type": "string"}]},
    },
    "required": ["mode", "level"],
}


def test_gemini_dialect_strips_its_known_rejections():
    result = sanitize_for(GNARLY, "gemini")
    assert "additionalProperties" not in result
    assert result["properties"]["mode"]["enum"] == ["fast"]
    assert "const" not in result["properties"]["mode"]
    assert result["properties"]["level"]["minimum"] == 0
    assert "multipleOf" not in result["properties"]["level"]
    assert result["properties"]["choice"]["enum"] == ["a"]  # non-string dropped
    assert result["properties"]["items"]["items"] == {"type": "string"}


def test_unknown_dialect_changes_nothing():
    assert sanitize_for(GNARLY, "some-future-gateway") == GNARLY


def test_required_is_pruned_to_surviving_properties():
    schema = {
        "type": "object",
        "properties": {"kept": {"type": "string"}},
        "required": ["kept", "gone"],
    }
    assert sanitize_for(schema, "gemini")["required"] == ["kept"]


def test_openai_strict_keeps_structure_but_drops_2020_keywords():
    result = sanitize_for(
        {"type": "object", "unevaluatedProperties": False, "properties": {"a": {"type": "string"}}},
        "openai_strict",
    )
    assert "unevaluatedProperties" not in result
    assert result["properties"]["a"]["type"] == "string"


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #


def test_prepare_schema_runs_refs_then_dialect():
    prepared = prepare_schema(NESTED, dialect="gemini", tool_name="query")
    assert "$defs" not in prepared
    assert prepared["properties"]["filter"]["properties"]["op"]["enum"] == ["eq", "gt"]


def test_prepare_schema_is_cached_per_dialect():
    prepare_schema(NESTED, dialect="gemini")
    prepare_schema(NESTED, dialect="gemini")
    stats = schema_cache_stats()
    assert stats["misses"] == 1
    assert stats["hits"] == 1


def test_prepare_schema_never_raises_on_bad_input():
    assert prepare_schema({}, dialect="gemini") == {"type": "object", "properties": {}}


def test_prepare_tool_schema_touches_only_parameters():
    tool = {
        "type": "function",
        "function": {
            "name": "query",
            "description": "unchanged",
            "parameters": NESTED,
        },
    }
    prepared = prepare_tool_schema(tool, dialect="gemini")
    assert prepared["function"]["description"] == "unchanged"
    assert prepared["function"]["name"] == "query"
    assert "$defs" not in prepared["function"]["parameters"]
