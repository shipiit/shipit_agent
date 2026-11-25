"""Workspace.resolve keeps paths inside the root: a sibling sharing its name prefix is outside."""

from __future__ import annotations

from pathlib import Path

import pytest

from shipit_agent.tools._shared import Workspace


@pytest.fixture
def layout(tmp_path: Path) -> tuple[Path, Path]:
    root, sibling = tmp_path / "project", tmp_path / "project-backup"
    root.mkdir()
    sibling.mkdir()
    return root, sibling


@pytest.mark.parametrize("make_path", [lambda s: "../project-backup/secret.txt", lambda s: str(s / "secret.txt")])
def test_a_sibling_with_the_same_prefix_is_outside(layout: tuple[Path, Path], make_path) -> None:
    root, sibling = layout
    with pytest.raises(ValueError, match="outside"):
        Workspace(root=root).resolve(make_path(sibling))


def test_a_symlink_to_a_sibling_is_outside(layout: tuple[Path, Path]) -> None:
    root, sibling = layout
    (root / "link").symlink_to(sibling, target_is_directory=True)
    with pytest.raises(ValueError, match="outside"):
        Workspace(root=root).resolve("link/secret.txt")


@pytest.mark.parametrize("path", ["src/app.py", ".", "src/../app.py", ""])
def test_paths_inside_resolve(layout: tuple[Path, Path], path: str) -> None:
    root, _ = layout
    assert Workspace(root=root).resolve(path).is_relative_to(root.resolve())
