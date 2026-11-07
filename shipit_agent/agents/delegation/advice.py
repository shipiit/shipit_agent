"""What an assessment says: whether to delegate, how many parts, and why."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(slots=True)
class DelegationAdvice:
    """Whether this task looks like sub-agent work, and why.

    ``reasons`` is evidence, not decoration: it goes into the directive, so
    the model is told what was noticed rather than nagged in the abstract.
    """

    delegate: bool
    items: int = 0
    reasons: list[str] = field(default_factory=list)
    source: str = ""

    def __bool__(self) -> bool:
        return self.delegate


class Assessor(Protocol):
    """Decides whether a task decomposes. Swap in your own if you like."""

    def assess(self, prompt: str, *, llm: Any = None) -> DelegationAdvice: ...
