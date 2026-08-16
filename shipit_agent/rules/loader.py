"""Discover rules from project files — the AGENTS.md house-style convention.

Two sources, both optional and both fail-soft (a missing or malformed file is
skipped, never fatal):

- **``AGENTS.md``** in the project root — the emerging cross-agent standard for
  "how to work in this repo". Its whole body becomes one global rule block.
- **``.shipit/rules/*.md``** — one rule per file, each with optional YAML
  frontmatter for scope::

      ---
      paths: ["tests/**"]
      tools: ["bash"]
      priority: 10
      ---
      Every test uses pytest; never add a unittest.TestCase.

Frontmatter needs PyYAML; without it a file still loads as an unscoped rule
(the body), so rules degrade gracefully rather than disappearing.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .rule import Rule

logger = logging.getLogger(__name__)


def load_project_rules(root: str | Path, *, include_agents_md: bool = True) -> list[Rule]:
    """Every rule discovered under ``root`` — AGENTS.md then .shipit/rules/*.md.

    ``include_agents_md=False`` skips AGENTS.md — useful when a caller already
    loads that file some other way (the Agent does, as flat project memory) and
    only wants the structured, scoped ``.shipit/rules/`` layer on top.
    """
    root_path = Path(root).expanduser()
    rules: list[Rule] = []
    if include_agents_md:
        rules.extend(_load_agents_md(root_path))
    rules.extend(_load_rules_dir(root_path / ".shipit" / "rules"))
    return rules


def _load_agents_md(root: Path) -> list[Rule]:
    for name in ("AGENTS.md", "AGENT.md"):
        path = root / name
        if not path.is_file():
            continue
        try:
            body = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError as err:
            logger.debug("could not read %s (%s)", path, err)
            return []
        if body:
            return [Rule(text=body, id="agents-md", priority=5, source=str(path))]
    return []


def _load_rules_dir(directory: Path) -> list[Rule]:
    if not directory.is_dir():
        return []
    rules: list[Rule] = []
    for path in sorted(directory.glob("*.md")):
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError as err:
            logger.debug("could not read rule file %s (%s)", path, err)
            continue
        meta, body = _split_frontmatter(raw)
        body = body.strip()
        if not body:
            continue
        rules.append(
            Rule(
                text=body,
                id=str(meta.get("id") or path.stem),
                paths=tuple(meta.get("paths", ()) or ()),
                tools=tuple(meta.get("tools", ()) or ()),
                priority=int(meta.get("priority", 0) or 0),
                source=str(path),
            )
        )
    return rules


def _split_frontmatter(raw: str) -> tuple[dict, str]:
    """Return ``(metadata, body)``. No/again-malformed frontmatter → ``({}, raw)``."""
    if not raw.startswith("---"):
        return {}, raw
    parts = raw.split("---", 2)
    if len(parts) < 3:
        return {}, raw
    _, front, body = parts
    try:
        import yaml
    except ImportError:
        # No YAML — treat the whole thing as body so the rule still loads.
        return {}, raw
    try:
        meta = yaml.safe_load(front) or {}
        return (meta if isinstance(meta, dict) else {}), body
    except yaml.YAMLError:
        logger.debug("malformed rule frontmatter; loading body only")
        return {}, body
