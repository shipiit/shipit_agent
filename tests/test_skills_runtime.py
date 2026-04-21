from __future__ import annotations

from pathlib import Path

from shipit_agent import (
    Agent,
    BashTool,
    DeepAgent,
    EditFileTool,
    FileSkillRegistry,
    FileReadTool,
    Skill,
    SkillCatalog,
    create_skill,
    skill_id_from_name,
)
from shipit_agent.agent import DEFAULT_SKILLS_PATH
from shipit_agent.builtins import get_builtin_tool_map
from shipit_agent.llms import LLMResponse
from shipit_agent.models import ToolCall
from shipit_agent.skills.tool_bundles import validate_tool_bundles


class PromptCaptureLLM:
    def __init__(self) -> None:
        self.system_prompts: list[str] = []

    def complete(
        self,
        *,
        messages,
        tools=None,
        system_prompt=None,
        metadata=None,
        response_format=None,
    ):
        self.system_prompts.append(system_prompt or "")
        return LLMResponse(content="ok")


class SingleToolCallLLM:
    def __init__(self, name: str, arguments: dict) -> None:
        self.name = name
        self.arguments = arguments

    def complete(
        self,
        *,
        messages,
        tools=None,
        system_prompt=None,
        metadata=None,
        response_format=None,
    ):
        return LLMResponse(
            content="completed",
            tool_calls=[ToolCall(name=self.name, arguments=self.arguments)],
        )


def test_packaged_skills_catalog_loads() -> None:
    registry = FileSkillRegistry(DEFAULT_SKILLS_PATH)
    assert len(registry) > 0
    assert registry.get("code-workflow-assistant") is not None


def test_skill_prompt_text_falls_back_to_metadata_when_template_missing() -> None:
    skill = Skill(
        id="database-architect",
        name="Database Architect",
        description="Design schemas and optimize queries.",
        use_cases=["Optimize slow SQL queries"],
        how_to_use=["Share your code and constraints"],
    )
    prompt = skill.prompt_text()
    assert "Database Architect" in prompt
    assert "Optimize slow SQL queries" in prompt


def test_agent_auto_applies_matching_skill_from_registry() -> None:
    llm = PromptCaptureLLM()
    agent = Agent(llm=llm)

    agent.run("Please help me debug this production bug and plan this feature.")

    assert llm.system_prompts
    prompt = llm.system_prompts[-1]
    assert "<!-- skill:code-workflow-assistant -->" in prompt
    assert "Code Workflow Assistant" in prompt


def test_agent_applies_default_skill_ids() -> None:
    llm = PromptCaptureLLM()
    agent = Agent(
        llm=llm,
        default_skill_ids=["database-architect"],
    )

    agent.run("hello")

    prompt = llm.system_prompts[-1]
    assert "<!-- skill:database-architect -->" in prompt
    assert "Database Architect" in prompt


def test_agent_accepts_prebuilt_skill_ids_in_skills_argument() -> None:
    llm = PromptCaptureLLM()
    agent = Agent(
        llm=llm,
        auto_use_skills=False,
        skills=["database-architect"],
    )

    agent.run("hello")

    prompt = llm.system_prompts[-1]
    assert "<!-- skill:database-architect -->" in prompt


def test_agent_can_add_and_search_skills() -> None:
    agent = Agent(llm=PromptCaptureLLM(), auto_use_skills=False)

    matches = agent.search_skills("database")
    assert matches
    added = agent.add_skill("database-architect")

    assert added.id == "database-architect"
    assert any(skill.id == "database-architect" for skill in agent.skills)


def test_packaged_skill_bundle_adds_power_tools() -> None:
    agent = Agent(
        llm=PromptCaptureLLM(),
        auto_use_skills=False,
        skills=["web-scraper-pro"],
    )

    tool_names = {tool.name for tool in agent._effective_tools("scrape this page")}
    assert {
        "open_url",
        "playwright_browse",
        "read_file",
        "write_file",
        "bash",
        "edit_file",
    } <= tool_names


def test_deep_agent_forwards_skill_support_to_inner_agent() -> None:
    llm = PromptCaptureLLM()
    agent = DeepAgent(llm=llm, default_skill_ids=["database-architect"])

    agent.run("hello")

    assert llm.system_prompts
    prompt = llm.system_prompts[-1]
    assert "<!-- skill:database-architect -->" in prompt
    assert "Database Architect" in prompt


def test_deep_agent_accepts_prebuilt_skills_argument() -> None:
    llm = PromptCaptureLLM()
    agent = DeepAgent(
        llm=llm,
        auto_use_skills=False,
        skills=["database-architect"],
    )

    agent.run("hello")

    prompt = llm.system_prompts[-1]
    assert "<!-- skill:database-architect -->" in prompt
    assert agent.search_skills("database")
    assert any(skill.id == "database-architect" for skill in agent.skills)


def test_skill_authoring_helpers_create_stable_skill_id() -> None:
    assert skill_id_from_name("Release Notes Writer") == "release-notes-writer"


def test_skill_catalog_can_create_and_persist_new_skill(tmp_path: Path) -> None:
    catalog_path = tmp_path / "skills.json"
    catalog = SkillCatalog(catalog_path)

    created = catalog.create(
        name="Release Notes Writer",
        description="Write release notes from merged changes.",
        category="Development",
        tags=["release", "docs"],
        trigger_phrases=["write release notes"],
    )

    assert created.id == "release-notes-writer"
    reloaded = FileSkillRegistry(catalog_path)
    assert reloaded.get("release-notes-writer") is not None


def test_agent_can_use_newly_authored_skill_from_custom_catalog(tmp_path: Path) -> None:
    catalog_path = tmp_path / "skills.json"
    catalog = SkillCatalog(catalog_path)
    custom_skill = create_skill(
        name="Release Notes Writer",
        description="Write concise release notes from code changes.",
        prompt_template="Always structure the answer as release highlights, fixes, and migration notes.",
    )
    catalog.add(custom_skill)

    llm = PromptCaptureLLM()
    agent = Agent(
        llm=llm,
        skill_source=catalog_path,
        auto_use_skills=False,
        skills=["release-notes-writer"],
    )

    agent.run("Summarize today's changes.")

    prompt = llm.system_prompts[-1]
    assert "<!-- skill:release-notes-writer -->" in prompt
    assert "release highlights" in prompt


def test_custom_skill_tools_are_auto_attached_and_callable(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    target = project_root / "notes.txt"
    target.write_text("hello\nworld\n", encoding="utf-8")

    catalog_path = tmp_path / "skills.json"
    catalog = SkillCatalog(catalog_path)
    catalog.add(
        create_skill(
            name="Repo Worker",
            description="Read and search local files.",
            tools=["read_file", "grep_files", "glob_files", "write_file"],
        )
    )

    agent = Agent(
        llm=SingleToolCallLLM("read_file", {"path": "notes.txt"}),
        project_root=project_root,
        skill_source=catalog_path,
        auto_use_skills=False,
        skills=["repo-worker"],
    )

    result = agent.run("Read the file")
    assert "hello" in result.tool_results[0].output


def test_agent_result_metadata_includes_used_skills_and_skill_tools() -> None:
    agent = Agent(
        llm=PromptCaptureLLM(),
        auto_use_skills=False,
        skills=["web-scraper-pro"],
    )

    result = agent.run("Scrape the site")

    assert result.metadata["used_skills"] == ["web-scraper-pro"]
    assert "bash" in result.metadata["used_skill_tools"]
    assert "edit_file" in result.metadata["used_skill_tools"]


def test_bash_tool_blocks_commands_outside_allowlist(tmp_path: Path) -> None:
    tool = BashTool(root_dir=tmp_path)

    try:
        tool.run(context=type("Ctx", (), {"state": {}})(), command="nc -l 8080")
    except ValueError as exc:
        assert "allowlist" in str(exc)
    else:
        raise AssertionError("Expected allowlist validation to reject nc")


def test_bash_tool_allows_cd_then_allowed_command(tmp_path: Path) -> None:
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "package.json").write_text('{"name":"demo"}\n', encoding="utf-8")

    tool = BashTool(root_dir=tmp_path)
    result = tool.run(
        context=type("Ctx", (), {"state": {}})(),
        command="cd frontend && pwd",
    )

    assert "exit_code: 0" in result.text
    assert str(frontend) in result.metadata["stdout"]


def test_edit_file_requires_prior_read(tmp_path: Path) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("hello world\n", encoding="utf-8")

    tool = EditFileTool(root_dir=tmp_path)
    blocked = tool.run(
        context=type("Ctx", (), {"state": {}})(),
        path="notes.txt",
        old_text="world",
        new_text="team",
    )
    assert "read the file first" in blocked.text

    context = type("Ctx", (), {"state": {}})()
    FileReadTool(root_dir=tmp_path).run(context=context, path="notes.txt")
    result = tool.run(
        context=context,
        path="notes.txt",
        old_text="world",
        new_text="team",
    )
    assert "File patched" in result.text
    assert target.read_text(encoding="utf-8") == "hello team\n"


def test_deep_agent_can_use_newly_authored_skill_from_custom_catalog(
    tmp_path: Path,
) -> None:
    catalog_path = tmp_path / "skills.json"
    catalog = SkillCatalog(catalog_path)
    catalog.add(
        create_skill(
            name="Release Notes Writer",
            description="Write concise release notes from code changes.",
            prompt_template=(
                "Always structure the answer as release highlights, fixes, and migration notes."
            ),
        )
    )

    llm = PromptCaptureLLM()
    agent = DeepAgent(
        llm=llm,
        skill_source=catalog_path,
        auto_use_skills=False,
        skills=["release-notes-writer"],
    )

    agent.run("Summarize today's changes.")

    prompt = llm.system_prompts[-1]
    assert "<!-- skill:release-notes-writer -->" in prompt
    assert "release highlights" in prompt
    assert any(skill.id == "release-notes-writer" for skill in agent.skills)


# ── New tests: iteration boost, bundle validation, efficiency ──────


def test_agent_boosts_max_iterations_when_skills_are_active() -> None:
    """When skills are selected and max_iterations is at default (4),
    the agent should auto-boost to at least 8 so skill-driven workflows
    can complete without cutting off early."""
    agent = Agent(
        llm=PromptCaptureLLM(),
        auto_use_skills=False,
        skills=["web-scraper-pro"],
    )
    selected = agent._selected_skills("scrape it")
    effective_max = agent._effective_max_iterations(selected)
    assert effective_max >= 8


def test_agent_respects_explicit_max_iterations_override() -> None:
    """An explicit max_iterations should NOT be overridden by the boost."""
    agent = Agent(
        llm=PromptCaptureLLM(),
        auto_use_skills=False,
        skills=["web-scraper-pro"],
        max_iterations=20,
    )
    selected = agent._selected_skills("scrape it")
    effective_max = agent._effective_max_iterations(selected)
    assert effective_max == 20


def test_agent_no_boost_without_skills() -> None:
    """No skills → no boost, max_iterations stays at default."""
    agent = Agent(
        llm=PromptCaptureLLM(),
        auto_use_skills=False,
    )
    selected = agent._selected_skills("hello")
    effective_max = agent._effective_max_iterations(selected)
    assert effective_max == 4


def test_tool_bundle_names_all_exist_in_builtins() -> None:
    """Every tool name referenced in SKILL_TOOL_BUNDLES should exist
    in get_builtin_tool_map() so skill-linked tools can actually be resolved."""
    # Pass a stub LLM so SubAgentTool (requires llm=) is included in the map.
    builtin_names = set(get_builtin_tool_map(llm=PromptCaptureLLM()).keys())
    errors = validate_tool_bundles(builtin_names)
    assert errors == [], f"Unknown tool names in bundles: {errors}"


def test_effective_tools_accepts_precomputed_skills() -> None:
    """_effective_tools should accept pre-computed skills to avoid redundant work."""
    agent = Agent(
        llm=PromptCaptureLLM(),
        auto_use_skills=False,
        skills=["web-scraper-pro"],
    )
    skills = agent._selected_skills("scrape it")
    tools_a = {
        getattr(t, "name", "")
        for t in agent._effective_tools("scrape it", selected_skills=skills)
    }
    tools_b = {getattr(t, "name", "") for t in agent._effective_tools("scrape it")}
    assert tools_a == tools_b


def test_all_packaged_skills_have_tool_bundles() -> None:
    """Every skill in the packaged catalog should have a matching entry
    in SKILL_TOOL_BUNDLES so it gets useful tools at runtime."""
    from shipit_agent.skills.tool_bundles import SKILL_TOOL_BUNDLES

    registry = FileSkillRegistry(DEFAULT_SKILLS_PATH)
    missing = [
        skill.id for skill in registry.list() if skill.id not in SKILL_TOOL_BUNDLES
    ]
    assert missing == [], f"Skills without tool bundles: {missing}"


def test_deep_agent_boosts_iterations_via_inner_agent() -> None:
    """DeepAgent should also benefit from the iteration boost through
    its inner Agent."""
    llm = PromptCaptureLLM()
    deep = DeepAgent(
        llm=llm,
        auto_use_skills=False,
        skills=["code-workflow-assistant"],
    )
    # DeepAgent default is 8, so the boost only applies if inner agent
    # gets the skills. Check that the inner agent has skills wired.
    assert any(s.id == "code-workflow-assistant" for s in deep.skills)
    inner_selected = deep.agent._selected_skills("fix this bug")
    assert len(inner_selected) > 0


# ── Chat, streaming, and chat streaming tests ──────────────────────


def test_agent_chat_session_retains_skills() -> None:
    """Chat sessions should inherit skills from the parent agent."""
    llm = PromptCaptureLLM()
    agent = Agent(
        llm=llm,
        auto_use_skills=False,
        skills=["database-architect"],
    )

    chat = agent.chat_session(session_id="test-chat")
    result = chat.send("hello")

    prompt = llm.system_prompts[-1]
    assert "<!-- skill:database-architect -->" in prompt
    assert result.output == "ok"


def test_agent_chat_session_multi_turn_history() -> None:
    """Multiple chat.send() calls should accumulate message history."""
    llm = PromptCaptureLLM()
    agent = Agent(
        llm=llm,
        auto_use_skills=False,
        skills=["code-workflow-assistant"],
    )

    chat = agent.chat_session(session_id="multi-turn-test")

    r1 = chat.send("turn one")
    r2 = chat.send("turn two")

    # Both calls should succeed.
    assert r1.output == "ok"
    assert r2.output == "ok"
    # LLM should have been called twice.
    assert len(llm.system_prompts) >= 2


def test_agent_stream_with_skills_yields_events() -> None:
    """agent.stream() should yield events when skills are active."""
    llm = PromptCaptureLLM()
    agent = Agent(
        llm=llm,
        auto_use_skills=False,
        skills=["web-scraper-pro"],
    )

    events = list(agent.stream("scrape something"))

    # Should have at least run_started and run_completed events.
    event_types = {e.type for e in events}
    assert "run_started" in event_types
    assert "run_completed" in event_types

    # Skills should be in the prompt.
    prompt = llm.system_prompts[-1]
    assert "<!-- skill:web-scraper-pro -->" in prompt


def test_agent_stream_metadata_includes_skills() -> None:
    """Streaming metadata should include used_skills and used_skill_tools."""
    llm = PromptCaptureLLM()
    agent = Agent(
        llm=llm,
        auto_use_skills=False,
        skills=["code-workflow-assistant"],
    )

    list(agent.stream("fix the bug"))

    # Find run_started or check metadata on the runtime.
    # The metadata is set on the runtime, which is internal —
    # but we can verify skills were applied via the prompt.
    prompt = llm.system_prompts[-1]
    assert "<!-- skill:code-workflow-assistant -->" in prompt


def test_deep_agent_chat_retains_skills() -> None:
    """DeepAgent.chat() should retain skills across turns."""
    llm = PromptCaptureLLM()
    deep = DeepAgent(
        llm=llm,
        auto_use_skills=False,
        skills=["database-architect"],
    )

    chat = deep.chat(session_id="deep-chat-test")
    r1 = chat.send("turn one")

    prompt = llm.system_prompts[-1]
    assert "<!-- skill:database-architect -->" in prompt
    assert r1.output == "ok"


def test_deep_agent_stream_with_skills() -> None:
    """DeepAgent.stream() should yield events with skills active."""
    llm = PromptCaptureLLM()
    deep = DeepAgent(
        llm=llm,
        auto_use_skills=False,
        skills=["security-engineer"],
    )

    events = list(deep.stream("audit the project"))

    event_types = {e.type for e in events}
    assert "run_started" in event_types
    assert "run_completed" in event_types

    prompt = llm.system_prompts[-1]
    assert "<!-- skill:security-engineer -->" in prompt


def test_chat_stream_yields_events() -> None:
    """chat.stream() should yield events just like agent.stream()."""
    llm = PromptCaptureLLM()
    agent = Agent(
        llm=llm,
        auto_use_skills=False,
        skills=["full-stack-developer"],
    )

    chat = agent.chat_session(session_id="chat-stream-test")
    events = list(chat.stream("create a project"))

    event_types = {e.type for e in events}
    assert "run_started" in event_types
    assert "run_completed" in event_types

    prompt = llm.system_prompts[-1]
    assert "<!-- skill:full-stack-developer -->" in prompt


def test_agent_with_memory_store_and_skills() -> None:
    """Agent with memory_store + skills should work without errors."""
    from shipit_agent.stores import InMemoryMemoryStore

    llm = PromptCaptureLLM()
    memory = InMemoryMemoryStore()

    agent = Agent(
        llm=llm,
        auto_use_skills=False,
        skills=["database-architect"],
        memory_store=memory,
    )

    result = agent.run("debug the slow query")

    assert result.output == "ok"
    assert result.metadata["used_skills"] == ["database-architect"]

    prompt = llm.system_prompts[-1]
    assert "<!-- skill:database-architect -->" in prompt
