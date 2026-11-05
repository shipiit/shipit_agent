"""Named sub-agents a caller or a project defines, as in the Claude Agent SDK.

A definition says when to use the sub-agent (``description``), how it should
behave (``prompt``), which tools it may use (``tools``; ``None`` means all of
its parent's) and which model runs it (``model``; ``None`` means the parent's).
They come from ``Agent(agents={...})`` and from Markdown files with a front
matter header in ``.shipit/agents/`` and ``.claude/agents/``::

    ---
    name: reviewer
    description: Use for reviewing code changes.
    tools: read_file, grep_files
    model: claude-haiku-5-5
    ---
    You review code. Be specific.

A sub-agent never gets more than its parent: its tools are intersected with
the parent's, and it inherits the parent's permissions.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = ["SubagentDefinition", "coerce_subagents", "load_subagent_files"]

#: Project folders searched for agent files; later ones win on a name clash.
AGENT_FOLDERS: tuple[str, ...] = (".claude/agents", ".shipit/agents")

_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


@dataclass(frozen=True, slots=True)
class SubagentDefinition:
    """One named sub-agent: when to use it, how it behaves, what it may use."""

    #: When the parent should hand work to it. Shown to the parent model.
    description: str
    #: The sub-agent's own system prompt.
    prompt: str
    #: Tool names it may use, within the parent's; ``None`` for all of them.
    tools: list[str] | None = None
    #: Model to run it with; ``None`` for the parent's.
    model: str | None = None


def coerce_subagents(spec: Mapping[str, Any] | None) -> dict[str, SubagentDefinition]:
    """Normalise ``Agent(agents=...)`` to definitions, refusing malformed ones."""
    if not spec:
        return {}
    agents: dict[str, SubagentDefinition] = {}
    for name, value in spec.items():
        key = str(name).strip().lower()
        if not _NAME.match(key):
            raise ValueError(
                f"Sub-agent name {name!r} must be a short lowercase name like 'code-reviewer'"
            )
        agents[key] = _coerce_one(key, value)
    return agents


def _coerce_one(name: str, value: Any) -> SubagentDefinition:
    if isinstance(value, SubagentDefinition):
        return value
    if isinstance(value, Mapping):
        description = str(value.get("description") or "").strip()
        prompt = str(value.get("prompt") or "").strip()
        tools = value.get("tools")
        model = value.get("model")
    elif hasattr(value, "prompt") and hasattr(value, "role"):
        # A prebuilt role AgentDefinition: its role and goal say when to use it.
        description = " ".join(
            part
            for part in (str(value.role or ""), str(getattr(value, "goal", "") or ""))
            if part
        ).strip()
        prompt = str(value.prompt or "").strip()
        tools = list(value.tools) or None
        model = value.model or None
    else:
        raise ValueError(
            f"Sub-agent {name!r}: expected a definition or a dict, got {type(value).__name__}"
        )
    if not description or not prompt:
        raise ValueError(f"Sub-agent {name!r} needs both a description and a prompt")
    if tools is not None:
        tools = [str(tool).strip() for tool in tools if str(tool).strip()]
    return SubagentDefinition(description, prompt, tools, str(model) if model else None)


def load_subagent_files(project_root: str | Path) -> dict[str, SubagentDefinition]:
    """Sub-agents defined by Markdown files in the project's agent folders."""
    from shipit_agent.skills.registry import split_frontmatter

    root = Path(project_root)
    found: dict[str, SubagentDefinition] = {}
    for folder in AGENT_FOLDERS:
        directory = root / folder
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.md")):
            metadata, body = split_frontmatter(path.read_text(encoding="utf-8"))
            name = str(metadata.get("name") or path.stem).strip().lower()
            tools = metadata.get("tools")
            if isinstance(tools, str):
                tools = [part.strip() for part in tools.split(",") if part.strip()]
            try:
                found[name] = _coerce_one(
                    name,
                    {
                        "description": metadata.get("description"),
                        "prompt": body.strip(),
                        "tools": tools or None,
                        "model": metadata.get("model"),
                    },
                )
            except ValueError:
                # A malformed file is skipped rather than failing every run.
                continue
    return found
