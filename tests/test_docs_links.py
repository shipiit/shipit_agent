"""Published pages link only to published pages.

The docs site copies the pages in mkdocs.yml's nav and nothing else, so a
link from a published page to an unlisted one is a dead link there even
though the file exists in docs/.
"""

from __future__ import annotations

import posixpath
import re
from pathlib import Path

from test_docs_examples import DOCS, _nav_pages

LINK = re.compile(r"\]\(([^)#\s]+\.md)(?:#[^)]*)?\)")


def test_every_link_between_pages_targets_a_published_page() -> None:
    nav = set(_nav_pages())
    dead = []
    for page in sorted(nav):
        for match in LINK.finditer((DOCS / page).read_text()):
            if "://" in match.group(1):
                continue
            target = posixpath.normpath(posixpath.join(posixpath.dirname(page), match.group(1)))
            if target not in nav:
                dead.append(f"{page} -> {target}")
    assert not dead, "links to pages missing from the nav:\n" + "\n".join(dead)
