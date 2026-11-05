"""A repository's CLAUDE.md is read as project instructions, as in Claude Code."""

from __future__ import annotations

from pathlib import Path

from shipit_agent.workspace.project_memory import load_project_memory


def test_a_root_claude_md_is_loaded(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("Use pnpm, never npm.\n")
    assert "Use pnpm, never npm." in load_project_memory(tmp_path, include_user=False)


def test_a_dot_claude_folder_claude_md_is_loaded(tmp_path: Path) -> None:
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "CLAUDE.md").write_text("Tests live in tests/.\n")
    assert "Tests live in tests/." in load_project_memory(tmp_path, include_user=False)


def test_agents_md_and_claude_md_both_apply(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("Rule A\n")
    (tmp_path / "CLAUDE.md").write_text("Rule B\n")
    memory = load_project_memory(tmp_path, include_user=False)
    assert "Rule A" in memory and "Rule B" in memory


def test_a_claude_md_linked_to_agents_md_is_read_once(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("Only once\n")
    (tmp_path / "CLAUDE.md").symlink_to(tmp_path / "AGENTS.md")
    assert load_project_memory(tmp_path, include_user=False).count("Only once") == 1


def test_imports_work_from_claude_md(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "style.md").write_text("Prefer small functions.\n")
    (tmp_path / "CLAUDE.md").write_text("@docs/style.md\n")
    assert "Prefer small functions." in load_project_memory(
        tmp_path, include_user=False
    )
