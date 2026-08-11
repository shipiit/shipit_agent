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
import ast
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
# Gemma-observed compact call syntax: ```call:read_file{path:app.py}```.
# Keep the body to one line and disallow nested objects; complex edits must use
# the provider's structured channel rather than an increasingly permissive
# text parser.
_RELAXED_CALL_RE = re.compile(
    r"(?:```)?call:(?P<name>[A-Za-z_][A-Za-z0-9_.-]*)"
    r"\{(?P<body>[^{}\r\n]+)\}(?:```)?",
    re.IGNORECASE,
)
_AT_CALL_RE = re.compile(
    r"(?m)^[ \t]*@(?P<name>[A-Za-z_][A-Za-z0-9_.-]*)"
    r"\((?P<body>[^()\r\n]*)\)[ \t]*$"
)
_BACKTICK_CALL_RE = re.compile(
    r"(?m)^[ \t>]*`(?P<name>[A-Za-z_][A-Za-z0-9_.-]*)"
    r"\((?P<body>[^()\r\n]*)\)`[ \t]*$"
)
# Bare Python-style fallback emitted by open-weight models after a provider
# rejects their native tool-call body: ``read_file(path="app.py")``.  The
# name must still be in the runtime allowlist and every keyword is checked
# against that tool's schema before promotion.
_DECLARED_CALL_RE = re.compile(
    r"(?<![A-Za-z0-9_`@])(?P<name>[A-Za-z_][A-Za-z0-9_.-]*)"
    r"\((?P<body>[^()\r\n]*)\)"
)
# XML/JSX attribute shape, observed live from Gemma when the provider
# rejected its native tool-call body: ``bash command="ls" />``. It is a real
# call — the name is declared, the argument is right — but no JSON, Python or
# markdown parser recognises it, so every layer dropped it and the run made
# zero tool calls while spending 55,821 prompt tokens.
#
# The closing ``>`` is required. Without it this would match ordinary prose
# that happens to contain ``word key="value"``, and healing must not invent a
# call out of a sentence.
_ATTR_PAIR = (
    r"[A-Za-z_][A-Za-z0-9_.-]*\s*=\s*(?:\"[^\"]*\"|'[^']*')"
)
_ATTR_PAIR_RE = re.compile(_ATTR_PAIR)
_ATTR_CALL_RE = re.compile(
    r"</?(?P<name>[A-Za-z_][A-Za-z0-9_.-]*)"
    r"(?P<body>(?:\s+" + _ATTR_PAIR + r")+)\s*/?>"
    r"|(?:^|(?<=[\s`]))(?P<name2>[A-Za-z_][A-Za-z0-9_.-]*)"
    r"(?P<body2>(?:\s+" + _ATTR_PAIR + r")+)\s*/?>",
    re.MULTILINE,
)


def _attributes_to_keywords(body: str) -> str:
    """``command="ls" limit="3"`` -> ``command="ls", limit="3"``.

    Turns an attribute list into the keyword body ``_try_parse_at_call``
    already knows how to read safely, so this shape reuses the same AST
    parse and the same schema validation rather than a second code path.
    """
    return ", ".join(match.group(0) for match in _ATTR_PAIR_RE.finditer(body))


_TABLE_CALL_RE = re.compile(
    r"(?m)^\|\s*`?(?P<name>[A-Za-z_][A-Za-z0-9_.-]*)`?\s*\|"
    r"(?P<body>[^\r\n|]+)\|\s*$"
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


def coerce_argument_values(arguments: dict, schema: dict) -> dict:
    """Coerce encoded arrays/objects only when the JSON Schema requests it."""
    properties = schema.get("properties") or {}
    coerced = dict(arguments)
    for name, value in arguments.items():
        declaration = properties.get(name)
        if not isinstance(declaration, dict) or not isinstance(value, str):
            continue
        expected = declaration.get("type")
        if expected not in {"array", "object"}:
            continue
        parsed = _coerce_value(value)
        if (expected == "array" and isinstance(parsed, list)) or (
            expected == "object" and isinstance(parsed, dict)
        ):
            coerced[name] = parsed
    return coerced


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
    if strict_required and not properties:
        return False
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


def _parse_relaxed_scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        raise ValueError("empty argument")
    for parser in (json.loads, ast.literal_eval):
        try:
            return parser(value)
        except (ValueError, SyntaxError, json.JSONDecodeError):
            continue
    return value.strip("`\"'")


def _try_parse_relaxed_call(
    name: str,
    body: str,
    allowed: set[str],
    schemas: Mapping[str, dict] | None,
) -> ToolCall | None:
    """Parse a bounded ``call:name{key:value}`` model fallback."""
    if name not in allowed:
        return None
    arguments: dict[str, Any] = {}
    for field in body.split(","):
        separator = ":" if ":" in field else "=" if "=" in field else None
        if separator is None:
            return None
        key, value = field.split(separator, 1)
        key = key.strip()
        if not _ARGUMENT_NAME.fullmatch(key) or key in arguments:
            return None
        try:
            arguments[key] = _parse_relaxed_scalar(value)
        except ValueError:
            return None
    if not _qualifies(name, arguments, schemas):
        return None
    return ToolCall(name=name, arguments=arguments)


def _try_parse_at_call(
    name: str,
    body: str,
    allowed: set[str],
    schemas: Mapping[str, dict] | None,
) -> ToolCall | None:
    """Parse explicit ``@tool(key=value)`` without evaluating code."""
    if name not in allowed:
        return None
    try:
        # Parse only the keyword body under a fixed safe identifier. Tool
        # names may be namespaced (or contain punctuation) and are validated
        # separately against ``allowed``; they must never become executable
        # Python source.
        expression = ast.parse(f"_tool_({body})", mode="eval").body
    except SyntaxError:
        return None
    if not isinstance(expression, ast.Call) or expression.args:
        return None
    arguments: dict[str, Any] = {}
    for keyword in expression.keywords:
        if keyword.arg is None or keyword.arg in arguments:
            return None
        try:
            arguments[keyword.arg] = ast.literal_eval(keyword.value)
        except (ValueError, TypeError):
            return None
    if not _qualifies(name, arguments, schemas):
        return None
    return ToolCall(name=name, arguments=arguments)


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
        for match in _RELAXED_CALL_RE.finditer(text):
            call = _try_parse_relaxed_call(
                match.group("name"),
                match.group("body"),
                allowed_names,
                schemas,
            )
            if call is not None:
                calls.append(call)
                consumed.append(match.span())

    if not calls:
        for match in _AT_CALL_RE.finditer(text):
            call = _try_parse_at_call(
                match.group("name"),
                match.group("body"),
                allowed_names,
                schemas,
            )
            if call is not None:
                calls.append(call)
                consumed.append(match.span())

    if not calls:
        for match in _BACKTICK_CALL_RE.finditer(text):
            call = _try_parse_at_call(
                match.group("name"),
                match.group("body"),
                allowed_names,
                schemas,
            )
            if call is not None:
                calls.append(call)
                consumed.append(match.span())

    if not calls:
        for match in _DECLARED_CALL_RE.finditer(text):
            call = _try_parse_at_call(
                match.group("name"),
                match.group("body"),
                allowed_names,
                schemas,
            )
            if call is not None:
                calls.append(call)
                consumed.append(match.span())

    if not calls:
        for match in _TABLE_CALL_RE.finditer(text):
            call = _try_parse_at_call(
                match.group("name"),
                match.group("body").replace("`", "").strip(),
                allowed_names,
                schemas,
            )
            if call is not None:
                calls.append(call)
                consumed.append(match.span())

    if not calls:
        for match in _ATTR_CALL_RE.finditer(text):
            name = match.group("name") or match.group("name2")
            body = match.group("body") or match.group("body2")
            call = _try_parse_at_call(
                name, _attributes_to_keywords(body), allowed_names, schemas
            )
            if call is not None:
                calls.append(call)
                consumed.append(match.span())

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

    # Repeated fallback prose often contains the same rejected call several
    # times. Remove every promoted span from the visible draft, but execute
    # an identical declared call only once.
    unique_calls: list[ToolCall] = []
    seen_calls: set[tuple[str, str]] = set()
    for call in calls:
        fingerprint = (
            call.name,
            json.dumps(call.arguments, sort_keys=True, default=str),
        )
        if fingerprint not in seen_calls:
            seen_calls.add(fingerprint)
            unique_calls.append(call)

    # Remove exactly the promoted spans, keep everything else.
    remaining: list[str] = []
    cursor = 0
    for start, end in sorted(consumed):
        remaining.append(text[cursor:start])
        cursor = end
    remaining.append(text[cursor:])
    cleaned = "".join(remaining).strip()
    return cleaned, unique_calls
