"""Self-healing tool calls — promote text-emitted calls to structured ones.

Small open-weight models frequently write a tool call into their TEXT
instead of the structured tool-call field::

    <tool_call>{"name": "web_search", "arguments": {"query": "..."}}</tool_call>
    ```json
    {"name": "read_file", "arguments": {"path": "app.py"}}
    ```

The runtime heals these on the RESPONSE side only, under strict invariants
(modeled on the behavior of production healing layers):

- only names in the agent's DECLARED tool set are promoted;
- promotion removes exactly the promoted span — every other byte of the
  model's text is preserved;
- unparseable or undeclared blocks are left as plain text, never dropped;
- healing never issues extra generation.

Disable per-agent with ``Agent(heal_tool_calls=False)``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from .llms.base import ToolCall

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


#: A parameter name in any real tool schema is an identifier.
_ARGUMENT_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]*$")


def _plausible_argument_names(arguments: dict) -> bool:
    """Whether these keys could be a tool's actual parameters.

    Healing exists to rescue a call a model wrote as prose. It must not
    rescue one so mangled that the arguments are wreckage: observed from
    Gemma 4, ``{"))Query:Qilin": "qilin"}`` and ``{":[{": ","}``. Both
    named a real tool, so both were promoted, and both reached the tool
    with the actual parameter missing.

    That is worse than not healing at all. A tool whose required argument
    is absent either errors — recoverable — or, if the argument is
    optional, treats "no filter" as "everything" and returns the whole
    corpus. The model then answers confidently from data that has nothing
    to do with the question, and every layer reports success.

    Rejecting here sends the text back as prose, which is what it was.
    """
    return all(
        isinstance(key, str) and _ARGUMENT_NAME.match(key)
        for key in arguments
    )


def _coerce_value(value: Any) -> Any:
    """Parse a JSON-string value into its Python equivalent.

    Models routinely emit a list-valued parameter as a string —
    ``{"queries": '["a", "b"]'}`` instead of ``{"queries": ["a", "b"]}``.
    Only text that is *wholly* a JSON array or object is parsed, so a
    string that merely contains a bracket is returned untouched.
    """
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not (
        (stripped.startswith("[") and stripped.endswith("]"))
        or (stripped.startswith("{") and stripped.endswith("}"))
    ):
        return value
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return value


def _coerce_arguments(arguments: Any) -> dict | None:
    """Normalise an arguments payload into a dict, unwrapping encodings.

    Handles the double-encoded case — ``'"{\\"query\\": \\"x\\"}"'``, a JSON
    string literal *of* an object — by parsing until a dict falls out or the
    shape is clearly not one.
    """
    for _ in range(2):
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                return None
        else:
            break
    if not isinstance(arguments, dict):
        return None
    return {key: _coerce_value(value) for key, value in arguments.items()}


def _arguments_fit_schema(
    arguments: dict, schema: dict, *, strict_required: bool = False
) -> bool:
    """Whether these arguments could be a real call to this tool.

    Checks, all from the tool's own declaration:

    - **empty arguments against a tool that requires some** are refused. This
      is the ``search_echo({})`` failure: a tool whose filter is optional
      reads "no filter" as "everything" and returns its entire corpus, and
      the model then answers confidently from data unrelated to the question
      while every layer reports success.
    - **at least one supplied key must be a declared property.** Catches the
      plausible-looking misspelling (``quary`` for ``query``) that an
      identifier regex waves through.

    Full ``required`` coverage is only enforced under *strict_required*, used
    when matching a nameless object where a confident identification is the
    whole point. It is deliberately NOT enforced for a call that named its
    tool, because real schemas over-declare ``required`` — shipit's own
    ``FunctionTool`` listed ``**kwargs`` there until this was written — and
    discarding a good call over a bad declaration is the worse failure.

    Undeclared extras never disqualify a call; models add stray keys.
    """
    properties = schema.get("properties") or {}
    required = schema.get("required") or []
    if not arguments:
        return not required
    if properties and not any(key in properties for key in arguments):
        return False
    if strict_required and not all(key in arguments for key in required):
        return False
    return True


def _qualifies(
    name: str, arguments: dict, schemas: Mapping[str, dict] | None
) -> bool:
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
    name = data.get("name") or data.get("tool") or data.get("function")
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
    if len(fits) != 1:
        return None
    return ToolCall(name=fits[0], arguments=coerced)


#: Unquoted identifier keys — `{query: "x"}` — the pseudo-JSON a weak model
#: writes when it serialises a call by hand. Quoting them is the entire
#: repair; values are left alone so a brace inside a string never corrupts.
_UNQUOTED_KEY_RE = re.compile(r'([{,]\s*)([A-Za-z_][A-Za-z0-9_.-]*)\s*:')
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
    aliases = {
        alias: name
        for name in allowed
        for alias in (name, f"tool_{name}")
    }
    pattern = re.compile(
        r"(?<![A-Za-z0-9_])(" + "|".join(
            re.escape(n) for n in sorted(aliases, key=len, reverse=True)
        )
        + r")\s*\(([^()]*)\)"
    )
    for match in pattern.finditer(text[:_MAX_SCAN_CHARS]):
        arguments = _parse_python_kwargs(match.group(2))
        if arguments is not None:
            found.append((match.span(), {
                "name": aliases[match.group(1)], "arguments": arguments,
            }))
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
            _qualifies(name, coerced, schemas)
            or _plausible_argument_names(coerced)
        ):
            continue
        line_start = len(prefix) - len(line_prefix)
        span_start = line_start + name_match.start(1)
        span_end = end
        if opened and text[end:end + 1] == ")":
            span_end += 1
        found.append(((span_start, span_end), ToolCall(name=name, arguments=coerced)))
    return found


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


#: Junk a model wraps around an argument name when it mangles a tool call.
#: Observed from Gemma 4 as the key ``",'query'"`` — the parameter name is
#: in there, buried in the punctuation of the call it failed to serialise.
_KEY_JUNK = " \t\r\n,:;'\"[]{}()<>|/\\`*-="


def repair_argument_names(arguments: dict, schema: dict) -> dict:
    """Rename mangled argument keys that clean up to a declared parameter.

    A structured tool call arrives from the provider already parsed, so the
    healing path never inspects it — yet a weak model can produce arguments
    just as broken there. Observed live: ``search_echo`` called with
    ``{",'query'": ""}``. The tool saw no ``query``, treated "no filter" as
    "everything", and returned its entire corpus; the model then answered
    about the corpus rather than the question.

    Only renames when the cleaned key is an exact declared property and the
    real name is not already present, so this cannot invent or overwrite an
    argument the model actually supplied.
    """
    properties = schema.get("properties") or {}
    if not properties:
        return arguments
    repaired: dict = {}
    for key, value in arguments.items():
        if isinstance(key, str) and key not in properties:
            cleaned = key.strip(_KEY_JUNK)
            if cleaned in properties and cleaned not in arguments:
                repaired[cleaned] = value
                continue
        repaired[key] = value
    return repaired


def _has_value(value: Any) -> bool:
    """Whether an argument actually carries something."""
    if value is None:
        return False
    if isinstance(value, (str, list, dict, tuple, set)):
        return bool(value)
    return True


def call_carries_nothing(arguments: dict, schema: dict) -> list[str]:
    """Required names, when a call to this tool supplies *no* usable argument.

    Returns ``[]`` — meaning "let it run" — unless the tool declares required
    parameters and not one declared parameter arrives with a value. That is
    the shape worth refusing: asking a tool for everything it has.

    Deliberately not a per-parameter ``required`` check. A schema's required
    list does not hold for every valid invocation — a tool with modes
    (``sub_agent`` dispatching work versus collecting results) legitimately
    omits what another mode demands — and rejecting those would break working
    calls to fix a different problem. A call that supplies at least one real
    argument has expressed an intent, so it runs.

    A required parameter present but empty counts as absent: an empty query
    is exactly what a tool reads as "no filter".
    """
    required = schema.get("required") or []
    if not required:
        return []
    properties = schema.get("properties") or {}
    for key, value in arguments.items():
        if (key in properties or not properties) and _has_value(value):
            return []
    return list(required)


def schemas_from_tools(tools: Any) -> dict[str, dict]:
    """Map tool name → its JSON-Schema ``parameters`` object.

    Tools declare themselves in OpenAI function format, but not uniformly —
    some nest under ``function``, some expose ``parameters`` at the top
    level. A tool whose schema cannot be read is simply absent from the
    result, which downgrades healing to the name check for that tool rather
    than failing the run.
    """
    schemas: dict[str, dict] = {}
    for tool in tools:
        try:
            raw = tool.schema()
        except Exception:  # a broken schema must not break the turn
            continue
        if not isinstance(raw, dict):
            continue
        function = raw.get("function")
        body = function if isinstance(function, dict) else raw
        name = body.get("name") or getattr(tool, "name", None)
        parameters = body.get("parameters")
        if isinstance(name, str) and isinstance(parameters, dict):
            schemas[name] = parameters
    return schemas


# Anthropic/Claude-lineage XML tool-call form, which some models emit
# unprompted even on other providers::
#
#     <function_calls>
#     <invoke name="get_entity">
#     <parameter name="domain">ransomlook</parameter>
#     <parameter name="entity">groups</parameter>
#     </invoke>
#     </function_calls>
#
# Each `<invoke>` is one call; each `<parameter>` one argument. Values are
# coerced (a JSON array written as text becomes a list) and the call must clear
# the same allow-list + schema bar as every other healed form.
_XML_INVOKE_RE = re.compile(
    r"<invoke\s+name\s*=\s*[\"']([A-Za-z_][A-Za-z0-9_.-]*)[\"']\s*>(.*?)</invoke>",
    re.IGNORECASE | re.DOTALL,
)
_XML_PARAM_RE = re.compile(
    r"<parameter\s+name\s*=\s*[\"']([A-Za-z_][A-Za-z0-9_.-]*)[\"']\s*>(.*?)</parameter>",
    re.IGNORECASE | re.DOTALL,
)
_XML_BLOCK_RE = re.compile(
    r"<function_calls>.*?</function_calls>", re.IGNORECASE | re.DOTALL
)


def _xml_style_calls(
    text: str,
    allowed: set[str],
    schemas: Mapping[str, dict] | None,
) -> list[tuple[tuple[int, int], ToolCall]]:
    """Calls written in the Anthropic `<function_calls><invoke>` XML form."""
    found: list[tuple[tuple[int, int], ToolCall]] = []
    for block in _XML_BLOCK_RE.finditer(text[:_MAX_SCAN_CHARS]):
        for invoke in _XML_INVOKE_RE.finditer(block.group(0)):
            name = invoke.group(1)
            if name not in allowed:
                continue
            arguments: dict[str, Any] = {}
            for param in _XML_PARAM_RE.finditer(invoke.group(2)):
                arguments[param.group(1)] = _coerce_value(param.group(2).strip())
            if not _qualifies(name, arguments, schemas):
                continue
            found.append((block.span(), ToolCall(name=name, arguments=arguments)))
    return found


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
            _arguments_fit_schema(union, schema)
            if isinstance(schema, dict)
            else True
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
                _qualifies(name, coerced, schemas)
                or _plausible_argument_names(coerced)
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
