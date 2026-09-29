"""Small context must not come at the expense of tool scope or instructions."""
from types import SimpleNamespace

import pytest

from shipit_agent import Agent, FunctionTool, Skill
from shipit_agent.llms.simple import ShipitLLM
from shipit_agent.skills.catalog import SkillCaps, SkillSession, LoadSkillTool, build_catalog
from shipit_agent.skills.markdown import Skill as MarkdownSkill
from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.helpers import build_tools_prompt


def test_identical_tool_guidance_is_emitted_once_with_scope():
    tools = [SimpleNamespace(name=f"lookup_{i}", read_only=True,
                             prompt="Only read records in the caller's tenant.") for i in range(40)]
    prompt = build_tools_prompt(tools)
    assert prompt.count("Only read records in the caller's tenant.") == 1
    assert "Guidance for lookup_0, lookup_1" in prompt
    tools[-1].prompt = "Only read public records."
    prompt = build_tools_prompt(tools)
    assert "Guidance for lookup_39:\nOnly read public records." in prompt


def test_skill_cannot_replace_host_scoped_tool(monkeypatch):
    custom = FunctionTool.from_callable(lambda path: "tenant-scoped", name="read_file")
    skill = Skill(id="review", tools=["read_file"], prompt_template="Review permitted files.")
    agent = Agent(llm=ShipitLLM(), tools=[custom], skills=[skill], auto_use_skills=False,
                  auto_project_memory=False, auto_project_skills=False, skill_source=None)

    def unnecessary(**kwargs):
        raise AssertionError("no missing tools: do not construct every builtin")

    monkeypatch.setattr("shipit_agent.agent_preparation.get_builtin_tool_map", unnecessary)
    effective = agent._effective_tools("review")
    assert next(t for t in effective if t.name == "read_file") is custom


def test_preselected_skills_do_not_trigger_a_second_catalog_scan(monkeypatch):
    agent = Agent(llm=ShipitLLM(), auto_use_skills=False,
                  auto_project_memory=False, auto_project_skills=False, skill_source=None)

    def unexpected(*args):
        raise AssertionError("skills were already selected for this run")

    monkeypatch.setattr(Agent, "_selected_skills", unexpected)
    assert agent._effective_prompt("hello", selected_skills=[]) == agent.prompt


def test_skill_reference_blocks_sibling_prefix_and_symlink_escape(tmp_path):
    root = tmp_path / "review"
    root.mkdir()
    sibling = tmp_path / "review-private"
    sibling.mkdir()
    (sibling / "secret.txt").write_text("outside")
    (root / "safe.txt").write_text("inside")
    (root / "linked.txt").symlink_to(sibling / "secret.txt")
    skill = MarkdownSkill(id="review", name="review", description="Review", directory=root)
    assert skill.reference("safe.txt") == "inside"
    for path in ("../review-private/secret.txt", "linked.txt", str(sibling / "secret.txt")):
        with pytest.raises(ValueError, match="escapes"):
            skill.reference(path)


def test_skill_catalog_is_bounded_without_truncating_loaded_instructions():
    body = "Full instruction. " * 100
    skill = MarkdownSkill(id="review", name="Review", description="Long metadata " * 100, body=body)
    [entry] = build_catalog([skill], caps=SkillCaps(description_chars=48))
    assert len(entry.description) == 48
    assert body not in entry.description
    session = SkillSession()
    loader = LoadSkillTool({"review": skill}, session)
    first = loader.run(ToolContext(prompt="review"), skill_id="review")
    second = loader.run(ToolContext(prompt="review"), skill_id="review")
    assert body.strip() in first.text
    assert body not in second.text
    assert len(second.text) < len(first.text)


def test_skill_loader_is_preferred_in_large_tool_catalog():
    from shipit_agent.deferral.policy import DiscoveryPolicy, select_resident

    tools = [FunctionTool.from_callable(lambda query: "ok", name=f"utility_{i}") for i in range(20)]
    loader = LoadSkillTool({}, SkillSession())
    tools.append(loader)
    search = FunctionTool.from_callable(lambda query: "ok", name="search_tools")
    tools.append(search)
    schemas = {tool.name: tool.schema() for tool in tools}
    selected = select_resident(tools, schemas, DiscoveryPolicy(), core=set(), search_name=search.name)
    assert loader.name in selected
    assert len(selected) == 10
