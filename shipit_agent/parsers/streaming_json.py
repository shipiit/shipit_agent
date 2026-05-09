"""Streaming partial JSON parser.

Parses incomplete JSON text (as it arrives token-by-token from an LLM)
into the best-effort partial Python object available *right now*.

Useful for live UIs that want to render structured output as it streams,
without waiting for the closing brace.

Example::

    from shipit_agent.parsers.streaming_json import parse_partial_json

    parse_partial_json('{"name": "Al')        # → {"name": "Al"}
    parse_partial_json('{"items": [1, 2, ')   # → {"items": [1, 2]}
    parse_partial_json('{"done": tr')         # → {"done": None}  (incomplete keyword dropped)

The parser is permissive: it closes any pending string, array, or object,
trims trailing partial values that wouldn't be valid JSON, and returns
``None`` only when no recoverable shape exists.
"""

from __future__ import annotations

import json
from typing import Any


def parse_partial_json(text: str) -> Any:
    """Parse possibly-incomplete JSON. Returns the best-effort object, or None.

    Tries ``json.loads(text)`` first. On failure, walks the input completing
    pending strings/arrays/objects and trimming trailing partial tokens.
    """
    text = text.strip()
    if not text:
        return None

    # Fast path — input is already valid JSON
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Find a JSON object/array start; ignore prose before it.
    start_idx = -1
    for i, c in enumerate(text):
        if c in "{[":
            start_idx = i
            break
    if start_idx == -1:
        # No JSON structure found
        return None
    text = text[start_idx:]

    completed = _complete(text)
    if completed is None:
        return None
    try:
        return json.loads(completed)
    except json.JSONDecodeError:
        # One more attempt — strip trailing partial token and retry
        trimmed = _trim_trailing_partial(text)
        if trimmed is None or trimmed == text:
            return None
        completed = _complete(trimmed)
        if completed is None:
            return None
        try:
            return json.loads(completed)
        except json.JSONDecodeError:
            return None


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _complete(text: str) -> str | None:
    """Walk the text once, return a string with all pending strings/arrays/objects closed.

    Returns None if the input is unrecoverable (e.g., empty after stripping).
    """
    stack: list[str] = []  # 'obj' | 'arr'
    in_string = False
    escape = False

    for c in text:
        if escape:
            escape = False
            continue
        if in_string:
            if c == "\\":
                escape = True
            elif c == '"':
                in_string = False
            continue
        if c == '"':
            in_string = True
        elif c == "{":
            stack.append("obj")
        elif c == "[":
            stack.append("arr")
        elif c == "}":
            if stack and stack[-1] == "obj":
                stack.pop()
        elif c == "]":
            if stack and stack[-1] == "arr":
                stack.pop()

    completion: list[str] = []
    if in_string:
        completion.append('"')

    # If a key/value position is half-typed (e.g. `{"a":` or `{"a": 1,`),
    # we need to remove the dangling fragment so the result parses.
    body = text + "".join(completion)
    body = _strip_dangling_value(body, stack)

    # Close brackets in reverse order
    closing = []
    for kind in reversed(stack):
        closing.append("}" if kind == "obj" else "]")
    return body + "".join(closing)


def _strip_dangling_value(text: str, stack: list[str]) -> str:
    """Drop any trailing `,` or `key:` that isn't followed by a complete value.

    Operates on the already-string-closed text.
    """
    # Walk backwards over whitespace
    end = len(text)
    while end > 0 and text[end - 1] in " \t\n\r":
        end -= 1
    if end == 0 or not stack:
        return text[:end]

    # If the last non-whitespace is a comma, drop it (trailing comma is invalid)
    if text[end - 1] == ",":
        return text[:end - 1]

    # Look for an unmatched `key:` pattern at the end
    if stack[-1] == "obj":
        # Pattern: "...,\s*\"key\"\s*:\s*<incomplete>"
        # We need to find the position of the last colon that's at the top level
        # of the current object, and check if everything after it is a complete value.
        i = end - 1
        depth = 0
        in_str = False
        esc = False
        last_colon = -1
        while i >= 0:
            c = text[i]
            if esc:
                esc = False
                i -= 1
                continue
            if in_str:
                if c == '"' and (i == 0 or text[i - 1] != "\\"):
                    in_str = False
                i -= 1
                continue
            if c == '"':
                in_str = True
                i -= 1
                continue
            if c in "}]":
                depth += 1
            elif c in "{[":
                if depth == 0:
                    break  # hit the opening of the current object
                depth -= 1
            elif c == ":" and depth == 0:
                last_colon = i
                break
            elif c == "," and depth == 0:
                break
            i -= 1

        if last_colon != -1:
            after_colon = text[last_colon + 1:end].strip()
            if not _is_complete_value(after_colon):
                # Drop "key" : <incomplete>
                # Find the `,` or `{` before the key
                j = last_colon - 1
                while j >= 0 and text[j] in " \t\n\r":
                    j -= 1
                # text[j] should be the closing quote of the key
                if j >= 0 and text[j] == '"':
                    # find opening quote
                    k = j - 1
                    while k >= 0:
                        if text[k] == '"' and (k == 0 or text[k - 1] != "\\"):
                            break
                        k -= 1
                    # k is opening quote of key; scan back for `,` or `{`
                    m = k - 1
                    while m >= 0 and text[m] in " \t\n\r":
                        m -= 1
                    if m >= 0 and text[m] in ",{":
                        if text[m] == ",":
                            return text[:m]
                        else:
                            return text[:m + 1]
        # In an array context, drop trailing partial value after last `,` or `[`
    if stack[-1] == "arr":
        i = end - 1
        depth = 0
        in_str = False
        last_sep = -1
        while i >= 0:
            c = text[i]
            if in_str:
                if c == '"' and (i == 0 or text[i - 1] != "\\"):
                    in_str = False
                i -= 1
                continue
            if c == '"':
                in_str = True
                i -= 1
                continue
            if c in "}]":
                depth += 1
            elif c in "{[":
                if depth == 0:
                    last_sep = i
                    break
                depth -= 1
            elif c == "," and depth == 0:
                last_sep = i
                break
            i -= 1
        if last_sep != -1:
            after_sep = text[last_sep + 1:end].strip()
            if after_sep and not _is_complete_value(after_sep):
                return text[:last_sep + 1] if text[last_sep] == "[" else text[:last_sep]

    return text[:end]


def _is_complete_value(s: str) -> bool:
    """Return True if `s` is a fully-formed JSON value."""
    if not s:
        return False
    try:
        json.loads(s)
        return True
    except json.JSONDecodeError:
        return False


def _trim_trailing_partial(text: str) -> str | None:
    """Aggressive fallback: drop the last token that prevents parsing."""
    text = text.rstrip()
    if not text:
        return None
    # Drop last char(s) until the prefix parses or we run out
    for cut in range(1, min(len(text), 40)):
        prefix = text[:-cut].rstrip().rstrip(",:")
        if prefix:
            return prefix
    return None
