"""The fact type the memory consolidator distils."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass(slots=True)
class DistilledFact:
    """A single fact extracted by consolidation."""

    text: str
    category: str = "other"
    confidence: float = 1.0
    timestamp: float = field(default_factory=time.time)
    strength: float = 1.0
    """Decays over time. Below ``forgetting_threshold`` the fact may be pruned."""
    retrievals: int = 0
    """How many times this fact was returned by ``search_knowledge``."""

