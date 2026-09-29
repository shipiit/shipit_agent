from __future__ import annotations

import asyncio
import json
import pytest

from shipit_agent import Agent
from shipit_agent.deferral import DiscoveryPolicy
from shipit_agent.deferral.policy import schema_tokens, select_resident
from shipit_agent.permissions import PermissionEngine
from shipit_agent.runtime import AgentRuntime
from shipit_agent.async_runtime import AsyncAgentRuntime
from shipit_agent.tools.base import ToolOutput
from test_deferred_tools import FakeTool, ScriptedLLM


@pytest.mark.parametrize("runtime_cls", [AgentRuntime, AsyncAgentRuntime])
def test_small_catalog_large_schemas_are_deferred(runtime_cls):
    tools = [FakeTool("large", "expensive " * 3000), FakeTool("small", "Small tool")]
    llm = ScriptedLLM([("done", [])])
    runtime = runtime_cls(llm=llm, prompt="Help", tools=tools,
                          deferred_tools=DiscoveryPolicy(schema_tokens=500))
    if runtime_cls is AsyncAgentRuntime:
        asyncio.run(runtime.run("hello"))
    else:
        runtime.run("hello")
    assert "large" not in llm.seen_tools[0]
    assert "search_tools" in llm.seen_tools[0]
    assert "small" in llm.seen_tools[0]


def test_reuse_is_bounded_and_invalidated_by_schema_and_permission_changes():
    tools = [FakeTool(f"capability_{i}", f"Capability {i}") for i in range(20)]
    llm = ScriptedLLM([
        ("", [("search_tools", {"query": "capability_19"})]), ("done", []),
        ("done", []), ("done", []), ("done", []),
    ])
    agent = Agent(llm=llm, tools=tools, auto_use_skills=False, auto_project_memory=False)
    agent.run("find a tool")
    agent.run("continue")
    assert "capability_19" in llm.seen_tools[2]
    assert len(llm.seen_tools[2]) == 10
    tools[-1].description = "Changed contract"
    agent.run("continue")
    assert "capability_19" not in llm.seen_tools[3]
    agent.permissions = PermissionEngine(deny=["capability_19"])
    agent.run("continue")
    assert "capability_19" not in llm.seen_tools[4]


def test_chat_session_preserves_state_without_cross_session_leaks():
    agent = Agent(llm=ScriptedLLM([]), tools=[])
    first = agent.chat_session(session_id="one")
    second = agent.chat_session(session_id="two")
    first._session_agent()._session_runtime_state["sentinel"] = 1
    assert first._session_agent()._session_runtime_state["sentinel"] == 1
    assert "sentinel" not in second._session_agent()._session_runtime_state
    assert "sentinel" not in agent._session_runtime_state


@pytest.mark.parametrize("runtime_cls", [AgentRuntime, AsyncAgentRuntime])
def test_discovery_survives_runtime_recreation_and_revalidates(runtime_cls):
    from shipit_agent.stores import InMemorySessionStore
    store = InMemorySessionStore()
    tools = [FakeTool(f"tool_{i}", "Lookup records") for i in range(20)]

    def run(llm, **extra):
        runtime = runtime_cls(llm=llm, prompt="help", tools=tools, session_id="tenant-a/chat-1",
                              session_store=store, **extra)
        if runtime_cls is AsyncAgentRuntime:
            asyncio.run(runtime.run("continue"))
        else:
            runtime.run("continue")

    run(ScriptedLLM([("", [("search_tools", {"query": "tool_19"})]), ("done", [])]))
    checkpoint = store.load("tenant-a/chat-1").metadata["tool_discovery"]
    assert set(checkpoint["schemas"]) == {"tool_19"}
    llm = ScriptedLLM([("done", [])])
    run(llm)
    assert "tool_19" in llm.seen_tools[0]
    llm = ScriptedLLM([("done", [])])
    run(llm, permissions=PermissionEngine(deny=["tool_19"]))
    assert "tool_19" not in llm.seen_tools[0]


def test_checkpoint_from_another_session_is_not_reused():
    from shipit_agent.deferral.policy import schema_fingerprint
    tools = [FakeTool(f"tool_{i}", "Lookup records") for i in range(20)]
    checkpoint = {"version": 1, "session_id": "other-session",
                  "schemas": {"tool_19": schema_fingerprint(tools[-1].schema())}}
    llm = ScriptedLLM([("done", [])])
    Agent(llm=llm, tools=tools, session_id="this-session", metadata={"tool_discovery": checkpoint},
          auto_use_skills=False).run("hello")
    assert "tool_19" not in llm.seen_tools[0]


def test_schema_count_uses_model_tokenizer_when_available(monkeypatch):
    monkeypatch.setattr("shipit_agent.token_counting.count_tokens", lambda text, model: 789)
    assert schema_tokens({"x": "y"}, "fixture-model") == 789


def test_permission_discovery_never_calls_argument_callback():
    def callback(*args):
        raise AssertionError("Discovery must not call permission callbacks")
    engine = PermissionEngine(deny=["secret_*"], callback=callback)
    assert not engine.discoverable("secret_lookup")
    assert engine.discoverable("conditional_lookup")


def test_resident_schema_budget_includes_discovery():
    from shipit_agent.tools.tool_search import ToolSearchTool
    tools = [FakeTool(f"tool_{i}", "description " * 50) for i in range(20)]
    search = ToolSearchTool()
    schemas = {t.name: t.schema() for t in [*tools, search]}
    policy = DiscoveryPolicy(schema_tokens=700)
    names = select_resident(tools, schemas, policy, core=frozenset(), search_name=search.name)
    assert search.name in names
    assert sum(schema_tokens(schemas[name]) for name in names) <= 700
    assert len(names) < 10


def test_denied_name_collision_does_not_replace_user_tool():
    tools = [FakeTool(f"tool_{i}", "description") for i in range(20)]
    tools.append(FakeTool("search_tools", "Private user implementation"))
    llm = ScriptedLLM([("done", [])])
    Agent(llm=llm, tools=tools, auto_use_skills=False,
          permissions=PermissionEngine(deny=["search_tools"])).run("hello")
    assert "search_tools" not in llm.seen_tools[0]
    assert "_search_tools" in llm.seen_tools[0]


def test_projection_retains_original_and_advertises_pagination():
    rows = [{"id": i, "evidence": "exact quote", "body": "x" * 1000} for i in range(30)]
    output = ToolOutput.from_records(rows, fields=["id", "evidence"], limit=2, source="fixture")
    assert json.loads(output.text) == rows
    view = json.loads(output.model_text)
    assert view["next_offset"] == 2
    assert view["total_records"] == 30
    assert view["records"] == [{"id": i, "evidence": "exact quote"} for i in range(2)]
    assert len(output.model_text) < len(output.text) / 10


@pytest.mark.parametrize("kwargs", [{"initial_tools": 1}, {"schema_tokens": 0}, {"reuse_tools": -1}])
def test_policy_rejects_invalid_budgets(kwargs):
    with pytest.raises(ValueError):
        DiscoveryPolicy(**kwargs)
