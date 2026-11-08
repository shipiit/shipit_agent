"""Build docs/changelog.md from CHANGELOG.md, the one changelog people edit.

    python scripts/build_docs_changelog.py

Release headings become "## v3.0.0 — 2026-11-07". Releases 1.0.18 and older
come from scripts/changelog/1.0.x.md, the docs' fuller write-ups of them. Links into docs/ become
docs-relative when the page is in the published nav, and every other relative
link points at the file on GitHub, so the docs site never links a missing page.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO_URL = "https://github.com/shipiit/shipit_agent/blob/main/"
HEADING = re.compile(r"^## \[([^\]]+)\]\s*[—-]\s*(.+)$")
ARCHIVE = ROOT / "scripts" / "changelog" / "1.0.x.md"
#: The first release the archive covers; CHANGELOG.md is used above it.
ARCHIVE_FROM = "## [1.0.18]"
LINK = re.compile(r"\]\((?!https?://|#|mailto:)([^)\s]+)\)")


def nav_pages() -> set[str]:
    """Pages listed in mkdocs.yml's nav, relative to docs/."""
    text = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
    nav = text[text.index("\nnav:") :]
    return set(re.findall(r":\s*([\w./-]+\.md)\s*$", nav, re.M))


def _link(target: str, pages: set[str]) -> str:
    path, _, anchor = target.partition("#")
    suffix = f"#{anchor}" if anchor else ""
    if path.startswith("docs/") and path[len("docs/") :] in pages:
        return f"]({path[len('docs/'):]}{suffix})"
    return f"]({REPO_URL}{path.lstrip('./')}{suffix})"


def build(changelog: str, pages: set[str], archive: str = "") -> str:
    out = []
    for line in changelog.splitlines():
        if archive and line.startswith(ARCHIVE_FROM):
            out.extend(archive.rstrip().splitlines())
            break
        heading = HEADING.match(line)
        if heading:
            version, date = heading.groups()
            line = "## Unreleased" if version.lower() == "unreleased" else f"## v{version} — {date.strip()}"
        elif line.strip().lower() == "## [unreleased]":
            line = "## Unreleased"
        out.append(LINK.sub(lambda m: _link(m.group(1), pages), line))
    return "\n".join(out).rstrip() + "\n"


def main() -> None:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    archive = ARCHIVE.read_text(encoding="utf-8")
    (ROOT / "docs" / "changelog.md").write_text(build(changelog, nav_pages(), archive), encoding="utf-8")
    print("wrote docs/changelog.md")


if __name__ == "__main__":
    main()
