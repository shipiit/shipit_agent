"""What a forked session starts with."""

from __future__ import annotations

import copy
from typing import Any

from shipit_agent.core.models import Message

#: Session metadata built from the whole conversation. A fork that stops at an
#: earlier message must not inherit what was learned after it.
HISTORY_DERIVED_KEYS = frozenset({"verified_facts", "compaction_checkpoint", "tool_discovery"})


def fork_contents(
    messages: list[Message], metadata: dict[str, Any], *, cut: bool
) -> tuple[list[Message], dict[str, Any]]:
    """Independent copies of *messages* and *metadata* for a fork; *cut* when history was shortened."""
    kept = {key: value for key, value in metadata.items() if not (cut and key in HISTORY_DERIVED_KEYS)}
    return copy.deepcopy(messages), copy.deepcopy(kept)
