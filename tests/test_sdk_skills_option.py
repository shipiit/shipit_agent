"""``AgentOptions(skills=...)``: limit which skills the main agent can use."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from shipit_agent.llms.base import LLMResponse
from shipit_agent.sdk import AgentOptions, build_agent
from shipit_agent.skills import SkillRegistry
from shipit_agent.skills.skill import Skill


class _Model:
    model = "claude-sonnet-5-5"

    def complete(self, **_: Any) -> LLMResponse:
        return LLMResponse(content="done")


def _registry() -> SkillRegistry:
    registry = SkillRegistry()
    for skill_id, name in (("pdf", "pdf-tools"), ("review", "code-review"), ("deploy", "deploy")):
        registry.register(Skill(id=skill_id, name=name, description=f"The {name} skill."))
    return registry


def _skills(tmp_path: Path, registry: SkillRegistry, skills: Any) -> set[str]:
    options = AgentOptions(
        llm=_Model(), tools=[], cwd=tmp_path, skills=skills,
        agent_options={"skill_registry": registry, "auto_project_skills": False},
    )
    agent = build_agent(options)
    return {skill.id for skill in agent.skill_registry.list()} if agent.skill_registry is not None else set()


def test_a_list_keeps_only_the_named_skills_by_id_or_name(tmp_path: Path) -> None:
    registry = _registry()
    assert _skills(tmp_path, registry, ["pdf", "code-review"]) == {"pdf", "review"}
    # The registry the caller passed in is left whole.
    assert {s.id for s in registry.list()} == {"pdf", "review", "deploy"}


def test_all_or_none_keeps_every_skill_and_an_empty_list_keeps_none(tmp_path: Path) -> None:
    assert _skills(tmp_path, _registry(), "all") == {"pdf", "review", "deploy"}
    assert _skills(tmp_path, _registry(), None) == {"pdf", "review", "deploy"}
    assert _skills(tmp_path, _registry(), []) == set()


@pytest.mark.parametrize("bad", [["pd*"], ["*"], ["has space"], [""], ["../escape"], "some", [3]])
def test_wildcards_and_malformed_names_are_refused(tmp_path: Path, bad: Any) -> None:
    with pytest.raises(ValueError, match="skills"):
        _skills(tmp_path, _registry(), bad)


def test_a_name_no_skill_has_is_refused_with_the_names_that_exist(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="nope") as caught:
        _skills(tmp_path, _registry(), ["pdf", "nope"])
    assert "code-review" in str(caught.value)


def test_a_filter_with_no_skills_found_at_all_is_an_error(tmp_path: Path) -> None:
    options = AgentOptions(llm=_Model(), tools=[], cwd=tmp_path, skills=["pdf"],
                           agent_options={"skill_registry": None, "skill_source": None, "auto_project_skills": False})
    with pytest.raises(ValueError, match="pdf"):
        build_agent(options)
