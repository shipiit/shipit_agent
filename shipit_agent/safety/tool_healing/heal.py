"""Healing a response: promote the calls found in its text, and merge calls split across steps."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from shipit_agent.llms.base import ToolCall

from .arguments import (
    _arguments_fit_schema,
    _coerce_arguments,
    _plausible_argument_names,
)
from .json_calls import (
    _CALL_MAPPING_RE,
    _FENCED_RE,
    _MAX_SCAN_CHARS,
    _TAGGED_RE,
    _balanced_json_spans,
    _match_by_schema,
    _qualifies,
    _try_parse_call,
    _try_parse_mapping_call,
)
from .python_calls import _name_adjacent_calls, _python_style_calls
from .xml_calls import _tagged_attribute_calls, _xml_style_calls


def merge_split_calls(
    calls: list[ToolCall], schemas: Mapping[str, dict] | None = None
) -> list[ToolCall]:
    """Collapse calls a model split across several single-argument invocations.

    A weaker model asked for ``get_entity(domain=…, entity=…, entity_id=…)``
    sometimes emits three separate calls, one argument each — the multi-arg
    failure. When several calls name the SAME tool and their argument keys do
    not overlap, they are almost certainly one logical call taken apart, so
    union the arguments back together (first value wins on the impossible tie).

    Kept deliberately conservative: calls whose keys DO overlap are genuinely
    distinct invocations (two searches with different ``query``) and are left
    untouched; and when a schema is known, a merge that would not fit it is
    abandoned rather than forced. Order is preserved by the first appearance of
    each tool name.
    """
    if len(calls) < 2:
        return calls
    order: list[str] = []
    grouped: dict[str, list[ToolCall]] = {}
    for call in calls:
        grouped.setdefault(call.name, [])
        if call.name not in order:
            order.append(call.name)
        grouped[call.name].append(call)

    merged: list[ToolCall] = []
    for name in order:
        group = grouped[name]
        if len(group) < 2:
            merged.extend(group)
            continue
        union: dict[str, Any] = {}
        keys_disjoint = True
        for call in group:
            args = call.arguments if isinstance(call.arguments, dict) else {}
            if any(key in union for key in args):
                keys_disjoint = False
                break
            union.update(args)
        schema = (schemas or {}).get(name)
        fits = (
            _arguments_fit_schema(union, schema) if isinstance(schema, dict) else True
        )
        if keys_disjoint and fits and union:
            merged.append(ToolCall(name=name, arguments=union))
        else:
            merged.extend(group)
    return merged


def heal_tool_calls(
    text: str,
    allowed_names: set[str],
    *,
    schemas: Mapping[str, dict] | None = None,
) -> tuple[str, list[ToolCall]]:
    """Extract promotable tool calls from ``text``.

    ``schemas`` maps a tool name to its JSON-Schema ``parameters`` object.
    When supplied, arguments are validated against the tool's own
    declaration rather than merely inspected for identifier-shaped keys,
    and a nameless arguments object can be matched to the tool it fits.
    Omitting it preserves the previous, weaker behaviour exactly.

    Returns ``(remaining_text, calls)``. When no call qualifies, the text
    comes back byte-identical and ``calls`` is empty.
    """
    if not text or not allowed_names or len(text) > _MAX_SCAN_CHARS:
        return text, []

    calls: list[ToolCall] = []
    consumed: list[tuple[int, int]] = []

    for match in _CALL_MAPPING_RE.finditer(text):
        call = _try_parse_mapping_call(match.group(1), allowed_names, schemas)
        if call is not None:
            calls.append(call)
            consumed.append(match.span())

    # Anthropic `<function_calls><invoke>` XML — an explicit, high-confidence
    # form, so recovered alongside the other tagged shapes rather than as a
    # last resort. One block can carry several invokes.
    for span, call in _xml_style_calls(text, allowed_names, schemas):
        calls.append(call)
        if span not in consumed:
            consumed.append(span)

    for span, call in _tagged_attribute_calls(text, allowed_names, schemas):
        calls.append(call)
        if span not in consumed:
            consumed.append(span)

    for pattern in (_TAGGED_RE, _FENCED_RE):
        for match in pattern.finditer(text):
            call = _try_parse_call(match.group(1), allowed_names, schemas)
            if call is not None:
                calls.append(call)
                consumed.append(match.span())

    if not calls:
        # Fallback: bare top-level JSON objects shaped like a call.
        for start, end in _balanced_json_spans(text):
            call = _try_parse_call(text[start:end], allowed_names, schemas)
            if call is not None:
                calls.append(call)
                consumed.append((start, end))

    if not calls:
        # A declared tool name glued to a (pseudo-)JSON object in prose.
        for span, call in _name_adjacent_calls(text, allowed_names, schemas):
            calls.append(call)
            consumed.append(span)

    if not calls:
        # Python keyword-call syntax: `weather_lookup(city="Paris")`. Same
        # confidence argument as the brace form — the model wrote the tool's
        # literal name — and the same bars on the parsed arguments.
        for span, parsed in _python_style_calls(text, allowed_names):
            coerced = _coerce_arguments(parsed["arguments"])
            if coerced is None:
                continue
            name = parsed["name"]
            if not (
                _qualifies(name, coerced, schemas) or _plausible_argument_names(coerced)
            ):
                continue
            calls.append(ToolCall(name=name, arguments=coerced))
            consumed.append(span)

    if not calls and schemas:
        # Last resort: an arguments object with no name, identified by the
        # schema it satisfies. Only ever reached once every named form has
        # failed, so a well-formed call is never displaced by a guess.
        for pattern in (_TAGGED_RE, _FENCED_RE):
            for match in pattern.finditer(text):
                call = _match_by_schema(match.group(1), allowed_names, schemas)
                if call is not None:
                    calls.append(call)
                    consumed.append(match.span())
        if not calls:
            for start, end in _balanced_json_spans(text):
                call = _match_by_schema(text[start:end], allowed_names, schemas)
                if call is not None:
                    calls.append(call)
                    consumed.append((start, end))

    if not calls:
        return text, []

    # Remove exactly the promoted spans, keep everything else.
    remaining: list[str] = []
    cursor = 0
    for start, end in sorted(consumed):
        remaining.append(text[cursor:start])
        cursor = end
    remaining.append(text[cursor:])
    cleaned = "".join(remaining).strip()
    # A model that split one call across several single-argument invocations
    # gets them reassembled here (same tool, disjoint keys → one call).
    return cleaned, merge_split_calls(calls, schemas)
