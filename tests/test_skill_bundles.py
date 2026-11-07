"""A loaded skill tells the model where it lives and what files it bundles.

Claude Code skills ship scripts and reference files next to SKILL.md. The
model can only run "scripts/fill.py" if it knows the skill's folder, so
load_skill reports the base directory and lists the bundled files.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from shipit_agent import Agent
from shipit_agent.llms import SimpleEchoLLM
from shipit_agent.skills import load_markdown_skill
from shipit_agent.tools.base import ToolContext


def _project() -> Path:
    root = Path(tempfile.mkdtemp())
    skill = root / ".claude" / "skills" / "pdf-tools"
    (skill / "scripts").mkdir(parents=True)
    (skill / "scripts" / "fill.py").write_text("print('fill')\n")
    (skill / "reference.md").write_text("Form fields\n")
    (skill / "SKILL.md").write_text(
        "---\nname: pdf-tools\ndescription: Use for filling PDF forms.\n---\n"
        "Run scripts/fill.py; see reference.md.\n"
    )
    return root


def _load(root: Path, skill_id: str = "pdf-tools") -> str:
    agent = Agent(llm=SimpleEchoLLM(), project_root=str(root))
    tool = next(t for t in agent._effective_tools("x") if t.name == "load_skill")
    return tool.run(ToolContext(prompt="x"), skill_id=skill_id).text


def test_a_skill_md_records_its_folder() -> None:
    root = _project()
    skill = load_markdown_skill(root / ".claude/skills/pdf-tools/SKILL.md")
    assert Path(skill.directory) == (root / ".claude/skills/pdf-tools").resolve()


def test_loading_reports_the_base_directory_and_bundled_files() -> None:
    root = _project()
    text = _load(root)
    folder = (root / ".claude/skills/pdf-tools").resolve()
    assert f"Base directory: {folder}" in text
    assert "scripts/fill.py" in text and "reference.md" in text
    assert "SKILL.md" not in text.split("Bundled files")[-1]


def test_a_skill_with_no_extra_files_lists_none() -> None:
    root = Path(tempfile.mkdtemp())
    skill = root / ".shipit" / "skills" / "plain"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: plain\ndescription: Use always.\n---\nBe brief.\n"
    )
    text = _load(root, "plain")
    assert "Base directory" in text
    assert "Bundled files" not in text


def test_a_large_bundle_is_listed_with_a_cap() -> None:
    root = _project()
    many = root / ".claude/skills/pdf-tools/assets"
    many.mkdir()
    for index in range(80):
        (many / f"img{index:02}.png").write_text("x")
    text = _load(root)
    assert "more" in text
    assert text.count("assets/img") <= 40
