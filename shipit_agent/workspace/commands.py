"""Slash commands & filesystem skills from ``.shipit/``.

Drop a markdown file at ``.shipit/commands/<name>.md`` and invoke it with
``agent.run("/<name> ...args")`` — the file body becomes the prompt, with
``$ARGUMENTS`` (and ``$1``, ``$2``, …) substituted. A leading YAML frontmatter
block is stripped. Project-local, file-based, no catalog edit required.
"""

from __future__ import annotations

import re
from pathlib import Path

_FRONTMATTER_RE = re.compile(r"^---\n.*?\n---\n", re.DOTALL)


def commands_dir(project_root: str | Path) -> Path:
    return Path(project_root).resolve() / ".shipit" / "commands"


def skills_dir(project_root: str | Path) -> Path:
    return Path(project_root).resolve() / ".shipit" / "skills"


def discover_commands(project_root: str | Path) -> dict[str, Path]:
    """Map ``command name -> .md path`` under ``.shipit/commands/``."""
    directory = commands_dir(project_root)
    if not directory.is_dir():
        return {}
    return {
        path.stem: path
        for path in sorted(directory.glob("*.md"))
        if path.is_file()
    }


def _strip_frontmatter(text: str) -> str:
    return _FRONTMATTER_RE.sub("", text, count=1)


def expand_command(project_root: str | Path, user_prompt: str) -> str | None:
    """Expand a ``/command`` invocation into its prompt, or return ``None``.

    ``/review src/app.py`` → the body of ``.shipit/commands/review.md`` with
    ``$ARGUMENTS`` → ``"src/app.py"`` and ``$1`` → ``"src/app.py"``. Returns
    ``None`` when the text isn't a known command (so normal prompts pass through).
    """
    if not user_prompt.startswith("/") or len(user_prompt) < 2:
        return None
    parts = user_prompt[1:].split(maxsplit=1)
    name = parts[0]
    args = parts[1].strip() if len(parts) > 1 else ""

    path = discover_commands(project_root).get(name)
    if path is None:
        return None
    try:
        body = _strip_frontmatter(path.read_text(encoding="utf-8")).strip()
    except Exception:
        return None

    body = body.replace("$ARGUMENTS", args)
    for index, token in enumerate(args.split(), start=1):
        body = body.replace(f"${index}", token)
    return body
