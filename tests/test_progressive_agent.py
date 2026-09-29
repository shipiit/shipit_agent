from concurrent.futures import ThreadPoolExecutor

import pytest

from shipit_agent import Agent, FunctionTool, Skill, SkillRegistry
from shipit_agent.llms.base import LLMResponse
from shipit_agent.models import ToolCall
from shipit_agent.permissions import PermissionEngine


def make_agent(llm, **kwargs):
    registry = SkillRegistry()
    registry.register(Skill(id="evidence", name="Evidence", description="Assess evidence carefully",
                            prompt_template="DISTINCT_SKILL_BODY: distinguish evidence and uncertainty."))
    registry.register(Skill(id="hidden", name="Hidden", description="Hidden workflow",
                            is_admin_enabled=False, prompt_template="HIDDEN_BODY"))
    return Agent(llm=llm, skill_registry=registry, skill_source=None, progressive_skills=True,
                 auto_project_memory=False, auto_project_skills=False, **kwargs)


class SkillModel:
    def complete(self, *, messages, tools=None, **kwargs):
        loaded = any(m.role == "tool" and "DISTINCT_SKILL_BODY" in str(m.content) for m in messages)
        if loaded:
            return LLMResponse(content="Applied evidence guidance.")
        assert "DISTINCT_SKILL_BODY" not in str([m.content for m in messages if m.role == "system"])
        assert "HIDDEN_BODY" not in str(messages)
        return LLMResponse(tool_calls=[ToolCall(name="load_skill", arguments={"skill_id": "evidence"})])


@pytest.mark.parametrize("stream", [False, True])
def test_ordinary_agent_loads_skill_on_demand(stream):
    agent = make_agent(SkillModel())
    if stream:
        events = list(agent.stream("Assess this evidence"))
        assert next(e for e in events if e.type == "final_answer").payload["content"] == "Applied evidence guidance."
    else:
        result = agent.run("Assess this evidence")
        assert "Applied evidence guidance." in result.output


def test_progressive_skill_state_is_not_shared_between_chats():
    agent = make_agent(SkillModel())
    chats = [agent.chat_session(session_id=f"chat-{i}") for i in range(4)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda chat: chat.send("Assess evidence"), chats))
    assert all("Applied evidence guidance." in result.output for result in results)
    assert all(any("DISTINCT_SKILL_BODY" in str(m.content) for m in chat.history()) for chat in chats)


def test_async_progressive_skills():
    import asyncio
    result = asyncio.run(make_agent(SkillModel()).arun("Assess evidence"))
    assert "Applied evidence guidance." in result.output


def test_skill_loading_does_not_bypass_denial():
    agent = make_agent(SkillModel(), permissions=PermissionEngine(deny=["load_skill"]), max_iterations=2)
    result = agent.run("Assess evidence")
    assert any(e.type == "tool_denied" for e in result.events)
    assert all("DISTINCT_SKILL_BODY" not in str(r.output) for r in result.tool_results)


@pytest.mark.parametrize("async_run", [False, True])
@pytest.mark.parametrize("iteration_limit", [1, 4])
def test_budget_stops_next_step_and_preserves_results(async_run, iteration_limit):
    import asyncio

    class Model:
        calls = 0
        def complete(self, **kwargs):
            self.calls += 1
            return LLMResponse(tool_calls=[ToolCall(name="lookup", arguments={})],
                               usage={"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110})

    model = Model()
    agent = make_agent(model, max_task_tokens=100, max_iterations=iteration_limit,
                       tools=[FunctionTool.from_callable(lambda: "verified fixture", name="lookup")])
    result = asyncio.run(agent.arun("lookup")) if async_run else agent.run("lookup")
    assert model.calls == 1
    assert result.metadata["run_summary"]["incomplete_reason"] == "task_token_budget"
    assert result.tool_results[0].output == "verified fixture"
    diagnostics = result.metadata["run_summary"]["usage_diagnostics"]
    assert diagnostics["reported_tokens_by_purpose"]["main"] == 110
    assert diagnostics["estimated_main_request_content_tokens"]["schemas"] > 0


@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
def test_invalid_task_budget(limit):
    with pytest.raises(ValueError, match="max_task_tokens"):
        make_agent(SkillModel(), max_task_tokens=limit)


def test_cache_diagnostics_detect_prefix_change_not_history_growth():
    class Model:
        def complete(self, **kwargs):
            return LLMResponse(content="ok", usage={"prompt_tokens": 100, "completion_tokens": 1,
                "total_tokens": 101, "cache_read_input_tokens": 40}, metadata={"prompt_tokens_include_cache": True})

    agent = make_agent(Model())
    first = agent.run("hello").metadata["run_summary"]
    second = agent.run("hello again").metadata["run_summary"]
    assert first["usage_diagnostics"]["prefix_changes"] == 0
    assert second["usage_diagnostics"]["prefix_changes"] == 0
    assert second["cache"]["hit_ratio"] == 0.4
    agent.prompt += "\nChanged instruction."
    third = agent.run("hello").metadata["run_summary"]
    assert third["usage_diagnostics"]["prefix_changes"] == 1


def test_large_tool_result_retains_canonical_evidence_but_bounds_model_view(tmp_path):
    payload = "verified-evidence " * 30000

    class Model:
        calls = 0
        def complete(self, *, messages, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return LLMResponse(tool_calls=[ToolCall(name="lookup", arguments={})])
            result = next(m for m in messages if m.role == "tool")
            assert len(result.content) < 5000
            return LLMResponse(content="Received limited evidence view.")

    agent = make_agent(Model(), project_root=tmp_path, max_tool_output_chars=1500,
                       tools=[FunctionTool.from_callable(lambda: payload, name="lookup")])
    result = agent.run("lookup")
    assert result.tool_results[0].output == payload


@pytest.mark.parametrize("usage", [{}, {"cache_read_input_tokens": 10},
                                   {"prompt_tokens": 10}, {"completion_tokens": 2},
                                   {"total_tokens": 12}])
@pytest.mark.parametrize("async_run", [False, True])
def test_budget_does_not_silently_continue_without_usage(usage, async_run):
    import asyncio
    class Model:
        calls = 0
        def complete(self, **kwargs):
            self.calls += 1
            return LLMResponse(tool_calls=[ToolCall(name="lookup", arguments={})], usage=usage)

    model = Model()
    agent = make_agent(model, max_task_tokens=100,
                       tools=[FunctionTool.from_callable(lambda: "fixture", name="lookup")])
    result = asyncio.run(agent.arun("lookup")) if async_run else agent.run("lookup")
    assert model.calls == 1
    assert result.metadata["run_summary"]["incomplete_reason"] == "task_budget_usage_unavailable"
