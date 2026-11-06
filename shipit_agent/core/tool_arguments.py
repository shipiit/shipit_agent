"""Telling a tool call that lacks an argument apart from a tool that is broken."""

from __future__ import annotations

import re
from typing import Any


def declared_parameters(tool: Any) -> tuple[set[str], list[str]]:
    """``(all parameter names, required names)`` from a tool's schema."""
    try:
        schema = tool.schema() or {}
        function = schema.get("function", schema)
        parameters = function.get("parameters") or {}
        return (
            set((parameters.get("properties") or {}).keys()),
            list(parameters.get("required") or []),
        )
    except Exception:
        return set(), []


def missing_argument(
    exc: Exception, supplied: dict[str, Any], declared: set[str]
) -> str | None:
    """The argument name a KeyError/TypeError is complaining about.

    Returns ``None`` when the exception is about something else. A tool with a
    genuine bug must still surface as a failure — relabelling it as the
    model's mistake would send the model retrying a call that was fine.
    """
    if isinstance(exc, KeyError):
        key = exc.args[0] if exc.args else None
        if not isinstance(key, str) or key in supplied:
            return None
        # It must be a parameter the tool *declares*. A KeyError from a tool's
        # own internal dict lookup names something the caller was never asked
        # for, and that is a bug in the tool.
        return key if key in declared else None

    text = str(exc)
    if "required" not in text or "argument" not in text:
        return None
    match = re.search(r"argument:? \'([^\']+)\'", text)
    if match is None:
        return None
    name = match.group(1)
    return name if not declared or name in declared else None


def missing_argument_message(name: str, missing: str, required: list[str]) -> str:
    """What the model is told, including which arguments the tool requires.

    Listing them all means the next turn can supply everything, rather than
    discovering them one at a time over three round trips.
    """
    detail = f" Required: {', '.join(required)}." if required else ""
    return (
        f"Error: {name} needs the '{missing}' argument, which was not "
        f"provided.{detail} Call it again with that argument."
    )
