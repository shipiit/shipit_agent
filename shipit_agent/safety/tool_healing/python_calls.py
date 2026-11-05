"""Finding calls written as Python (``name(key=value)``) or as a name followed by JSON."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from shipit_agent.llms.base import ToolCall

from .arguments import _coerce_arguments, _plausible_argument_names
from .json_calls import _MAX_SCAN_CHARS, _balanced_json_spans, _qualifies, _relaxed_json

#: `name(key="value", n=3)` — Python keyword-call syntax, Gemma's OTHER
#: hand-written form (its official docs teach `tool_code` blocks in this
#: shape, and it emits the bare call in prose too).
_PYCALL_KWARG_RE = re.compile(
    r"\s*([A-Za-z_][A-Za-z0-9_.-]*)\s*=\s*(.+?)\s*$", re.DOTALL
)


def _split_call_args(body: str) -> list[str]:
    """Split a call body on commas outside quotes/brackets."""
    parts: list[str] = []
    depth = 0
    quote = ""
    start = 0
    for i, ch in enumerate(body):
        if quote:
            if ch == quote and body[i - 1 : i] != "\\":
                quote = ""
            continue
        if ch in "\"'":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(body[start:i])
            start = i + 1
    parts.append(body[start:])
    return [p for p in parts if p.strip()]


def _parse_python_kwargs(body: str) -> dict | None:
    """``city="Paris", n=3`` → ``{"city": "Paris", "n": 3}``, or None."""
    if not body.strip():
        return None
    arguments: dict[str, Any] = {}
    for part in _split_call_args(body):
        match = _PYCALL_KWARG_RE.match(part)
        if match is None:
            return None
        key, raw = match.group(1), match.group(2).strip()
        value = _relaxed_json(raw)
        if value is None:
            if (raw[:1] == raw[-1:] and raw[:1] in "\"'") and len(raw) >= 2:
                value = raw[1:-1]
            else:
                value = raw
        arguments[key] = value
    return arguments or None


def _python_style_calls(
    text: str,
    allowed: set[str],
) -> list[tuple[tuple[int, int], dict]]:
    """Spans and arguments of ``tool_name(key="value")`` calls in prose."""
    found: list[tuple[tuple[int, int], dict]] = []
    # `\b` is the wrong boundary here. Gemma via bedrock-mantle glues a
    # non-ASCII marker token straight onto the name — observed live::
    #
    #     I will check the current weather in Paris.\n\n逃weather_lookup(city='Paris')展开提示符
    #
    # Python's `\b` is Unicode-aware, so `逃` and `w` are *both* word
    # characters and no boundary exists between them: the call never matched
    # and the turn ended as narration. `_name_adjacent_calls` already tolerates
    # this for the brace form (it matches on `prefix.endswith(name)`), which is
    # why the same run healed `联tool_search{...}` but not this.
    #
    # An explicit "not preceded by an ASCII identifier character" still refuses
    # to match a genuine longer identifier like `my_weather_lookup(...)`, which
    # is the only thing `\b` was buying.
    # OpenAI-compatible providers sometimes namespace a declared function as
    # ``tool_<declared_name>`` when writing it in prose. Resolve that generic
    # namespace back to the exact advertised name; arbitrary prefixes such as
    # ``my_<name>`` remain rejected. Identity still comes from the allow-list.
    aliases = {alias: name for name in allowed for alias in (name, f"tool_{name}")}
    pattern = re.compile(
        r"(?<![A-Za-z0-9_])("
        + "|".join(re.escape(n) for n in sorted(aliases, key=len, reverse=True))
        + r")\s*\(([^()]*)\)"
    )
    for match in pattern.finditer(text[:_MAX_SCAN_CHARS]):
        arguments = _parse_python_kwargs(match.group(2))
        if arguments is not None:
            found.append(
                (
                    match.span(),
                    {
                        "name": aliases[match.group(1)],
                        "arguments": arguments,
                    },
                )
            )
    return found


def _name_adjacent_calls(
    text: str,
    allowed: set[str],
    schemas: Mapping[str, dict] | None,
) -> list[tuple[tuple[int, int], ToolCall]]:
    """Calls written as ``tool_name{...}`` / ``tool_name({...})`` in prose.

    Observed live from Gemma via bedrock-mantle::

        I will search for the correct tool.\\n\\n联tool_search{query: "get
        current weather for a city"}

    The tool name is glued to a pseudo-JSON object (often with unquoted
    keys, sometimes behind a non-ASCII verb). Neither the tagged, fenced,
    nor bare-JSON forms match it, so the turn ends with narration instead
    of the call. The name must be one of *allowed* and the arguments must
    fit the tool's schema — same bar as every other healed form.
    """
    found: list[tuple[tuple[int, int], ToolCall]] = []
    for start, end in _balanced_json_spans(text):
        prefix = text[:start].rstrip()
        opened = prefix.endswith("(")
        if opened:
            prefix = prefix[:-1].rstrip()
        # Markdown tables and provider wrappers commonly put punctuation
        # between the declared name and its argument object, for example
        # ``| crm_open_tickets | {"company":"ACME"} |``. Permit only
        # non-word separators on the same line. Identity still comes from the
        # advertised name and arguments still have to pass schema validation.
        line_prefix = prefix.rsplit("\n", 1)[-1]
        alternatives = "|".join(
            re.escape(n) for n in sorted(allowed, key=len, reverse=True)
        )
        name_match = re.search(
            rf"(?<![A-Za-z0-9_])({alternatives})[^A-Za-z0-9_{{}}]*$",
            line_prefix,
        )
        name = name_match.group(1) if name_match else None
        if name is None:
            continue
        data = _relaxed_json(text[start:end])
        if not isinstance(data, dict):
            continue
        coerced = _coerce_arguments(data)
        if coerced is None:
            continue
        # The model wrote the tool's literal name against the brace, so
        # identity is not in question — only the arguments are. Prefer the
        # schema bar, but accept identifier-shaped keys the schema does not
        # declare (observed: ``weather_lookup{location: "Paris"}`` from a
        # model that had only the tool's NAME — deferred schemas invite an
        # invented argument). Promoting hands the call to the argument gate
        # and the tool, whose corrective errors teach the model the real
        # parameter; refusing buries the call in prose and ends the run.
        # Junk keys (``{",'query'": ""}``) still fail both bars.
        if not (
            _qualifies(name, coerced, schemas) or _plausible_argument_names(coerced)
        ):
            continue
        line_start = len(prefix) - len(line_prefix)
        span_start = line_start + name_match.start(1)
        span_end = end
        if opened and text[end : end + 1] == ")":
            span_end += 1
        found.append(((span_start, span_end), ToolCall(name=name, arguments=coerced)))
    return found
