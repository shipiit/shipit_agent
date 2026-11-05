"""The result of asking for structured output."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class StructuredOutputResult:
    """Result of a structured-output run."""

    value: Any
    """Parsed object — Pydantic instance or dict, depending on schema."""

    raw_text: str
    """Final raw text the model produced."""

    attempts: int
    """Number of attempts (1 means first try succeeded)."""

    history: list[dict[str, Any]] = field(default_factory=list)
    """Per-attempt diagnostic info: text, error, etc."""
