"""Which JSON Schema keywords each model family's validator will accept.

Companion to :mod:`capabilities`, same shape and same discipline: one
declarative rule per dialect, matched by name, ordered so the most specific
wins, and permissive when nothing matches.

A *dialect* is not a provider. Several providers share ``openai_strict``;
Gemini and Vertex share ``gemini``. Capabilities name the dialect, so adding a
provider that happens to validate like OpenAI costs one line in
``capabilities.py`` and nothing here.

The keyword lists are the ones observed to be rejected in practice, not the
whole of what a spec omits — a rule that strips more than necessary makes tools
less expressive for no gain.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

__all__ = [
    "SchemaRules",
    "PERMISSIVE",
    "DIALECTS",
    "rules_for_dialect",
    "register_dialect",
]


@dataclass(frozen=True, slots=True)
class SchemaRules:
    """What to remove from a schema for one dialect. Defaults remove nothing."""

    #: Keywords deleted outright wherever they appear.
    strip_keywords: frozenset[str] = frozenset()
    #: Collapse ``anyOf``/``oneOf`` into their first non-null branch.
    collapse_unions: bool = False
    #: Rewrite a string ``const`` as a one-value ``enum``; drop others.
    const_to_enum: bool = False
    #: Keep only string members of an ``enum``.
    string_enums_only: bool = False
    #: Fold ``exclusiveMinimum``/``exclusiveMaximum`` into inclusive bounds.
    fold_exclusive_bounds: bool = False
    #: Replace a boolean ``items`` with a schema object.
    require_items_object: bool = False
    #: Truncate nesting beyond this depth to a permissive object.
    max_depth: int | None = None
    #: Free text naming the failure this rule prevents, for the log line.
    reason: str = ""

    @property
    def is_permissive(self) -> bool:
        """True when this rule set would leave every schema untouched."""
        return not (
            self.strip_keywords
            or self.collapse_unions
            or self.const_to_enum
            or self.string_enums_only
            or self.fold_exclusive_bounds
            or self.require_items_object
            or self.max_depth is not None
        )


#: Everything unmatched. Strips nothing — an unknown model must never be
#: degraded by a layer whose only job is preventing avoidable 400s.
PERMISSIVE = SchemaRules()


#: Gemini / Vertex function-calling Schema subset. The narrowest dialect: it
#: accepts a small fixed set of keywords and rejects the rest outright.
_GEMINI = SchemaRules(
    strip_keywords=frozenset(
        {
            "additionalProperties",
            "patternProperties",
            "propertyNames",
            "unevaluatedProperties",
            "unevaluatedItems",
            "uniqueItems",
            "multipleOf",
            "readOnly",
            "writeOnly",
            "deprecated",
            "examples",
            "contentEncoding",
            "contentMediaType",
            "dependentRequired",
            "dependentSchemas",
            "allOf",
            "not",
            "if",
            "then",
            "else",
        }
    ),
    collapse_unions=True,
    const_to_enum=True,
    string_enums_only=True,
    fold_exclusive_bounds=True,
    require_items_object=True,
    reason="Gemini function-calling accepts only a small Schema subset",
)


#: OpenAI-compatible gateways (bedrock-mantle, vLLM, LiteLLM proxy, Together).
#: Far more tolerant than Gemini, but stricter than OpenAI itself: several
#: reject 2020-12 keywords that OpenAI silently ignores, and none of them
#: accept a ``$ref`` (schema_prep inlines those before this rule is consulted).
_OPENAI_STRICT = SchemaRules(
    strip_keywords=frozenset(
        {
            "unevaluatedProperties",
            "unevaluatedItems",
            "dependentRequired",
            "dependentSchemas",
            "contentEncoding",
            "contentMediaType",
            "deprecated",
            "readOnly",
            "writeOnly",
        }
    ),
    require_items_object=True,
    fold_exclusive_bounds=True,
    reason="OpenAI-compatible gateways reject several 2020-12 keywords",
)


#: Anthropic's tool input_schema. Tolerant; only meta keywords are a problem,
#: and those are already removed by the provider-neutral normalize step.
_ANTHROPIC = SchemaRules(
    strip_keywords=frozenset({"deprecated"}),
    reason="Anthropic accepts near-full JSON Schema",
)


DIALECTS: dict[str, SchemaRules] = {
    "permissive": PERMISSIVE,
    "json_schema_2020": PERMISSIVE,
    "gemini": _GEMINI,
    "openai_strict": _OPENAI_STRICT,
    "anthropic": _ANTHROPIC,
}


def rules_for_dialect(dialect: str | None) -> SchemaRules:
    """Rules for *dialect*, or permissive defaults when unknown."""
    if not dialect:
        return PERMISSIVE
    return DIALECTS.get(dialect.strip().lower(), PERMISSIVE)


def register_dialect(name: str, rules: SchemaRules) -> None:
    """Add or replace a dialect at runtime, for a gateway not shipped here."""
    DIALECTS[name.strip().lower()] = rules


def with_reason(rules: SchemaRules, reason: str) -> SchemaRules:
    """Copy *rules* with a different explanation — for registering variants."""
    return replace(rules, reason=reason)


# Keeps `field` imported for downstream dataclass extension without a lint fix.
_ = field
