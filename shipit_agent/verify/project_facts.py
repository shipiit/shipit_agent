"""Detect a project's verify commands once — so the agent doesn't rediscover them.

The reference agent sniffs the project's test/build commands from its manifests a
single time and hands them to the model up front, instead of making it guess how
to run the tests every session. This does the same, cheaply and read-only:

- **Node** — ``package.json`` ``scripts.test`` → ``npm test`` (skips the
  no-op ``echo "Error: no test specified"`` default).
- **Python** — ``pyproject.toml`` ``[tool.pytest]`` / ``pytest.ini`` /
  ``setup.cfg`` ``[tool:pytest]``, or a ``tests/`` dir → ``pytest``.
- **Make** — a ``test:`` target in a ``Makefile`` → ``make test``.
- **Script** — ``scripts/run_tests.sh`` → ``bash scripts/run_tests.sh``.

Best-effort and never raises: an unreadable or exotic project just yields no
commands, and the verify gate then treats a run as ``not_applicable``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


def detect_verify_commands(root: str | Path) -> list[str]:
    """The commands that verify this project, best-effort, de-duplicated."""
    root_path = Path(root).expanduser()
    commands: list[str] = []

    def add(command: str) -> None:
        if command and command not in commands:
            commands.append(command)

    _detect_node(root_path, add)
    _detect_python(root_path, add)
    _detect_make(root_path, add)
    _detect_script(root_path, add)
    return commands


def _detect_node(root: Path, add) -> None:
    package = root / "package.json"
    if not package.is_file():
        return
    try:
        data = json.loads(package.read_text(encoding="utf-8", errors="replace"))
    except (ValueError, OSError):
        return
    scripts = data.get("scripts") if isinstance(data, dict) else None
    if not isinstance(scripts, dict):
        return
    test = str(scripts.get("test", ""))
    # npm's placeholder default is not a real test command.
    if test and "no test specified" not in test:
        add("npm test")


def _detect_python(root: Path, add) -> None:
    if (root / "pytest.ini").is_file():
        add("pytest")
        return
    for name, marker in (("pyproject.toml", "[tool.pytest"), ("setup.cfg", "[tool:pytest]")):
        path = root / name
        if path.is_file():
            try:
                if marker in path.read_text(encoding="utf-8", errors="replace"):
                    add("pytest")
                    return
            except OSError:
                pass
    if (root / "tests").is_dir() or (root / "test").is_dir():
        add("pytest")


def _detect_make(root: Path, add) -> None:
    makefile = root / "Makefile"
    if not makefile.is_file():
        return
    try:
        text = makefile.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    # A `test:` target at the start of a line (not `pretest:` etc.).
    if re.search(r"^test\s*:", text, re.MULTILINE):
        add("make test")


def _detect_script(root: Path, add) -> None:
    if (root / "scripts" / "run_tests.sh").is_file():
        add("bash scripts/run_tests.sh")
