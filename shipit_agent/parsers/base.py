from __future__ import annotations

from typing import Any, Protocol


class OutputParser(Protocol):
    """Protocol for output parsers.

    Any class with a ``parse(text) -> Any`` method satisfies this protocol.
    """

    def parse(self, text: str) -> Any: ...

    def get_format_instructions(self) -> str:
        """Return instructions the LLM should follow to produce parseable output."""
        ...


class ParseError(Exception):
    """Raised when an output parser cannot parse the given text."""

    def __init__(self, message: str, raw_text: str = "") -> None:
        super().__init__(message)
        self.raw_text = raw_text
