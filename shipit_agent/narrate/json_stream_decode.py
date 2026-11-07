"""Decoding what the streaming tool-input parser has scanned: escapes, the prefix, the value."""

from __future__ import annotations

import json
import re
from typing import Any, Callable

_HEX4 = re.compile(r"^[0-9a-fA-F]{4}$")

_SIMPLE_ESCAPES = {
    '"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f",
    "n": "\n", "r": "\r", "t": "\t",
}


class JsonStreamDecodeMixin:
    """The decoding half of :class:`~shipit_agent.narrate.json_stream.StreamingToolInputParser`."""

    _buffer: str
    _pos: int
    _phase: str
    _key: str
    _key_start: int
    _prefix: dict[str, Any] | None
    _decoded: str
    _complete: bool
    # Defined by the parser.
    _fail: Callable[[], None]

    def _decode_escape_into_key(self) -> int | None:
        """Decode one escape inside a key. ``None`` = need more input."""
        buffer = self._buffer
        if self._pos + 1 >= len(buffer):
            return None
        escape = buffer[self._pos + 1]
        if escape == "u":
            if self._pos + 6 > len(buffer):
                return None
            hex4 = buffer[self._pos + 2 : self._pos + 6]
            if not _HEX4.match(hex4):
                self._fail()
                return 0
            self._key += chr(int(hex4, 16))
            self._pos += 6
            return 6
        decoded = _SIMPLE_ESCAPES.get(escape)
        if decoded is None:
            self._fail()
            return 0
        self._key += decoded
        self._pos += 2
        return 2

    def _extract_prefix(self) -> None:
        """Parse everything before the streaming key, in one shot.

        Reached exactly when the streaming field's opening quote is found,
        which is also when every preceding field is known to be complete.
        """
        prefix = self._buffer[: self._key_start].rstrip()
        if prefix.endswith(","):
            prefix = prefix[:-1]
        prefix += "}"
        try:
            parsed = json.loads(prefix)
            self._prefix = parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            self._prefix = {}

    def _decode_streaming(self) -> None:
        """Decode the streaming string incrementally from the cursor onward."""
        buffer = self._buffer
        start = self._pos
        while self._pos < len(buffer):
            char = buffer[self._pos]

            if char == '"':
                if self._pos > start:
                    self._decoded += buffer[start : self._pos]
                self._complete = True
                self._phase = "done"
                self._pos += 1
                return

            if char == "\\":
                # Flush the plain run before this escape, then decode it —
                # or bail, leaving the cursor on the backslash, if the escape
                # straddles the chunk boundary.
                if self._pos > start:
                    self._decoded += buffer[start : self._pos]
                if self._pos + 1 >= len(buffer):
                    return
                escape = buffer[self._pos + 1]
                decoded = _SIMPLE_ESCAPES.get(escape)
                if decoded is not None:
                    self._decoded += decoded
                    self._pos += 2
                elif escape == "u":
                    if self._pos + 6 > len(buffer):
                        return
                    hex4 = buffer[self._pos + 2 : self._pos + 6]
                    if not _HEX4.match(hex4):
                        return self._fail()
                    self._decoded += chr(int(hex4, 16))
                    self._pos += 6
                else:
                    return self._fail()
                start = self._pos
                continue

            self._pos += 1

        if self._pos > start:
            self._decoded += buffer[start : self._pos]
