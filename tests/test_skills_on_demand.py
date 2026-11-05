"""Skills load on demand by default, as in Claude Code.

The system prompt lists each available skill in one line; the model reads a
skill's full instructions with ``load_skill`` only when the task calls for
it. Skills named explicitly in ``skills=[...]`` are still applied in full,
and keyword-matching a prompt no longer injects whole skills unasked.

What is listed: the project's own SKILL.md files, and any registry the
caller supplies. The packaged catalog is opt-in
(``advertise_packaged_skills=True``); an agent with nothing to list gets no
skill tool and no extra prompt.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from shipit_agent import Agent
from shipit_agent.core.models import ToolCall
from shipit_agent.deferral.core import resolve_deferred_names
from shipit_agent.llms import SimpleEchoLLM
from shipit_agent.llms.base import LLMResponse


def _agent(**options: Any) -> Agent:
    options.setdefault("advertise_packaged_skills", True)
    return Agent(llm=SimpleEchoLLM(), project_root=tempfile.mkdtemp(), **options)


def _project_with_skill() -> str:
    root = Path(tempfile.mkdtemp())
    skill = root / ".shipit" / "skills" / "release-notes"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: Release notes\ndescription: Use when writing release notes.\n---\n"
        "Group changes by user impact; lead with breaking changes.\n"
    )
    return str(root)


def test_on_demand_is_the_default() -> None:
    assert _agent().progressive_skills is True


def test_the_prompt_lists_skills_without_their_bodies() -> None:
    agent = _agent()
    prompt = agent._effective_prompt("Design a database schema for orders")
    assert "database-architect" in prompt
    body = agent.skill_registry.get("database-architect").prompt_text()
    assert body[:200] not in prompt


def test_keyword_matching_does_not_inject_a_skill_unasked() -> None:
    agent = _agent()
    assert agent._selected_skills("Design a database schema for orders") == []


def test_an_explicit_skill_is_still_applied_in_full() -> None:
    agent = _agent(skills=["database-architect"])
    prompt = agent._effective_prompt("anything")
    body = agent.skill_registry.get("database-architect").prompt_text()
    assert body[:200] in prompt


def test_load_skill_is_among_the_resident_tools() -> None:
    agent = Agent.with_builtins(
        llm=SimpleEchoLLM(),
        project_root=tempfile.mkdtemp(),
        advertise_packaged_skills=True,
    )
    tools = agent._effective_tools("hello")
    names = {t.name for t in tools}
    assert "load_skill" in names
    assert "load_skill" not in resolve_deferred_names(tools, "auto")


class _LoadsThenAnswers:
    def __init__(self) -> None:
        self.turn = 0
        self.saw: list[str] = []

    def complete(self, *, messages: Any, **_: Any) -> LLMResponse:
        self.turn += 1
        if self.turn == 1:
            return LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        name="load_skill", arguments={"skill_id": "database-architect"}
                    )
                ],
            )
        self.saw = [str(m.content) for m in messages if m.role == "tool"]
        return LLMResponse(content="Schema drafted.")


def test_the_model_reads_a_skill_when_it_asks() -> None:
    llm = _LoadsThenAnswers()
    agent = Agent(
        llm=llm, project_root=tempfile.mkdtemp(), advertise_packaged_skills=True
    )
    result = agent.run("Design a database schema for orders")
    assert result.output == "Schema drafted."
    body = agent.skill_registry.get("database-architect").prompt_text()
    assert any(body[:120] in text for text in llm.saw)


def test_the_old_behaviour_is_one_option_away() -> None:
    agent = _agent(progressive_skills=False)
    assert "load_skill" not in {t.name for t in agent._effective_tools("hello")}


def test_a_plain_agent_gets_no_skill_tool_and_no_catalog() -> None:
    agent = Agent(llm=SimpleEchoLLM(), project_root=tempfile.mkdtemp())
    assert "load_skill" not in {t.name for t in agent._effective_tools("hello")}
    assert agent._effective_prompt("hello") == agent._effective_prompt("other")
    assert "Available skills" not in agent._effective_prompt("hello")


def test_project_skills_are_listed_without_the_packaged_catalog() -> None:
    agent = Agent(llm=SimpleEchoLLM(), project_root=_project_with_skill())
    prompt = agent._effective_prompt("Write the release notes")
    assert "release-notes" in prompt
    assert "database-architect" not in prompt
    assert "load_skill" in {t.name for t in agent._effective_tools("hello")}


def test_a_callers_own_registry_is_listed() -> None:
    from shipit_agent.skills import SkillRegistry, load_markdown_skill

    root = _project_with_skill()
    registry = SkillRegistry()
    registry.register(
        load_markdown_skill(Path(root) / ".shipit/skills/release-notes/SKILL.md")
    )
    agent = Agent(
        llm=SimpleEchoLLM(),
        project_root=tempfile.mkdtemp(),
        skill_registry=registry,
    )
    assert "release-notes" in agent._effective_prompt("hello")


def test_a_skills_exact_trigger_phrase_still_applies_it() -> None:
    root = Path(tempfile.mkdtemp())
    skill = root / ".shipit" / "skills" / "incident"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nid: incident\ndescription: Investigate incidents.\n"
        "triggers: [production incident]\n---\nCorrelate logs first.\n"
    )
    agent = Agent(llm=SimpleEchoLLM(), project_root=str(root))
    assert [
        s.id for s in agent._selected_skills("Look at this production incident")
    ] == ["incident"]
    assert agent._selected_skills("Look at this incident report") == []


def test_trigger_phrases_of_unlisted_packaged_skills_do_nothing() -> None:
    agent = Agent(llm=SimpleEchoLLM(), project_root=tempfile.mkdtemp())
    packaged = [s for s in agent.skill_registry.list() if s.trigger_phrases]
    assert packaged, "the packaged catalog should have trigger phrases to test"
    phrase = packaged[0].trigger_phrases[0]
    assert agent._selected_skills(f"please {phrase}") == []
