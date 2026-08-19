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

import difflib
import hashlib
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from shipit_agent.models import ToolCall, ToolResult

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


class EditError(Exception):
    """Base for edit preconditions. Always rendered as a tool result."""


class UnreadFileError(EditError):
    """The file has not been read in this session."""


class StaleReadError(EditError):
    """The file changed on disk after it was read."""


class MatchError(EditError):
    """``old_str`` did not match exactly once."""


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


@dataclass
class ReadTracker:
    """Remembers which files this session read, and what they looked like.

    Keyed by resolved path, so ``./src/a.py`` and ``src/a.py`` are one entry —
    otherwise a file read by one spelling and written by another slips the
    check, which is the whole failure this class prevents.
    """

    #: path → content digest at the time of the read.
    seen: dict[str, str] = field(default_factory=dict)

    @staticmethod
    def _key(path: str | Path) -> str:
        return str(Path(path).expanduser().resolve())

    def record_read(self, path: str | Path, content: str) -> None:
        self.seen[self._key(path)] = _digest(content)

    def has_read(self, path: str | Path) -> bool:
        return self._key(path) in self.seen

    def forget(self, path: str | Path) -> None:
        self.seen.pop(self._key(path), None)

    def check_writable(self, path: str | Path, current_content: str) -> None:
        """Raise unless *path* was read this session and has not changed since.

        Called before every edit. Both failures are recoverable: the model reads
        the file and retries, which is one extra turn rather than a lost run.
        """
        key = self._key(path)
        recorded = self.seen.get(key)
        if recorded is None:
            raise UnreadFileError(
                f"{path} has not been read in this session. Read it first, then "
                "edit — editing a file you have not seen risks destroying "
                "content you did not know was there."
            )
        if recorded != _digest(current_content):
            raise StaleReadError(
                f"{path} changed on disk since it was read. Read it again "
                "before editing, or the edit will be based on stale content."
            )


# --------------------------------------------------------------------------- #
# Exact-string editing
# --------------------------------------------------------------------------- #


def _near_miss(content: str, needle: str, *, cutoff: float = 0.6) -> str | None:
    """The closest line-window to *needle*, for a useful failure message."""
    needle_lines = needle.splitlines() or [needle]
    span = len(needle_lines)
    lines = content.splitlines()
    if not lines:
        return None
    windows = [
        "\n".join(lines[i : i + span]) for i in range(max(1, len(lines) - span + 1))
    ]
    matches = difflib.get_close_matches(needle, windows, n=1, cutoff=cutoff)
    return matches[0] if matches else None


def apply_unique_edit(
    content: str,
    old_str: str,
    new_str: str,
    *,
    path: str = "",
) -> str:
    """Replace *old_str* with *new_str*, requiring exactly one match.

    Zero matches raises with the nearest near-miss attached, which usually shows
    the model the whitespace or quoting difference immediately. Two or more
    raises asking for more surrounding context, because picking one silently is
    how an edit lands in the wrong place.
    """
    if not old_str:
        raise MatchError("old_str is empty; give the exact text to replace.")

    count = content.count(old_str)
    if count == 1:
        return content.replace(old_str, new_str, 1)

    where = f" in {path}" if path else ""
    if count == 0:
        near = _near_miss(content, old_str)
        hint = (
            f"\nClosest text found{where}:\n---\n{near}\n---"
            if near
            else "\nNo similar text found — check the file was read correctly."
        )
        raise MatchError(
            f"old_str was not found{where}. It must match the file exactly, "
            f"including indentation and line endings.{hint}"
        )
    raise MatchError(
        f"old_str matched {count} times{where}; an edit must be unambiguous. "
        "Include more surrounding lines so exactly one location matches."
    )


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
