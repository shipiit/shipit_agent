"""Fitting a healed call's arguments to the tool's schema: names, types, and whether anything is there."""

from __future__ import annotations

import json
import re
from typing import Any

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
    return all(isinstance(key, str) and _ARGUMENT_NAME.match(key) for key in arguments)


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
    if strict_required and not properties:
        # A nameless object with keys can never be a call to a tool that takes
        # nothing. Without this every JSON object "fit" a no-argument tool:
        # a model's JSON answer was promoted to list_documents and removed from
        # the reply, and real nameless calls became ambiguous and were lost.
        return False
    if properties and not any(key in properties for key in arguments):
        return False
    if strict_required and not all(key in arguments for key in required):
        return False
    return True


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
