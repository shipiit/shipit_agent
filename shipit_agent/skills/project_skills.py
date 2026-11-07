"""Skills a project keeps as Markdown files, in .shipit, .claude and similar folders."""

from __future__ import annotations


import json
import re
from pathlib import Path

from .skill import Skill


_PROJECT_SKILL_ROOTS = (
    ".shipit/skills",
    ".agents/skills",
    ".claude/skills",
    ".codex/skills",
)


def _frontmatter_value(value: str) -> str | list[str] | bool:
    stripped = value.strip()
    if stripped.lower() in {"true", "false"}:
        return stripped.lower() == "true"
    if stripped.startswith("[") and stripped.endswith("]"):
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except json.JSONDecodeError:
            stripped = stripped[1:-1]
    return stripped.strip("\"'")


def split_frontmatter(text: str) -> tuple[dict[str, object], str]:
    """Split a Markdown file's ``---`` header from its body.

    Keys are normalised (``allowed-tools`` becomes ``allowed_tools``); values
    are strings, booleans, or lists for ``[a, b]``. A file without a header
    is all body.
    """
    metadata: dict[str, object] = {}
    body = text
    if text.startswith("---\n"):
        marker = text.find("\n---\n", 4)
        if marker >= 0:
            header = text[4:marker]
            body = text[marker + 5 :]
            for line in header.splitlines():
                if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
                    continue
                key, value = line.split(":", 1)
                metadata[key.strip().replace("-", "_")] = _frontmatter_value(value)
    return metadata, body


def load_markdown_skill(path: str | Path) -> Skill:
    """Load a Codex/Claude-style ``SKILL.md`` into a runtime Skill."""
    source = Path(path)
    metadata, body = split_frontmatter(source.read_text(encoding="utf-8"))

    def _list(name: str) -> list[str]:
        value = metadata.get(name, [])
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [part.strip() for part in str(value).split(",") if part.strip()]

    skill_id = str(metadata.get("id") or source.parent.name).strip()
    skill_id = re.sub(r"[^a-z0-9_-]+", "-", skill_id.lower()).strip("-")
    name = str(metadata.get("name") or skill_id.replace("-", " ").title())
    description = str(metadata.get("description") or "").strip()
    if not description:
        description = next(
            (
                line.strip()
                for line in body.splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            ),
            f"Project skill loaded from {source}",
        )
    return Skill(
        id=skill_id,
        name=name,
        display_name=str(metadata.get("display_name") or name),
        description=description,
        category=str(metadata.get("category") or "project"),
        version=str(metadata.get("version") or "1.0.0"),
        author=str(metadata.get("author") or source),
        tags=_list("tags"),
        trigger_phrases=_list("triggers") or _list("trigger_phrases"),
        tools=_list("tools"),
        mcps=[{"name": name} for name in _list("mcps")],
        requirements=_list("requirements"),
        prompt_template=body.strip(),
        featured=bool(metadata.get("featured", False)),
        directory=str(source.parent.resolve()),
    )


def discover_project_skills(project_root: str | Path) -> list[Skill]:
    """Discover local SKILL.md files in common agent skill directories.

    Later roots override earlier ones by skill id. This gives project-native
    ``.shipit`` skills priority while still accepting Claude/Codex layouts.
    """
    root = Path(project_root)
    discovered: dict[str, Skill] = {}
    # Compatibility roots first; shipit's native root wins last.
    for relative in reversed(_PROJECT_SKILL_ROOTS):
        skill_root = root / relative
        if not skill_root.is_dir():
            continue
        for path in sorted(skill_root.glob("*/SKILL.md")):
            skill = load_markdown_skill(path)
            discovered[skill.id] = skill
    return list(discovered.values())
