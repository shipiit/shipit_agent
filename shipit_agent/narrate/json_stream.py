"""Read one field of a tool call's arguments *while it is still arriving*.

A model writing a 400-line file emits its `write_file` arguments as a JSON
string, token by token. Until the closing brace lands you have no arguments at
all — so the transcript shows nothing, then shows everything. Cloudflare OS
fixes that with an incremental parser that decodes **one designated string
field** as it streams, which is what makes their editor pane type the file out
in real time.

This is that parser, ported::

    parser = StreamingToolInputParser("content")
    parser.append('{"path": "app.py", "content": "hel')
    parser.append('lo world"}')

    parser.prefix_fields    # {"path": "app.py"} — parsed once, in full
    parser.streaming_value  # "hello world"      — grew as chunks arrived
    parser.stream_complete  # True

Two properties matter and both are preserved:

- **O(n) total.** The buffer is scanned once; the cursor never rewinds. Fields
  *before* the streaming field are `json.loads`-ed in one shot at the moment
  the streaming field's opening quote is found — which is also the moment they
  are known to be complete.
- **Chunk boundaries are safe.** An escape sequence split across two chunks
  (``"\\`` then ``n"``, or a ``\\u00`` / ``e9`` split) is retried on the next
  append rather than mis-decoded, because the cursor is left sitting on the
  backslash.

Malformed input never raises — :attr:`has_error` goes true and the caller
stops previewing. A live preview must never be able to take a run down.
"""

from __future__ import annotations

import json
import re
from typing import Any

__all__ = ["StreamingToolInputParser", "STREAMING_FIELDS", "streaming_field_for"]

_SIMPLE_ESCAPES = {
    '"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f",
    "n": "\n", "r": "\r", "t": "\t",
}
_WHITESPACE = " \t\n\r"
_HEX4 = re.compile(r"^[0-9a-fA-F]{4}$")

# Which argument is worth streaming, per tool: the big one the model spends
# most of its tokens writing. Everything else arrives fast enough to wait for.
STREAMING_FIELDS: dict[str, str] = {
    "write_file": "content",
    "edit_file": "new_string",
    "notebook_edit": "content",
    "run_code": "code",
    "bash": "command",
    "sql": "query",
    "build_document": "content",
    "build_artifact": "content",
}


def streaming_field_for(tool_name: str) -> str | None:
    """The argument worth streaming for *tool_name*, if any."""
    return STREAMING_FIELDS.get(tool_name)


class StreamingToolInputParser:
    """Incrementally parse a JSON object, streaming one string field.

    Feed raw argument-JSON chunks to :meth:`append` as the model emits them.
    """

    __slots__ = (
        "_field", "_buffer", "_pos", "_phase", "_key", "_key_start",
        "_depth", "_in_string", "_prefix", "_decoded", "_complete",
    )

    def __init__(self, streaming_field_name: str) -> None:
        self._field = streaming_field_name
        self._buffer = ""
        self._pos = 0
        self._phase = "initial"
        self._key = ""
        self._key_start = 0
        self._depth = 0
        self._in_string = False
        self._prefix: dict[str, Any] | None = None
        self._decoded = ""
        self._complete = False

    # ── public ───────────────────────────────────────────────────────────

    def append(self, delta: str) -> None:
        """Feed the next raw chunk of argument JSON."""
        if not delta or self._phase in ("done", "error"):
            return
        self._buffer += delta
        self._scan()

    @property
    def prefix_fields(self) -> dict[str, Any] | None:
        """Fields *before* the streaming one — ``None`` until it starts.

        Non-``None`` is the signal that every preceding field is complete, so
        a caller can safely read e.g. the target path before the body arrives.
        """
        return self._prefix

    @property
    def streaming_value(self) -> str:
        """The decoded streaming field so far."""
        return self._decoded

    @property
    def stream_complete(self) -> bool:
        """Has the streaming field's closing quote arrived?"""
        return self._complete

    @property
    def has_error(self) -> bool:
        """Did the input turn out not to be the JSON we expected?"""
        return self._phase == "error"

    @property
    def done(self) -> bool:
        return self._phase in ("done", "error")

    # ── the state machine ────────────────────────────────────────────────

    def _fail(self) -> None:
        self._phase = "error"

    def _scan(self) -> None:  # noqa: C901 - a state machine reads best whole
        buffer = self._buffer
        while self._pos < len(buffer):
            char = buffer[self._pos]
            phase = self._phase

            if phase == "initial":
                if char in _WHITESPACE:
                    self._pos += 1
                elif char == "{":
                    self._phase = "expectKey"
                    self._pos += 1
                else:
                    return self._fail()

            elif phase == "expectKey":
                if char in _WHITESPACE:
                    self._pos += 1
                elif char == "}":
                    self._phase = "done"
                    self._pos += 1
                    return
                elif char == '"':
                    self._key_start = self._pos
                    self._key = ""
                    self._phase = "inKey"
                    self._pos += 1
                else:
                    return self._fail()

            elif phase == "inKey":
                if char == "\\":
                    # Leave the cursor on the backslash so a boundary-split
                    # escape is retried intact on the next append().
                    consumed = self._decode_escape_into_key()
                    if consumed is None:
                        return
                elif char == '"':
                    self._phase = "expectColon"
                    self._pos += 1
                else:
                    self._key += char
                    self._pos += 1

            elif phase == "expectColon":
                if char in _WHITESPACE:
                    self._pos += 1
                elif char == ":":
                    self._phase = "expectValue"
                    self._pos += 1
                else:
                    return self._fail()

            elif phase == "expectValue":
                if char in _WHITESPACE:
                    self._pos += 1
                    continue
                if self._key == self._field:
                    if char != '"':
                        return self._fail()  # the streamed field must be a string
                    self._pos += 1
                    self._phase = "streaming"
                    self._extract_prefix()
                elif char == '"':
                    self._phase = "inStringValue"
                    self._pos += 1
                else:
                    self._depth = 1 if char in "{[" else 0
                    self._in_string = False
                    self._phase = "inOtherValue"
                    self._pos += 1

            elif phase == "inStringValue":
                if char == "\\":
                    if self._pos + 1 >= len(buffer):
                        return
                    self._pos += 2
                elif char == '"':
                    self._phase = "afterValue"
                    self._pos += 1
                else:
                    self._pos += 1

            elif phase == "inOtherValue":
                if self._in_string:
                    if char == "\\":
                        if self._pos + 1 >= len(buffer):
                            return
                        self._pos += 2
                    elif char == '"':
                        self._in_string = False
                        self._pos += 1
                    else:
                        self._pos += 1
                elif char == '"':
                    self._in_string = True
                    self._pos += 1
                elif char in "{[":
                    self._depth += 1
                    self._pos += 1
                elif char in "}]":
                    if self._depth > 0:
                        self._depth -= 1
                        self._pos += 1
                        if self._depth == 0:
                            self._phase = "afterValue"
                    else:
                        # A scalar ended; this brace closes the outer object,
                        # so hand it back to `afterValue` without consuming it.
                        self._phase = "afterValue"
                elif self._depth == 0 and (char == "," or char in _WHITESPACE):
                    self._phase = "afterValue"
                else:
                    self._pos += 1

            elif phase == "afterValue":
                if char in _WHITESPACE:
                    self._pos += 1
                elif char == ",":
                    self._phase = "expectKey"
                    self._pos += 1
                elif char == "}":
                    self._phase = "done"
                    self._pos += 1
                    return
                else:
                    return self._fail()

            elif phase == "streaming":
                self._decode_streaming()
                return

            else:  # done / error
                return

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
