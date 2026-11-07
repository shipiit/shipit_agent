"""Finding calls written as JSON in the text: tagged, fenced, or bare, with relaxed parsing."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from shipit_agent.llms.base import ToolCall

from .arguments import (
    _arguments_fit_schema,
    _coerce_arguments,
    _plausible_argument_names,
)

_MAX_SCAN_CHARS = 200_000


# <tool_call>{...}</tool_call> (and singular/plural, any spacing/case)
_TAGGED_RE = re.compile(
    r"<tool_call>\s*(\{.*?\})\s*</tool_call>",
    re.IGNORECASE | re.DOTALL,
)


# ```json ... ``` fenced block (also bare ``` fences)
_FENCED_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


# Gemma 4 mapping form: ``<call>{"tool_name": {"arg": "x"}}</call>``.
_CALL_MAPPING_RE = re.compile(
    r"<call>\s*(\{.*?\})\s*</call>", re.IGNORECASE | re.DOTALL
)


def _qualifies(name: str, arguments: dict, schemas: Mapping[str, dict] | None) -> bool:
    """Schema check when the tool declares one, name check otherwise."""
    schema = (schemas or {}).get(name)
    if isinstance(schema, dict):
        return _arguments_fit_schema(arguments, schema)
    return _plausible_argument_names(arguments)


def _try_parse_call(
    raw: str, allowed: set[str], schemas: Mapping[str, dict] | None = None
) -> ToolCall | None:
    """Parse one candidate JSON object into a ToolCall if it qualifies."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    name = (
        data.get("name")
        or data.get("tool")
        or data.get("function")
        or data.get("action")
    )
    if isinstance(name, dict):  # {"function": {"name": ..., "arguments": ...}}
        arguments = name.get("arguments", {})
        name = name.get("name")
    else:
        arguments = data.get("arguments", data.get("parameters", {}))
    if not isinstance(name, str) or name not in allowed:
        return None
    coerced = _coerce_arguments(arguments)
    if coerced is None:
        return None
    if not _qualifies(name, coerced, schemas):
        return None
    return ToolCall(name=name, arguments=coerced)


def _try_parse_mapping_call(
    raw: str, allowed: set[str], schemas: Mapping[str, dict] | None = None
) -> ToolCall | None:
    """Parse ``{"tool_name": {arguments}}`` without guessing a tool."""
    data = _relaxed_json(raw)
    if not isinstance(data, dict) or len(data) != 1:
        return None
    name, arguments = next(iter(data.items()))
    if name not in allowed:
        return None
    coerced = _coerce_arguments(arguments)
    if coerced is None or not _qualifies(name, coerced, schemas):
        return None
    return ToolCall(name=name, arguments=coerced)


def _match_by_schema(
    raw: str, allowed: set[str], schemas: Mapping[str, dict]
) -> ToolCall | None:
    """Match a *nameless* arguments object to the tool it fits.

    A model that writes ``{"query": "qilin"}`` with no wrapper has chosen the
    arguments but omitted the name. Without this the call is simply lost. The
    tool is identified the only honest way available — by validating the keys
    against each declared schema — and an object that fits more than one tool
    is left alone rather than guessed at.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or not data:
        return None
    coerced = _coerce_arguments(data)
    if coerced is None:
        return None
    fits = [
        name
        for name in sorted(allowed)
        if isinstance(schemas.get(name), dict)
        and _arguments_fit_schema(coerced, schemas[name], strict_required=True)
    ]
    if len(fits) > 1:
        # Several tools accept the object; the one that declares every key the
        # model wrote is the call it meant ({"path", "content"} is write_file,
        # not read_file, which only knows "path"). Still a tie → leave it.
        complete = [
            name
            for name in fits
            if set(coerced) <= set((schemas[name].get("properties") or {}))
        ]
        fits = complete if len(complete) == 1 else fits
    if len(fits) != 1:
        return None
    return ToolCall(name=fits[0], arguments=coerced)


#: Unquoted identifier keys — `{query: "x"}` — the pseudo-JSON a weak model
#: writes when it serialises a call by hand. Quoting them is the entire
#: repair; values are left alone so a brace inside a string never corrupts.
_UNQUOTED_KEY_RE = re.compile(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_.-]*)\s*:")


_BARE_VALUE_RE = re.compile(r'(:\s*)([^"\'\[\]{},][^,}]*)')


def _quote_bare_value(match: re.Match[str]) -> str:
    """Quote a flat prose scalar while preserving real JSON primitives."""
    prefix, raw = match.group(1), match.group(2).strip()
    if raw in {"true", "false", "null"}:
        return prefix + raw
    try:
        float(raw)
    except ValueError:
        return prefix + json.dumps(raw)
    return prefix + raw


def _relaxed_json(raw: str) -> Any:
    """Parse JSON plus the two pseudo-JSON forms observed from weak models.

    Returns None when even the relaxed form does not parse — healing must
    promote calls, never invent them.
    """
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    keyed = _UNQUOTED_KEY_RE.sub(r'\1"\2":', raw)
    try:
        return json.loads(keyed)
    except json.JSONDecodeError:
        pass
    # Gemma can omit quotes around a natural-language scalar too:
    # ``{query:current weather in Paris}``. Restrict this to flat scalar
    # values; schema validation still decides whether the repaired call is
    # eligible for promotion.
    try:
        return json.loads(_BARE_VALUE_RE.sub(_quote_bare_value, keyed))
    except json.JSONDecodeError:
        return None


def _balanced_json_spans(text: str) -> list[tuple[int, int]]:
    """Spans of top-level {...} objects (string-aware, bounded)."""
    spans: list[tuple[int, int]] = []
    depth = 0
    start = -1
    in_string = False
    escape = False
    for i, ch in enumerate(text[:_MAX_SCAN_CHARS]):
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0 and start >= 0:
                spans.append((start, i + 1))
                start = -1
    return spans
