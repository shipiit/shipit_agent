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

from .llms.base import ToolCall

_MAX_SCAN_CHARS = 200_000

# <tool_call>{...}</tool_call> (and singular/plural, any spacing/case)
_TAGGED_RE = re.compile(
    r"<tool_call>\s*(\{.*?\})\s*</tool_call>",
    re.IGNORECASE | re.DOTALL,
)
# ```json ... ``` fenced block (also bare ``` fences)
_FENCED_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _try_parse_call(raw: str, allowed: set[str]) -> ToolCall | None:
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
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            return None
    if not isinstance(arguments, dict):
        return None
    return ToolCall(name=name, arguments=arguments)


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


def heal_tool_calls(
    text: str, allowed_names: set[str]
) -> tuple[str, list[ToolCall]]:
    """Extract promotable tool calls from ``text``.

    Returns ``(remaining_text, calls)``. When no call qualifies, the text
    comes back byte-identical and ``calls`` is empty.
    """
    if not text or not allowed_names or len(text) > _MAX_SCAN_CHARS:
        return text, []

    calls: list[ToolCall] = []
    consumed: list[tuple[int, int]] = []

    for pattern in (_TAGGED_RE, _FENCED_RE):
        for match in pattern.finditer(text):
            call = _try_parse_call(match.group(1), allowed_names)
            if call is not None:
                calls.append(call)
                consumed.append(match.span())

    if not calls:
        # Fallback: bare top-level JSON objects shaped like a call.
        for start, end in _balanced_json_spans(text):
            call = _try_parse_call(text[start:end], allowed_names)
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
    return cleaned, calls
