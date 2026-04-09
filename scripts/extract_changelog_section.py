#!/usr/bin/env python3
"""
Extract a specific version's section from CHANGELOG.md so it can be passed
to `gh release create --notes-file -` for the GitHub release body.

Usage:
    python scripts/extract_changelog_section.py 1.0.1
    python scripts/extract_changelog_section.py 1.0.1 > /tmp/notes.md

Reads CHANGELOG.md from the repo root, finds the ``## [X.Y.Z] — DATE`` heading,
and prints everything from there to the next ``## [`` heading (exclusive) or
the end of file.

Exits 0 with output, 1 if version not found.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = ROOT / "CHANGELOG.md"


def extract(version: str) -> str | None:
    if not CHANGELOG.exists():
        print(f"error: {CHANGELOG} not found", file=sys.stderr)
        sys.exit(2)

    text = CHANGELOG.read_text(encoding="utf-8")

    # Match `## [1.0.1] — 2026-04-09` or `## [1.0.1]` (any whitespace, em dash variations)
    escaped = re.escape(version)
    pattern = re.compile(
        rf"^## \[{escaped}\][^\n]*\n(.*?)(?=^## \[|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if not match:
        return None

    body = match.group(1).strip()
    # Trim trailing horizontal-rule separators (`---`) added by the bumper
    body = re.sub(r"\n---\s*$", "", body).strip()
    return body


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: extract_changelog_section.py X.Y.Z", file=sys.stderr)
        return 1

    version = sys.argv[1].lstrip("v").strip()
    body = extract(version)
    if body is None:
        print(f"error: no [## {version}] section found in CHANGELOG.md", file=sys.stderr)
        return 1

    print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
