"""The SKILL.md format: a folder is a skill.

A skill is a directory with a ``SKILL.md`` at its root. The file opens with YAML
front-matter — name, description, the tools it needs — and the body is the
instructions themselves. Supporting material sits alongside as ordinary files.

    invoice-processing/
    ├── SKILL.md              front-matter + instructions
    ├── references/
    │   └── vat-rules.md      loaded only when the body says to
    └── scripts/
        └── extract.py        run, not read into context

The format earns its shape from one constraint: **the description is what the
model sees, and the body is what it gets.** Descriptions live in the prompt for
every skill, always, so they are one line. Bodies are loaded on demand and can be
as long as the work requires. That split is why a hundred skills cost about a
thousand tokens instead of a hundred thousand — and it means a description that
does not say *when* to use the skill makes the skill unreachable no matter how
good the body is.

Reference files go one level further out. A body that inlines every edge case is
paid in full every time it loads; a body that says "for VAT edge cases, read
``references/vat-rules.md``" is paid only when the edge case appears.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

logger = logging.getLogger(__name__)

__all__ = [
    "Skill",
    "SkillParseError",
    "parse_skill_markdown",
    "load_skill_dir",
    "discover_skills",
    "write_skill",
    "SKILL_FILENAME",
]

SKILL_FILENAME = "SKILL.md"

_FRONT_MATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.S)
_ID_SAFE = re.compile(r"[^a-z0-9]+")


class SkillParseError(ValueError):
    """A SKILL.md that cannot be understood. Never fatal to discovery."""


def skill_id_from_name(name: str) -> str:
    return _ID_SAFE.sub("-", name.strip().lower()).strip("-") or "skill"


@dataclass
class Skill:
    """One skill: a line for the catalog, a body for when it is chosen."""

    id: str
    name: str
    #: One line, in the prompt for every skill, always. It must say *when* to
    #: use this — a description that only says what it is cannot be selected.
    description: str
    body: str = ""
    #: Tool names this skill needs. Unioned into the allowed set when primed;
    #: names this deployment lacks are dropped with a log line, never an error.
    tools: list[str] = field(default_factory=list)
    #: Exact phrases that select it without a model turn.
    trigger_phrases: list[str] = field(default_factory=list)
    #: Primed before the first turn, unconditionally.
    always_apply: bool = False
    version: str = "1.0.0"
    directory: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def prompt_text(self) -> str:
        """The body, as injected when the skill is primed."""
        return self.body

    def reference(self, relative: str) -> str:
        """Read a supporting file. Kept out of context until the body asks."""
        if self.directory is None:
            raise FileNotFoundError(f"{self.id} has no directory on disk")
        target = (self.directory / relative).resolve()
        if not str(target).startswith(str(self.directory.resolve())):
            raise ValueError(f"{relative!r} escapes the skill directory")
        return target.read_text(encoding="utf-8")

    def references(self) -> list[str]:
        """Supporting files available to this skill, relative to its directory."""
        if self.directory is None:
            return []
        return sorted(
            str(path.relative_to(self.directory))
            for path in self.directory.rglob("*")
            if path.is_file() and path.name != SKILL_FILENAME
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "tools": list(self.tools),
            "trigger_phrases": list(self.trigger_phrases),
            "always_apply": self.always_apply,
            "version": self.version,
            "directory": str(self.directory) if self.directory else None,
        }


def _parse_front_matter(text: str) -> dict[str, Any]:
    """YAML when available, a minimal key/value reader when it is not.

    A skill folder must not become unreadable because an optional dependency is
    missing, so the fallback handles the shapes front-matter actually uses:
    scalars, inline lists, and dash lists.
    """
    try:
        import yaml  # type: ignore

        loaded = yaml.safe_load(text)
        return loaded if isinstance(loaded, dict) else {}
    except ImportError:
        pass

    data: dict[str, Any] = {}
    current_key: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- ") and current_key:
            data.setdefault(current_key, [])
            if isinstance(data[current_key], list):
                data[current_key].append(stripped[2:].strip().strip("\"'"))
            continue
        if ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        key = key.strip()
        value = value.strip()
        current_key = key
        if not value:
            data[key] = []
        elif value.startswith("[") and value.endswith("]"):
            data[key] = [v.strip().strip("\"'") for v in value[1:-1].split(",") if v.strip()]
        elif value.lower() in ("true", "false"):
            data[key] = value.lower() == "true"
        else:
            data[key] = value.strip("\"'")
    return data


def parse_skill_markdown(text: str, *, directory: Path | None = None) -> Skill:
    """Parse a SKILL.md into a :class:`Skill`.

    A file with no front-matter is still usable: the first heading becomes the
    name and the first paragraph the description, so a plain markdown note can
    be dropped in and work.
    """
    match = _FRONT_MATTER.match(text.lstrip())
    if match:
        meta = _parse_front_matter(match.group(1))
        body = match.group(2).strip()
    else:
        meta = {}
        body = text.strip()

    name = str(meta.get("name") or "").strip()
    description = str(meta.get("description") or "").strip()

    if not name:
        heading = re.search(r"^#\s+(.+)$", body, re.M)
        name = heading.group(1).strip() if heading else (directory.name if directory else "")
    if not description:
        paragraphs = [p.strip() for p in body.split("\n\n") if p.strip() and not p.startswith("#")]
        description = " ".join(paragraphs[0].split())[:200] if paragraphs else ""

    if not name:
        raise SkillParseError("Skill has no name and no heading to infer one from.")
    if not description:
        raise SkillParseError(
            f"Skill {name!r} has no description. The description is the only "
            "thing the model sees when choosing — without it the skill can "
            "never be selected."
        )

    def as_list(value: Any) -> list[str]:
        if isinstance(value, str):
            return [v.strip() for v in value.split(",") if v.strip()]
        if isinstance(value, (list, tuple)):
            return [str(v).strip() for v in value if str(v).strip()]
        return []

    return Skill(
        id=str(meta.get("id") or skill_id_from_name(name)),
        name=name,
        description=description,
        body=body,
        tools=as_list(meta.get("tools")),
        trigger_phrases=as_list(meta.get("trigger_phrases") or meta.get("triggers")),
        always_apply=bool(meta.get("always_apply", False)),
        version=str(meta.get("version") or "1.0.0"),
        directory=directory,
        metadata={
            k: v
            for k, v in meta.items()
            if k
            not in {
                "id",
                "name",
                "description",
                "tools",
                "trigger_phrases",
                "triggers",
                "always_apply",
                "version",
            }
        },
    )


def load_skill_dir(directory: str | Path) -> Skill:
    """Load one skill folder."""
    path = Path(directory)
    skill_file = path / SKILL_FILENAME
    if not skill_file.is_file():
        raise SkillParseError(f"{path} has no {SKILL_FILENAME}")
    return parse_skill_markdown(skill_file.read_text(encoding="utf-8"), directory=path)


def discover_skills(*roots: str | Path, max_depth: int = 3) -> list[Skill]:
    """Find every skill under *roots*.

    A malformed skill is skipped with a warning rather than raising: one bad
    folder in a shared skills directory must not stop the other forty loading.
    Duplicate ids resolve to the first found, so an earlier root overrides a
    later one — which is what lets a project's skills shadow the shipped set.
    """
    found: dict[str, Skill] = {}
    for root in roots:
        base = Path(root).expanduser()
        if not base.is_dir():
            continue
        for skill_file in sorted(base.rglob(SKILL_FILENAME)):
            if len(skill_file.relative_to(base).parts) > max_depth:
                continue
            try:
                skill = parse_skill_markdown(
                    skill_file.read_text(encoding="utf-8"), directory=skill_file.parent
                )
            except (SkillParseError, OSError) as error:
                logger.warning("Skipping %s: %s", skill_file, error)
                continue
            found.setdefault(skill.id, skill)
    return sorted(found.values(), key=lambda s: s.id)


def write_skill(directory: str | Path, skill: Skill) -> Path:
    """Write a skill to disk in the canonical format."""
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)

    lines = [
        "---",
        f"name: {skill.name}",
        f"description: {skill.description}",
    ]
    if skill.tools:
        lines.append(f"tools: [{', '.join(skill.tools)}]")
    if skill.trigger_phrases:
        phrases = ", ".join(f'"{p}"' for p in skill.trigger_phrases)
        lines.append(f"trigger_phrases: [{phrases}]")
    if skill.always_apply:
        lines.append("always_apply: true")
    lines.append(f"version: {skill.version}")
    lines.append("---")
    lines.append("")
    lines.append(skill.body.strip())
    lines.append("")

    target = path / SKILL_FILENAME
    target.write_text("\n".join(lines), encoding="utf-8")
    return target


def catalog_lines(skills: Iterable[Skill], *, max_chars: int = 120) -> Iterator[str]:
    """One line per skill, for the prompt. The whole point of the format."""
    for skill in sorted(skills, key=lambda s: s.id):
        summary = " ".join(skill.description.split())
        if len(summary) > max_chars:
            summary = summary[: max_chars - 1].rstrip() + "…"
        yield f"- {skill.id} — {skill.name}: {summary}"
