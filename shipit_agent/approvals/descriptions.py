"""The title and description an action gets when its tool gives none."""

from __future__ import annotations

from typing import Any


def _default_title(tool: str, arguments: dict[str, Any]) -> str:
    """One line, in the Narrator's voice, so the queue reads like the transcript."""
    from shipit_agent.narrate.verbs import summarize

    return summarize(tool, arguments).past_label()


def _default_description(tool: str, arguments: dict[str, Any]) -> str:
    """Markdown detail — everything relevant to the decision, nothing else."""
    if not arguments:
        return f"Run `{tool}` with no arguments."
    lines = [f"Run `{tool}` with:", ""]
    for key, value in arguments.items():
        rendered = str(value)
        if "\n" in rendered or len(rendered) > 120:
            lines.append(f"- **{key}**:\n\n```\n{rendered[:2000]}\n```")
        else:
            lines.append(f"- **{key}**: `{rendered}`")
    return "\n".join(lines)
