"""Finding calls written as XML: ``<invoke>``/``<parameter>`` blocks and tags with attributes."""

from __future__ import annotations

import re
from collections.abc import Mapping
from html.parser import HTMLParser
from typing import Any

from shipit_agent.llms.base import ToolCall

from .arguments import _coerce_value
from .json_calls import _MAX_SCAN_CHARS, _qualifies

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


class _TaggedCallParser(HTMLParser):
    """Parse generic ``<call:name key="value"/>`` envelopes.

    This is a compatibility decoder for a response *shape*, not a provider,
    model, or tool-name special case. The standard-library parser owns
    quoting and entity decoding; promotion remains controlled exclusively by
    the agent's advertised tool names and JSON schemas.
    """

    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=True)
        self._line_offsets = [0]
        self.calls: list[tuple[tuple[int, int], str, dict[str, Any]]] = []
        for index, char in enumerate(source):
            if char == "\n":
                self._line_offsets.append(index + 1)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        prefix, separator, name = tag.partition(":")
        if prefix.casefold() != "call" or not separator or not name:
            return
        line, column = self.getpos()
        start = self._line_offsets[line - 1] + column
        raw = self.get_starttag_text() or ""
        arguments = {
            key: _coerce_value(value.strip())
            for key, value in attrs
            if value is not None
        }
        self.calls.append(((start, start + len(raw)), name, arguments))


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


def _tagged_attribute_calls(
    text: str,
    allowed: set[str],
    schemas: Mapping[str, dict] | None,
) -> list[tuple[tuple[int, int], ToolCall]]:
    """Schema-qualified calls from generic tagged attribute envelopes."""
    found: list[tuple[tuple[int, int], ToolCall]] = []
    source = text[:_MAX_SCAN_CHARS]
    parser = _TaggedCallParser(source)
    try:
        parser.feed(source)
        parser.close()
    except Exception:
        # Healing is best effort. A malformed text envelope remains prose.
        return found
    for span, name, arguments in parser.calls:
        if name not in allowed:
            continue
        if not _qualifies(name, arguments, schemas):
            continue
        found.append((span, ToolCall(name=name, arguments=arguments)))
    return found
