"""Every data file the package reads at runtime is listed to ship in the wheel.

The wheel built for 3.0.0 lacked skills/skills.json (the packaged skills
catalog Agent loads by default) and agents/agents.json: package-data never
named them, so an installed shipit-agent had neither. Python files ship by
being in a package; anything else ships only if a pattern names it.
"""

from __future__ import annotations

import fnmatch
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "shipit_agent"
#: Notes for people reading the source, not read by the package.
NOT_SHIPPED = {".md"}


def _patterns() -> dict[str, list[str]]:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    return config["tool"]["setuptools"]["package-data"]


def _shipped(path: Path, patterns: dict[str, list[str]]) -> bool:
    for package, globs in patterns.items():
        base = ROOT / Path(*package.split("."))
        if path.is_relative_to(base):
            relative = path.relative_to(base).as_posix()
            if any(fnmatch.fnmatch(relative, g) for g in globs):
                return True
    return False


def test_every_runtime_data_file_is_in_package_data() -> None:
    patterns = _patterns()
    data = [p for p in PACKAGE.rglob("*") if p.is_file() and p.suffix not in {".py", ".pyc", *NOT_SHIPPED}
            and "__pycache__" not in p.parts
            and not any(part.startswith(".") for part in p.relative_to(PACKAGE).parts)]
    missing = [str(p.relative_to(ROOT)) for p in data if not _shipped(p, patterns)]
    assert not missing, f"not shipped in the wheel: {missing}"
