"""Tests for DeepAgent's `agents=` sub-agent delegation + streaming."""
from __future__ import annotations

import json

import pytest

from shipit_agent import Agent
from shipit_agent.deep import (
    AdaptiveAgent,
    AgentDelegationTool,
    DeepAgent,
    Goal,
    GoalAgent,
    PersistentAgent,
    ReflectiveAgent,
    Supervisor,
    create_deep_agent,
)
from shipit_agent.deep.deep_agent.delegation import build_delegation_tool
from shipit_agent.llms import SimpleEchoLLM
from shipit_agent.models import AgentEvent
from shipit_agent.tools.base import ToolContext


# ---------------------------------------------------------------------------
# build_delegation_tool helper
# ---------------------------------------------------------------------------


def test_build_delegation_tool_returns_none_when_empty():
    assert build_delegation_tool(None) is None
    assert build_delegation_tool([]) is None
    assert build_delegation_tool({}) is None


def test_build_delegation_tool_from_dict_keeps_keys():
    a = Agent(llm=SimpleEchoLLM(), name="alpha")
    b = Agent(llm=SimpleEchoLLM(), name="beta")
    tool = build_delegation_tool({"alpha": a, "beta": b})
    assert isinstance(tool, AgentDelegationTool)
    assert set(tool.agents.keys()) == {"alpha", "beta"}


def test_build_delegation_tool_from_list_uses_agent_names():
    a = Agent(llm=SimpleEchoLLM(), name="researcher")
    b = Agent(llm=SimpleEchoLLM(), name="writer")
    tool = build_delegation_tool([a, b])
    assert set(tool.agents.keys()) == {"researcher", "writer"}


def test_build_delegation_tool_dedupes_collisions():
    a = Agent(llm=SimpleEchoLLM(), name="worker")
    b = Agent(llm=SimpleEchoLLM(), name="worker")
    tool = build_delegation_tool([a, b])
    assert set(tool.agents.keys()) == {"worker", "worker_2"}


def test_build_delegation_tool_rejects_unsupported_types():
    with pytest.raises(TypeError):
        build_delegation_tool("not a list")  # type: ignore[arg-type]


def test_delegation_tool_requires_run_method():
    class NotAnAgent:
        name = "x"

    with pytest.raises(TypeError):
        AgentDelegationTool(agents={"x": NotAnAgent()})


# ---------------------------------------------------------------------------
# Schema + invocation
# ---------------------------------------------------------------------------


def _ctx() -> ToolContext:
    return ToolContext(prompt="", metadata={}, state={})


def _make_dummy_agents() -> dict[str, Agent]:
    return {
        "alpha": Agent(llm=SimpleEchoLLM(), name="alpha", description="Alpha agent."),
        "beta": Agent(llm=SimpleEchoLLM(), name="beta", description="Beta agent."),
    }


def test_delegation_tool_schema_includes_agent_names():
    tool = AgentDelegationTool(agents=_make_dummy_agents())
    schema = tool.schema()
    fn = schema["function"]
    assert fn["name"] == "delegate_to_agent"
    assert "alpha" in fn["description"]
    assert "beta" in fn["description"]
    assert fn["parameters"]["properties"]["agent_name"]["enum"] == ["alpha", "beta"]


def test_delegation_tool_run_requires_agent_name():
    tool = AgentDelegationTool(agents=_make_dummy_agents())
    out = tool.run(_ctx(), task="hello")
    assert "error" in json.loads(out.text)


def test_delegation_tool_run_requires_task():
    tool = AgentDelegationTool(agents=_make_dummy_agents())
    out = tool.run(_ctx(), agent_name="alpha")
    assert "error" in json.loads(out.text)


def test_delegation_tool_unknown_agent_returns_error_with_available_list():
    tool = AgentDelegationTool(agents=_make_dummy_agents())
    out = tool.run(_ctx(), agent_name="gamma", task="hi")
    payload = json.loads(out.text)
    assert "unknown sub-agent" in payload["error"]
    assert "alpha" in payload["available"]


def test_delegation_tool_run_returns_payload_with_output():
    tool = AgentDelegationTool(agents=_make_dummy_agents())
    out = tool.run(_ctx(), agent_name="alpha", task="say hi")
    payload = json.loads(out.text)
    assert payload["agent"] == "alpha"
    assert payload["task"] == "say hi"
    assert "output" in payload
    assert "events" in out.metadata  # captured by streaming


def test_delegation_tool_capture_events_off_skips_event_collection():
    tool = AgentDelegationTool(agents=_make_dummy_agents(), capture_events=False)
    out = tool.run(_ctx(), agent_name="alpha", task="say hi")
    assert "events" not in out.metadata or not out.metadata["events"]


def test_delegation_tool_supports_deep_agent_subagent():
    inner_deep = DeepAgent(llm=SimpleEchoLLM(), name="researcher")
    tool = AgentDelegationTool(agents={"researcher": inner_deep})
    out = tool.run(_ctx(), agent_name="researcher", task="research python")
    payload = json.loads(out.text)
    assert payload["agent"] == "researcher"


def test_delegation_tool_supports_reflective_subagent():
    inner = ReflectiveAgent(llm=SimpleEchoLLM())
    tool = AgentDelegationTool(agents={"critic": inner})
    out = tool.run(_ctx(), agent_name="critic", task="review this")
    payload = json.loads(out.text)
    assert payload["agent"] == "critic"


def test_delegation_tool_add_runtime_agent():
    tool = AgentDelegationTool(agents=_make_dummy_agents())
    tool.add("gamma", Agent(llm=SimpleEchoLLM(), name="gamma"))
    assert "gamma" in tool.names()


# ---------------------------------------------------------------------------
# DeepAgent integration
# ---------------------------------------------------------------------------


def test_deep_agent_with_agents_list_wires_delegation_tool():
    researcher = Agent(llm=SimpleEchoLLM(), name="researcher")
    writer = Agent(llm=SimpleEchoLLM(), name="writer")
    agent = DeepAgent(llm=SimpleEchoLLM(), agents=[researcher, writer])

    delegate = agent.delegation_tool
    assert delegate is not None
    assert set(delegate.agents.keys()) == {"researcher", "writer"}


def test_deep_agent_with_agents_dict_wires_delegation_tool():
    agent = DeepAgent(
        llm=SimpleEchoLLM(),
        agents={
            "alpha": Agent(llm=SimpleEchoLLM(), name="anything"),
            "beta": Agent(llm=SimpleEchoLLM(), name="something"),
        },
    )
    assert set(agent.sub_agents.keys()) == {"alpha", "beta"}


def test_deep_agent_without_agents_has_no_delegation_tool():
    agent = DeepAgent(llm=SimpleEchoLLM())
    assert agent.delegation_tool is None
    assert agent.sub_agents == {}


def test_deep_agent_add_sub_agent_runtime():
    agent = DeepAgent(llm=SimpleEchoLLM())
    new_sub = Agent(llm=SimpleEchoLLM(), name="late")
    agent.add_sub_agent("late", new_sub)
    assert "late" in agent.sub_agents


def test_deep_agent_add_sub_agent_appends_to_existing_tool():
    agent = DeepAgent(
        llm=SimpleEchoLLM(),
        agents=[Agent(llm=SimpleEchoLLM(), name="first")],
    )
    agent.add_sub_agent("second", Agent(llm=SimpleEchoLLM(), name="second"))
    assert set(agent.sub_agents.keys()) == {"first", "second"}


def test_create_deep_agent_accepts_agents_list():
    a = Agent(llm=SimpleEchoLLM(), name="research")
    b = ReflectiveAgent(llm=SimpleEchoLLM())
    deep = create_deep_agent(
        llm=SimpleEchoLLM(),
        agents=[a, b],
        use_builtins=False,
    )
    assert deep.delegation_tool is not None
    assert "research" in deep.sub_agents


def test_deep_agent_supports_chained_deep_agent_as_subagent():
    inner = DeepAgent(llm=SimpleEchoLLM(), name="inner-deep")
    outer = DeepAgent(llm=SimpleEchoLLM(), agents={"inner": inner})
    assert "inner" in outer.sub_agents
    delegate = outer.delegation_tool
    out = delegate.run(_ctx(), agent_name="inner", task="deep task")
    payload = json.loads(out.text)
    assert payload["agent"] == "inner"


# ---------------------------------------------------------------------------
# Streaming tests — verify every agent type streams
# ---------------------------------------------------------------------------


def _drain(stream) -> list[AgentEvent]:
    return list(stream)


def test_agent_stream_yields_run_completed():
    agent = Agent(llm=SimpleEchoLLM())
    events = _drain(agent.stream("hi"))
    assert any(e.type == "run_completed" for e in events)


def test_deep_agent_stream_default_mode():
    agent = DeepAgent(llm=SimpleEchoLLM())
    events = _drain(agent.stream("hi"))
    assert any(e.type == "run_completed" for e in events)


def test_deep_agent_stream_verify_mode_emits_extra_run_completed():
    agent = DeepAgent(llm=SimpleEchoLLM(), verify=True, max_iterations=1)
    events = _drain(agent.stream("hi"))
    completed = [e for e in events if e.type == "run_completed"]
    # Default run_completed + verification_completed
    assert len(completed) >= 2


def test_deep_agent_stream_goal_mode_delegates_to_goal_agent():
    goal = Goal(objective="say hi", success_criteria=["greeting"], max_steps=1)
    agent = DeepAgent(llm=SimpleEchoLLM(), goal=goal)
    events = _drain(agent.stream("anything"))
    assert any(e.type == "run_completed" for e in events)


def test_deep_agent_stream_reflect_mode_yields_events():
    agent = DeepAgent(
        llm=SimpleEchoLLM(),
        reflect=True,
        reflect_max_iterations=1,
        reflect_threshold=0.0,
    )
    events = _drain(agent.stream("write a haiku"))
    # ReflectiveAgent.stream yields its own run_completed
    assert any(e.type == "run_completed" for e in events)


def test_goal_agent_stream():
    ga = GoalAgent(
        llm=SimpleEchoLLM(),
        goal=Goal(objective="x", success_criteria=["y"], max_steps=1),
    )
    events = _drain(ga.stream())
    assert any(e.type == "run_completed" for e in events)


def test_reflective_agent_stream():
    ra = ReflectiveAgent(llm=SimpleEchoLLM(), max_reflections=1, quality_threshold=0.0)
    events = _drain(ra.stream("hi"))
    assert any(e.type == "run_completed" for e in events)


def test_adaptive_agent_stream():
    aa = AdaptiveAgent(llm=SimpleEchoLLM())
    events = _drain(aa.stream("hi"))
    assert events  # produces at least one event


def test_supervisor_stream():
    sup = Supervisor.with_builtins(
        llm=SimpleEchoLLM(),
        worker_configs=[{"name": "worker", "prompt": "do it"}],
        max_delegations=1,
    )
    events = _drain(sup.stream("test task"))
    assert events


def test_persistent_agent_stream():
    pa = PersistentAgent(llm=SimpleEchoLLM(), max_steps=1, checkpoint_interval=1)
    events = _drain(pa.stream("hi", agent_id="t-1"))
    assert any(e.type == "run_completed" for e in events)


def test_create_deep_agent_returns_streamable_object():
    deep = create_deep_agent(llm=SimpleEchoLLM())
    events = _drain(deep.stream("hi"))
    assert any(e.type == "run_completed" for e in events)
