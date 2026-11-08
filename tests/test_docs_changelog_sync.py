"""docs/changelog.md is generated from CHANGELOG.md and must not drift."""

from __future__ import annotations

from scripts.build_docs_changelog import ARCHIVE, ROOT, build, nav_pages


def test_docs_changelog_is_generated_from_changelog() -> None:
    expected = build(
        (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), nav_pages(), ARCHIVE.read_text(encoding="utf-8")
    )
    actual = (ROOT / "docs" / "changelog.md").read_text(encoding="utf-8")
    assert actual == expected, "run: python scripts/build_docs_changelog.py"


def test_release_headings_and_links_are_rewritten() -> None:
    pages = {"guides/mcp.md"}
    out = build(
        "## [Unreleased]\n## [3.0.0] - 2026-11-07\nSee [MCP](docs/guides/mcp.md#x), [notes](docs/private.md) and [site](https://x.dev).",
        pages,
    )
    assert out.splitlines() == [
        "## Unreleased",
        "## v3.0.0 — 2026-11-07",
        "See [MCP](guides/mcp.md#x), [notes](https://github.com/shipiit/shipit_agent/blob/main/docs/private.md) and [site](https://x.dev).",
    ]


def test_archived_releases_replace_the_older_changelog_sections() -> None:
    out = build("## [2.0.0] - 2026-09-01\nnew\n## [1.0.18] — 2026-07-31\nshort\n", set(), "## v1.0.18 — 2026-07-31\nfull write-up\n")
    assert out == "## v2.0.0 — 2026-09-01\nnew\n## v1.0.18 — 2026-07-31\nfull write-up\n"
