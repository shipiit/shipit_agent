"""Keep provider reasoning markup out of user-visible model text."""

from __future__ import annotations

import re
from collections.abc import Iterable


DEFAULT_REASONING_MARKUP_TAGS = ("thought", "think")
_BOUNDARY_CHARS = 24


def _patterns(tags: Iterable[str]) -> tuple[re.Pattern[str], re.Pattern[str]]:
    names = [re.escape(str(tag).strip()) for tag in tags if str(tag).strip()]
    if not names:
        # A never-matching expression cleanly disables markup filtering.
        return re.compile(r"(?!x)x"), re.compile(r"(?!x)x")
    alternatives = "|".join(names)
    return (
        re.compile(rf"<\s*(?:{alternatives})\b", re.IGNORECASE),
        re.compile(rf"<\s*/\s*(?:{alternatives})\s*>", re.IGNORECASE),
    )


def split_reasoning_markup(
    text: str, hidden_tags: Iterable[str] | None = None
) -> tuple[str, str, bool]:
    """Return visible text, extracted reasoning, and malformed-tag status."""
    if not text:
        return text, "", False
    opening_pattern, closing_pattern = _patterns(
        DEFAULT_REASONING_MARKUP_TAGS if hidden_tags is None else hidden_tags
    )
    visible: list[str] = []
    reasoning: list[str] = []
    cursor = 0
    malformed = False
    while True:
        opening = opening_pattern.search(text, cursor)
        if opening is None:
            visible.append(text[cursor:])
            break
        visible.append(text[cursor : opening.start()])
        open_end = text.find(">", opening.end())
        if open_end < 0:
            reasoning.append(text[opening.end() :])
            malformed = True
            break
        closing = closing_pattern.search(text, open_end + 1)
        if closing is None:
            reasoning.append(text[open_end + 1 :])
            malformed = True
            break
        reasoning.append(text[open_end + 1 : closing.start()])
        cursor = closing.end()
    cleaned = closing_pattern.sub("", "".join(visible)).strip()
    hidden = "\n".join(part.strip() for part in reasoning if part.strip())
    return cleaned, hidden, malformed


class VisibleTextStreamFilter:
    """Incrementally suppress `<thought>`/`<think>` blocks across chunks."""

    def __init__(self, hidden_tags: Iterable[str] | None = None) -> None:
        self._opening, self._closing = _patterns(
            DEFAULT_REASONING_MARKUP_TAGS if hidden_tags is None else hidden_tags
        )
        self._buffer = ""
        self._hidden = False
        self.filtered_chars = 0

    def reset(self) -> None:
        self._buffer = ""
        self._hidden = False
        self.filtered_chars = 0

    def feed(self, chunk: str) -> list[str]:
        if not chunk:
            return []
        self._buffer += chunk
        output: list[str] = []
        while self._buffer:
            if self._hidden:
                closing = self._closing.search(self._buffer)
                if closing is None:
                    discard = max(0, len(self._buffer) - _BOUNDARY_CHARS)
                    self.filtered_chars += discard
                    self._buffer = self._buffer[discard:]
                    break
                self.filtered_chars += closing.end()
                self._buffer = self._buffer[closing.end() :]
                self._hidden = False
                continue

            opening = self._opening.search(self._buffer)
            if opening is not None:
                if opening.start():
                    output.append(self._buffer[: opening.start()])
                open_end = self._buffer.find(">", opening.end())
                if open_end < 0:
                    self._buffer = self._buffer[opening.start() :]
                    break
                self.filtered_chars += open_end + 1 - opening.start()
                self._buffer = self._buffer[open_end + 1 :]
                self._hidden = True
                continue

            # Retain only a possible split tag prefix (`<thou`); normal text
            # can be emitted immediately without waiting for the next chunk.
            last_lt = self._buffer.rfind("<")
            if last_lt >= 0 and len(self._buffer) - last_lt <= _BOUNDARY_CHARS:
                if last_lt:
                    output.append(self._buffer[:last_lt])
                self._buffer = self._buffer[last_lt:]
            else:
                output.append(self._buffer)
                self._buffer = ""
            break
        return [part for part in output if part]

    def finish(self) -> list[str]:
        if self._hidden or self._opening.search(self._buffer):
            self.filtered_chars += len(self._buffer)
            self._buffer = ""
            return []
        tail = self._closing.sub("", self._buffer)
        self._buffer = ""
        return [tail] if tail else []
