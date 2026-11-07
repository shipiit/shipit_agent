"""Identifying tool calls: a stable key for arguments, and the shared-state key for withheld tools."""

from __future__ import annotations

import json
from typing import Any

#: Below this, a repeated result is cheaper to resend than to explain.
_REPEAT_MIN_CHARS = 2_000


#: Tools taken out of the advertised set for the rest of a run because the
#: model kept repeating an identical call to them.
WITHHELD_TOOLS_KEY = "withheld_tool_names"


def _arguments_key(arguments: Any) -> str:
    """A stable key for a call's arguments, whatever they are.

    Sorted so that ``{"a": 1, "b": 2}`` and ``{"b": 2, "a": 1}`` are the
    same call, and falling back to ``repr`` for anything JSON cannot hold
    rather than raising inside the tool path.
    """
    try:
        return json.dumps(arguments or {}, sort_keys=True, default=str)
    except Exception:
        return repr(arguments)
