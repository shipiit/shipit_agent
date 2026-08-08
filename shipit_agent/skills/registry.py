"""Skill registries — in-memory and file-backed.

A registry holds :class:`Skill` objects and provides lookup, search,
and filtering. Two implementations:

- :class:`SkillRegistry` — pure in-memory, suitable for tests or
  programmatic skill management.
- :class:`FileSkillRegistry` — loads from a JSON file on disk (the
  packaged ``skills.json`` or a custom catalog).

The Agent uses the registry to:
1. Resolve string skill ids → Skill objects (``registry.get(id)``)
2. Auto-match skills from user prompts (``registry.search(query)``)
3. List all available skills (``registry.list()``)

Search scoring (in :meth:`SkillRegistry.search`):
    - Exact substring in name: +10
    - Exact substring in display_name: +8
    - Exact substring in trigger_phrases: +6
    - Exact substring in description: +5
    - Tag match: +4
    - Detailed description match: +3
    - Token overlap (fuzzy): +2 per overlapping token
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterator

from .skill import Skill


class SkillRegistry:
    """In-memory registry of :class:`Skill` objects.

    Supports register, unregister, get, list, search, and iteration.
    Used as the base for :class:`FileSkillRegistry`.
    """

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    # ── mutation ──────────────────────────────────────────────────────

    def register(self, skill: Skill) -> None:
        """Add or replace a skill in the registry."""
        self._skills[skill.id] = skill

    def unregister(self, skill_id: str) -> None:
        """Remove a skill by its *id*.  Raises ``KeyError`` if not found."""
        del self._skills[skill_id]

    # ── lookup ────────────────────────────────────────────────────────

    def get(self, skill_id: str) -> Skill | None:
        """Return a skill by id, or ``None``."""
        return self._skills.get(skill_id)

    def list(
        self,
        category: str | None = None,
        tag: str | None = None,
    ) -> list[Skill]:
        """Return skills, optionally filtered by *category* and/or *tag*."""
        results = list(self._skills.values())
        if category is not None:
            results = [s for s in results if s.category == category]
        if tag is not None:
            results = [s for s in results if tag in s.tags]
        return results

    def featured(self) -> list[Skill]:
        """Return all skills marked as *featured*."""
        return [s for s in self._skills.values() if s.featured]

    def search(self, query: str) -> list[Skill]:
        """Fuzzy-match *query* against skill metadata fields.

        Scoring weights (see module docstring for full breakdown):
        - Name/display_name exact match: highest signal
        - Trigger phrase match: strong signal (authored for matching)
        - Description match: medium signal
        - Tag match: medium signal
        - Token overlap: weak but broad (catches partial matches)

        Returns skills sorted by relevance (highest score first).
        """
        query_lower = query.lower()
        scored: list[tuple[float, Skill]] = []

        for skill in self._skills.values():
            score = 0.0

            # Exact substring in name is strongest signal.
            if query_lower in skill.name.lower():
                score += 10.0
            if query_lower in skill.display_name.lower():
                score += 8.0

            # Description matches.
            if query_lower in skill.description.lower():
                score += 5.0
            if query_lower in skill.detailed_description.lower():
                score += 3.0

            # Tag matches.
            for tag in skill.tags:
                if query_lower in tag.lower():
                    score += 4.0

            # Trigger phrase matches (high signal — authored for matching).
            for phrase in skill.trigger_phrases:
                if query_lower in phrase.lower():
                    score += 6.0

            # Token overlap for fuzzy matching (broad net).
            query_tokens = set(re.findall(r"[a-z0-9_+-]+", query_lower))
            haystack_tokens: set[str] = set()
            for text in [skill.name, skill.display_name, skill.description]:
                haystack_tokens.update(re.findall(r"[a-z0-9_+-]+", text.lower()))
            for tag in skill.tags:
                haystack_tokens.update(re.findall(r"[a-z0-9_+-]+", tag.lower()))
            for phrase in skill.trigger_phrases:
                haystack_tokens.update(re.findall(r"[a-z0-9_+-]+", phrase.lower()))

            overlap = query_tokens & haystack_tokens
            if overlap:
                score += len(overlap) * 2.0
            if query_tokens and query_tokens <= haystack_tokens:
                score += 4.0

            if score > 0:
                scored.append((score, skill))

        scored.sort(key=lambda t: t[0], reverse=True)
        return [s for _, s in scored]

    # ── dunder helpers ────────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self._skills)

    def __iter__(self) -> Iterator[Skill]:
        return iter(self._skills.values())

    def __contains__(self, skill_id: str) -> bool:  # type: ignore[override]
        return skill_id in self._skills


class FileSkillRegistry(SkillRegistry):
    """A :class:`SkillRegistry` backed by a JSON file.

    Loads skills on construction from the JSON file at *path*.
    Supports saving changes back with :meth:`save`.

    Expected file format::

        {
            "count": 3,
            "agents": [ { ... }, { ... }, { ... } ]
        }

    Each entry in ``agents`` is a skill dict (camelCase or snake_case
    keys — both are accepted by ``Skill.from_dict()``).

    The packaged catalog lives at ``shipit_agent/skills/skills.json``
    and is loaded automatically by the Agent unless ``skill_source``
    is overridden.
    """

    def __init__(self, path: str | Path) -> None:
        super().__init__()
        self._path = Path(path)
        if self._path.exists():
            self._load()

    # ── persistence ───────────────────────────────────────────────────

    def _load(self) -> None:
        """Read the JSON file and populate the registry."""
        with open(self._path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        agents = data.get("agents", [])
        for entry in agents:
            skill = Skill.from_dict(entry)
            self.register(skill)

    def save(self) -> None:
        """Write the current registry contents back to the JSON file."""
        skills = list(self._skills.values())
        payload = {
            "count": len(skills),
            "agents": [s.to_dict() for s in skills],
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)


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


def load_markdown_skill(path: str | Path) -> Skill:
    """Load a Codex/Claude-style ``SKILL.md`` into a runtime Skill."""
    source = Path(path)
    text = source.read_text(encoding="utf-8")
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
