"""The contracts that decide whether an agent can be trusted with a codebase.

A capable tool list is not what makes an agent safe to point at real files. Four
contracts do, and each exists because the obvious alternative fails in a
specific, reproducible way:

**Read before write, enforced.** An edit tool must refuse to modify a file this
session has not read, and refuse again if the file changed on disk since that
read. Written as a prompt instruction it holds right up until context pressure,
which is exactly when a blind overwrite is most damaging. Written as a
precondition it holds always, and the refusal is a recoverable message the model
acts on in one turn.

**Exact-string, unique-match edits.** ``old_str`` must appear exactly once. Zero
matches fails with the nearest near-miss; two matches fails asking for more
context. "Best effort" edits corrupt files quietly. Line numbers are worse
still: they go stale between the read and the write.

**Truncation is visible and recoverable.** A message list is cumulative, so one
huge tool result is not paid once — it is re-sent on every following turn. It
has to be bounded, but a silently shortened result makes the model reason about
half a file believing it saw all of it. Head and tail are kept with an explicit
marker naming what was removed and how to get it.

**Errors are results, not exceptions.** A failing tool returns text the model can
recover from; the real exception goes to logs with argument *shapes*, never
values, so a token in an argument cannot reach a log line.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Mapping

from shipit_agent.core.models import ToolCall, ToolResult

from .edits import (
    EditError as EditError,
)
from .edits import (
    MatchError as MatchError,
)
from .edits import (
    ReadTracker as ReadTracker,
)
from .edits import (
    StaleReadError as StaleReadError,
)
from .edits import (
    UnreadFileError as UnreadFileError,
)
from .edits import (
    apply_unique_edit as apply_unique_edit,
)

logger = logging.getLogger(__name__)

__all__ = [
    "ReadTracker",
    "EditError",
    "StaleReadError",
    "UnreadFileError",
    "MatchError",
    "apply_unique_edit",
    "truncate_output",
    "value_shape",
    "safe_error_text",
    "run_tool_safely",
]


# --------------------------------------------------------------------------- #
# Read-before-write
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# Exact-string editing
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# Visible truncation
# --------------------------------------------------------------------------- #


def truncate_output(
    text: str,
    *,
    limit: int,
    head_ratio: float = 0.6,
    recovery_hint: str = "",
) -> tuple[str, bool]:
    """Bound *text* for the model, keeping head and tail. Returns ``(text, cut)``.

    Head and tail rather than head alone: a command's exit status, a traceback's
    final line and a file's closing structure all live at the end, and a
    head-only cut removes exactly the part that says whether the thing worked.

    The marker names the byte count removed and, when given, how to retrieve it.
    A truncation the model cannot see is worse than a long result, because it
    reasons about a fragment believing it is the whole.
    """
    if limit <= 0 or len(text) <= limit:
        return text, False

    marker_budget = 160
    usable = max(200, limit - marker_budget)
    head_chars = int(usable * head_ratio)
    tail_chars = usable - head_chars
    removed = len(text) - head_chars - tail_chars

    hint = f" {recovery_hint}" if recovery_hint else ""
    marker = f"\n\n[... {removed:,} characters omitted from the middle.{hint} ...]\n\n"
    return text[:head_chars] + marker + text[-tail_chars:], True


# --------------------------------------------------------------------------- #
# Safe errors
# --------------------------------------------------------------------------- #


def value_shape(value: Any, *, depth: int = 0) -> Any:
    """Describe *value*'s structure without reproducing its content.

    Logs need to show what a failing call looked like. They must not show what
    was in it — an argument can hold a token, a password, or a customer's data,
    and a log line is the least controlled place any of those can end up.
    """
    if depth > 3:
        return "..."
    if value is None or isinstance(value, bool):
        return type(value).__name__
    if isinstance(value, (int, float)):
        return type(value).__name__
    if isinstance(value, str):
        return f"str[{len(value)}]"
    if isinstance(value, Mapping):
        return {str(k): value_shape(v, depth=depth + 1) for k, v in list(value.items())[:12]}
    if isinstance(value, (list, tuple, set)):
        inner = value_shape(next(iter(value)), depth=depth + 1) if value else "empty"
        return [f"{type(value).__name__}[{len(value)}]", inner]
    return type(value).__name__


def safe_error_text(error: Exception, *, tool_name: str) -> str:
    """A message the model can act on, with nothing sensitive in it."""
    detail = str(error).strip() or error.__class__.__name__
    if len(detail) > 500:
        detail = detail[:500].rstrip() + "…"
    return f"{tool_name} failed: {detail}"


def run_tool_safely(
    call: ToolCall,
    execute: Callable[[], str],
    *,
    output_limit: int = 16_000,
    recovery_hint: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> ToolResult:
    """Run one tool call, turning any failure into a recoverable result.

    The exception never escapes: an agent that dies because one tool raised
    cannot finish a task, whereas one handed an error message routinely recovers
    in the next turn. The real exception is logged with argument *shapes*.
    """
    started = time.perf_counter()
    try:
        raw = execute()
    except Exception as error:  # noqa: BLE001 — this is the containment boundary
        logger.warning(
            "Tool %s failed",
            call.name,
            exc_info=True,
            extra={"tool_call_id": call.id, "argument_shape": value_shape(call.arguments)},
        )
        return ToolResult(
            name=call.name,
            output=safe_error_text(error, tool_name=call.name),
            tool_call_id=call.id,
            is_error=True,
            duration_ms=(time.perf_counter() - started) * 1000,
        )

    text, truncated = truncate_output(
        str(raw), limit=output_limit, recovery_hint=recovery_hint
    )
    # A tool's own metadata is part of its result. Dropping it silently loses
    # everything a tool says *about* what it did — which skill it primed, which
    # tools that unlocked, whether a search found anything — and the runtime
    # then reports those as empty rather than as missing.
    carried = dict(metadata or {})
    return ToolResult(
        name=call.name,
        output=text,
        tool_call_id=call.id,
        truncated=truncated or bool(carried.get("truncated")),
        is_error=bool(carried.get("is_error")),
        duration_ms=(time.perf_counter() - started) * 1000,
        metadata=carried,
    )
