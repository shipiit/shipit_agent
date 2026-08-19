"""Contracts that make tools safe to point at real files.

The tools themselves live in ``shipit_agent.tools``, one per directory. This
package holds only the invariants they share — read-before-write, unique-match
editing, visible truncation, errors as results.
"""

from shipit_agent.toolkit.contracts import (
    EditError,
    MatchError,
    ReadTracker,
    StaleReadError,
    UnreadFileError,
    apply_unique_edit,
    run_tool_safely,
    safe_error_text,
    truncate_output,
    value_shape,
)

__all__ = [
    "EditError",
    "MatchError",
    "ReadTracker",
    "StaleReadError",
    "UnreadFileError",
    "apply_unique_edit",
    "run_tool_safely",
    "safe_error_text",
    "truncate_output",
    "value_shape",
]
