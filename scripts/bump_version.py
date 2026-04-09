#!/usr/bin/env python3
"""
Bump shipit-agent version in lockstep across every file that tracks it.

Usage:
    python scripts/bump_version.py 1.0.2

What it does (all in-place, no git writes):
    1. Validates the version format (must be X.Y.Z or X.Y.Z-prerelease)
    2. Validates that the git tag vX.Y.Z does NOT already exist
    3. Updates `version = "..."` in pyproject.toml
    4. Moves `## [Unreleased]` content → new `## [X.Y.Z] — YYYY-MM-DD` section
       in BOTH CHANGELOG.md (root) AND docs/changelog.md
    5. Updates the version comparison links at the bottom of CHANGELOG.md
    6. Prints a summary of what changed + suggested next commands

Exit codes:
    0 = success
    1 = version format invalid
    2 = git tag already exists
    3 = required file not found or unparseable
    4 = no [Unreleased] section to promote
"""
from __future__ import annotations

import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
CHANGELOG = ROOT / "CHANGELOG.md"
DOCS_CHANGELOG = ROOT / "docs" / "changelog.md"

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-.][\w.]+)?$")

GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def fail(code: int, message: str) -> None:
    print(f"{RED}error:{RESET} {message}", file=sys.stderr)
    sys.exit(code)


def info(message: str) -> None:
    print(f"{GREEN}✓{RESET} {message}")


def warn(message: str) -> None:
    print(f"{YELLOW}!{RESET} {message}")


def validate_version(version: str) -> None:
    if not VERSION_RE.match(version):
        fail(1, f"invalid version {version!r} — must be X.Y.Z (e.g. 1.0.2)")


def check_tag_absent(version: str) -> None:
    tag = f"v{version}"
    try:
        result = subprocess.run(
            ["git", "rev-parse", tag],
            capture_output=True,
            text=True,
            cwd=ROOT,
            check=False,
        )
    except FileNotFoundError:
        # Not a git repo or git not installed — skip tag check
        return
    if result.returncode == 0:
        fail(2, f"git tag {tag} already exists. Bump to a newer version.")


def read_current_version() -> str:
    text = PYPROJECT.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        fail(3, "could not find `version = \"...\"` in pyproject.toml")
    return match.group(1)


def bump_pyproject(new_version: str) -> str:
    text = PYPROJECT.read_text(encoding="utf-8")
    pattern = re.compile(r'^(version\s*=\s*)"[^"]+"', re.MULTILINE)
    new_text, count = pattern.subn(f'\\g<1>"{new_version}"', text, count=1)
    if count == 0:
        fail(3, "could not update `version` in pyproject.toml")
    PYPROJECT.write_text(new_text, encoding="utf-8")
    return new_text


def bump_changelog(new_version: str, release_date: str) -> None:
    """Promote `## [Unreleased]` → `## [X.Y.Z] — YYYY-MM-DD` in CHANGELOG.md."""
    if not CHANGELOG.exists():
        fail(3, f"{CHANGELOG} not found")

    text = CHANGELOG.read_text(encoding="utf-8")

    # Find the Unreleased section header (must be level-2 `## [Unreleased]`)
    unreleased_header = re.compile(r"^## \[Unreleased\].*$", re.MULTILINE)
    if not unreleased_header.search(text):
        fail(4, "no `## [Unreleased]` section found in CHANGELOG.md")

    # Replace the Unreleased header with a new Unreleased stub + versioned header
    new_header = (
        "## [Unreleased]\n"
        "\n"
        "Nothing yet.\n"
        "\n"
        "---\n"
        "\n"
        f"## [{new_version}] — {release_date}"
    )
    new_text = unreleased_header.sub(new_header, text, count=1)

    # Update the comparison links at the bottom of the file
    # Expected existing format:
    #     [Unreleased]: https://github.com/shipiit/shipit_agent/compare/vPREV...HEAD
    #     [PREV]: https://github.com/shipiit/shipit_agent/...
    current_version = read_current_version_from_text(text)
    link_unreleased = re.compile(
        r"^\[Unreleased\]: https://github\.com/[^/]+/[^/]+/compare/v[\d.]+\.\.\.HEAD$",
        re.MULTILINE,
    )
    if link_unreleased.search(new_text):
        new_text = link_unreleased.sub(
            f"[Unreleased]: https://github.com/shipiit/shipit_agent/compare/v{new_version}...HEAD",
            new_text,
            count=1,
        )
        # Insert the new version's compare link right after [Unreleased]
        new_link = f"[{new_version}]: https://github.com/shipiit/shipit_agent/compare/v{current_version}...v{new_version}"
        new_text = new_text.replace(
            f"[Unreleased]: https://github.com/shipiit/shipit_agent/compare/v{new_version}...HEAD",
            f"[Unreleased]: https://github.com/shipiit/shipit_agent/compare/v{new_version}...HEAD\n{new_link}",
            1,
        )

    CHANGELOG.write_text(new_text, encoding="utf-8")


def read_current_version_from_text(changelog_text: str) -> str:
    """Find the most recent version header in CHANGELOG.md."""
    match = re.search(r"^## \[(\d+\.\d+\.\d+(?:[-.][\w.]+)?)\]", changelog_text, re.MULTILINE)
    if match:
        return match.group(1)
    return "0.0.0"


def bump_docs_changelog(new_version: str, release_date: str) -> None:
    """Add a new version stub to docs/changelog.md (appended at the top)."""
    if not DOCS_CHANGELOG.exists():
        warn(f"{DOCS_CHANGELOG} not found — skipping docs changelog update")
        return

    text = DOCS_CHANGELOG.read_text(encoding="utf-8")
    # Look for the first `## v` heading
    first_version_header = re.compile(r"^## v\d+\.\d+\.\d+", re.MULTILINE)
    match = first_version_header.search(text)
    if not match:
        warn("no existing version header in docs/changelog.md — appending at top")
        stub = f"## v{new_version} — {release_date}\n\n_Release notes in progress._\n\n---\n\n"
        new_text = f"# Changelog\n\n{stub}" + text.removeprefix("# Changelog\n\n")
    else:
        # Insert new version header BEFORE the first existing one
        insertion = f"## v{new_version} — {release_date}\n\n_Release notes in progress. See CHANGELOG.md for details._\n\n---\n\n"
        new_text = text[: match.start()] + insertion + text[match.start():]

    DOCS_CHANGELOG.write_text(new_text, encoding="utf-8")


def run_command(cmd: list[str], description: str) -> bool:
    print(f"{DIM}$ {' '.join(cmd)}{RESET}")
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        warn(f"{description} failed (exit {result.returncode})")
        return False
    return True


def main() -> int:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} X.Y.Z", file=sys.stderr)
        return 1

    new_version = sys.argv[1].lstrip("v").strip()
    validate_version(new_version)
    check_tag_absent(new_version)

    current_version = read_current_version()
    if new_version == current_version:
        fail(1, f"new version {new_version} is the same as current. Bump higher.")

    release_date = date.today().isoformat()

    print(f"{BOLD}Bumping shipit-agent:{RESET} {current_version} → {new_version}")
    print(f"{BOLD}Release date:{RESET}        {release_date}")
    print()

    # 1. Update pyproject.toml
    bump_pyproject(new_version)
    info(f"pyproject.toml version → {new_version}")

    # 2. Update CHANGELOG.md
    bump_changelog(new_version, release_date)
    info(f"CHANGELOG.md — promoted [Unreleased] → [{new_version}]")

    # 3. Update docs/changelog.md
    bump_docs_changelog(new_version, release_date)
    info(f"docs/changelog.md — added v{new_version} stub")

    print()
    print(f"{BOLD}Next steps:{RESET}")
    print(f"  1. Review the diff:          {DIM}git diff{RESET}")
    print(f"  2. Fill in real notes:       {DIM}edit CHANGELOG.md + docs/changelog.md{RESET}")
    print(f"  3. Run full pre-flight:      {DIM}make new-release{RESET}")
    print(f"  4. Commit:                   {DIM}git add -A && git commit -m 'release: v{new_version}'{RESET}")
    print(f"  5. Tag:                      {DIM}git tag -a v{new_version} -m 'shipit-agent {new_version}'{RESET}")
    print(f"  6. Push:                     {DIM}git push origin main --tags{RESET}")
    print(f"  7. Publish to PyPI:          {DIM}make publish{RESET}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
