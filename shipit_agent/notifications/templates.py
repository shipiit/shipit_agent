"""Default message templates for agent lifecycle notifications.

Templates use Python :meth:`str.format_map` syntax.  Missing keys are
left as-is so partial rendering never raises.
"""

from __future__ import annotations

from string import Formatter
from typing import Any


# ---------------------------------------------------------------------------
# Default templates keyed by event name
# ---------------------------------------------------------------------------

DEFAULT_TEMPLATES: dict[str, str] = {
    "run_started": "{agent} started: {prompt_preview}",
    "run_completed": (
        "{agent} completed in {duration} | Cost: {cost} | {output_preview}"
    ),
    "tool_failed": "{agent} tool '{tool}' failed: {error}",
    "cost_alert": ("{agent} has spent {spent} of {budget} budget ({percent}%)"),
    "checkpoint_saved": "{agent} checkpoint #{step} saved",
    "crew_started": (
        "Crew '{crew}' started with {agent_count} agents, {task_count} tasks"
    ),
    "crew_completed": (
        "Crew '{crew}' completed in {duration} | " "{completed}/{total} tasks succeeded"
    ),
}


# ---------------------------------------------------------------------------
# Safe renderer
# ---------------------------------------------------------------------------


class _SafeDict(dict[str, Any]):
    """Dict subclass that returns the format key itself for missing keys.

    This lets :func:`render_template` silently skip placeholders that
    were not provided instead of raising :class:`KeyError`.
    """

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def render_template(template: str, **kwargs: Any) -> str:
    """Render a notification template with safe string formatting.

    Any placeholder whose value is not supplied is kept literally in the
    output (e.g. ``"{agent}"`` stays as ``"{agent}"``).

    Args:
        template: A format string with ``{key}`` placeholders.
        **kwargs: Values to substitute.

    Returns:
        The rendered string.
    """
    # Validate that the template is a well-formed format string by parsing
    # it once.  If it contains invalid syntax we fall back to the raw
    # template so we never crash on bad user input.
    try:
        # Formatter().parse validates the template structure.
        list(Formatter().parse(template))
    except (ValueError, KeyError):
        return template

    return template.format_map(_SafeDict(kwargs))
