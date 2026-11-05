"""Checkpoint compaction — keep a long run inside the context window.

shipit's original compaction (``runtime.py``) worked but made four compromises
Cloudflare OS doesn't:

============================  ==========================  =========================
                              before                      here
============================  ==========================  =========================
budget                        ``len(text) // 4``            per-model window, 0.75
cut point                     "last 4 messages"            a **turn boundary**
summary prompt                "summarize this"             a 6-heading handoff
prompt injection              none                         explicit ignore clause
history                       destructively replaced       **preserved**; replay moves
============================  ==========================  =========================

The last row is the important one. A checkpoint records *where replay starts*
and *what stands in for everything before it*. The canonical message list is
untouched, so a caller can still page back through the whole conversation —
only the agent's replay window moves forward.

    checkpoint = Compactor(llm=llm, model="claude-opus-5").compact(messages)
    if checkpoint:
        messages = checkpoint.replay(messages)
"""

from __future__ import annotations

from .boundary import find_boundary, starts_a_step, starts_a_turn
from .checkpoint import CompactionCheckpoint
from .compactor import Compactor
from .limits import (
    DEFAULT_CONTEXT_WINDOW,
    DEFAULT_MAX_OUTPUT,
    MODEL_CONTEXT_WINDOWS,
    TARGET_RATIO,
    TRIGGER_RATIO,
    ModelLimits,
    get_model_limits,
)
from .prompt import COMPACTION_SYSTEM_PROMPT
from .tokens import (
    content_tokens,
    count_messages,
    estimate_tokens,
    messages_tokens,
    should_compact,
)

__all__ = [
    "COMPACTION_SYSTEM_PROMPT",
    "CompactionCheckpoint",
    "Compactor",
    "DEFAULT_CONTEXT_WINDOW",
    "DEFAULT_MAX_OUTPUT",
    "MODEL_CONTEXT_WINDOWS",
    "ModelLimits",
    "TARGET_RATIO",
    "TRIGGER_RATIO",
    "content_tokens",
    "count_messages",
    "estimate_tokens",
    "find_boundary",
    "get_model_limits",
    "messages_tokens",
    "should_compact",
    "starts_a_step",
    "starts_a_turn",
]
