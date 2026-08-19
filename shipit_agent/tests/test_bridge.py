"""Driving the new loop from the existing Agent, without changing its surface."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from shipit_agent.bridge import MAPPING, NOT_YET_MAPPED, spec_from_agent, unmapped
from shipit_agent.graph import AgentGraph
from shipit_agent.tests.test_graph import EchoTool, Reply, ScriptedLLM
from shipit_agent.tests.test_mcp_and_skills import FakeMCPServer, FakeMCPTool


@dataclass
class FakeSkill:
    id: str
    name: str
    description: str
    body: str = "GUIDANCE"
    tools: list[str] = field(default_factory=list)
    trigger_phrases: list[str] = field(default_factory=list)

    def prompt_text(self) -> str:
        return self.body


class FakeRule:
    def __init__(self, text: str, tools: tuple[str, ...] = ()) -> None:
        self.text = text
        self.tools = tools
        self.priority = 0
        self.id = ""
        self.source = "agent"

    def applies(self, *, tools=frozenset(), paths=()) -> bool:
        return not self.tools or bool(set(self.tools) & set(tools))


@dataclass
class LegacyAgent:
    """Stands in for the real Agent: the fields the bridge reads, same names."""

    llm: Any = None
    model: str = "google.gemma-4-31b"
    prompt: str = "You are careful."
    tools: list[Any] = field(default_factory=list)
    mcps: list[Any] = field(default_factory=list)
    history: list[Any] = field(default_factory=list)
    rules: list[Any] = field(default_factory=list)
    skills: list[Any] = field(default_factory=list)
    default_skill_ids: list[str] = field(default_factory=list)
    skill_registry: Any = None
    auto_use_skills: bool = True
    skill_match_limit: int = 3
    deferred_tools: Any = False
    max_iterations: int = 12
    max_tool_output_chars: int = 16_000
    permission_callback: Any = None
    model_parameters: dict[str, Any] = field(default_factory=dict)
    # features the new loop does not yet cover
    code_mode: bool = False
    rag: Any = None
    verifier: Any = None
    parallel_tool_execution: bool = False
    decision_llm: Any = None
    observability: Any = "auto"


# --------------------------------------------------------------------------- #
# The surface is not replaced
# --------------------------------------------------------------------------- #


def test_the_bridge_does_not_ship_a_competing_agent():
    """The existing Agent is the product; the loop plugs in underneath it."""
    import shipit_agent

    assert "Agent" not in shipit_agent.__all__
    assert "spec_from_agent" in shipit_agent.__all__


def test_every_field_the_bridge_reads_keeps_its_name():
    agent = LegacyAgent(llm=ScriptedLLM())
    for name in ("llm", "prompt", "tools", "mcps", "rules", "max_iterations"):
        assert hasattr(agent, name)
        assert name in MAPPING


# --------------------------------------------------------------------------- #
# Mapping
# --------------------------------------------------------------------------- #


def test_core_fields_carry_across():
    tool = EchoTool()
    agent = LegacyAgent(llm=ScriptedLLM(), tools=[tool], max_iterations=5)
    spec = spec_from_agent(agent)

    assert spec.llm is agent.llm
    assert spec.model == "google.gemma-4-31b"
    assert spec.system_prompt == "You are careful."
    assert spec.tools == [tool]
    assert spec.max_iterations == 5


def test_skill_bodies_no_longer_ride_in_the_system_prompt():
    """They used to be appended there, which moved the prefix on every run."""
    skill = FakeSkill("s", "S", "does a thing", body="LONG BODY")
    agent = LegacyAgent(llm=ScriptedLLM(), skill_registry=[skill], skills=[skill])
    spec = spec_from_agent(agent, "go")
    assert "LONG BODY" not in spec.system_prompt
    assert skill in spec.always_apply_skills


def test_the_catalog_reaches_the_prefix_but_the_body_does_not():
    skill = FakeSkill("review", "Review", "review code", body="LONG BODY")
    agent = LegacyAgent(llm=ScriptedLLM(), skill_registry=[skill])
    graph = AgentGraph(spec_from_agent(agent, "hello"))
    assert "review" in graph.prefix.system_text
    assert "LONG BODY" not in graph.prefix.system_text


def test_trigger_phrases_still_prime_without_a_model_turn():
    skill = FakeSkill("rev", "Rev", "d", trigger_phrases=["code review"])
    agent = LegacyAgent(llm=ScriptedLLM(), skill_registry=[skill])
    primed = spec_from_agent(agent, "please do a code review").always_apply_skills
    assert [s.id for s in primed] == ["rev"]


def test_a_prompt_that_matches_nothing_primes_nothing():
    skill = FakeSkill("rev", "Rev", "d", trigger_phrases=["code review"])
    agent = LegacyAgent(llm=ScriptedLLM(), skill_registry=[skill])
    assert spec_from_agent(agent, "what is the weather").always_apply_skills == []


def test_the_match_limit_is_respected():
    skills = [FakeSkill(f"s{i}", f"S{i}", "d", trigger_phrases=["go"]) for i in range(6)]
    agent = LegacyAgent(llm=ScriptedLLM(), skill_registry=skills, skill_match_limit=2)
    assert len(spec_from_agent(agent, "go now").always_apply_skills) == 2


def test_explicit_and_default_skills_are_deduplicated():
    skill = FakeSkill("s", "S", "d")
    agent = LegacyAgent(
        llm=ScriptedLLM(), skill_registry=[skill], skills=[skill], default_skill_ids=["s"]
    )
    assert len(spec_from_agent(agent, "").always_apply_skills) == 1


def test_rules_are_rendered_and_scoped_to_active_tools():
    agent = LegacyAgent(
        llm=ScriptedLLM(),
        tools=[EchoTool()],
        rules=[FakeRule("never rm -rf", tools=("bash",)), FakeRule("always test")],
    )
    rules = spec_from_agent(agent).rules
    assert "always test" in rules
    assert "rm -rf" not in rules      # bash is not among this agent's tools


def test_a_tool_can_contribute_its_own_rule():
    class Guarded(EchoTool):
        rules = [FakeRule("echo carefully", tools=("echo",))]

    agent = LegacyAgent(llm=ScriptedLLM(), tools=[Guarded()])
    assert "echo carefully" in spec_from_agent(agent).rules


def test_mcp_servers_attach_lazily_through_the_bridge():
    server = FakeMCPServer("jira", [FakeMCPTool("search", "Find issues")])
    agent = LegacyAgent(llm=ScriptedLLM(), mcps=[server])
    spec = spec_from_agent(agent)

    assert spec.mcp is not None
    assert server.discoveries == 1                     # described
    assert [d.name for d in spec.mcp.descriptors()] == ["search__mcp__jira"]


def test_mcp_server_instructions_reach_the_prompt():
    server = FakeMCPServer(
        "jira", [FakeMCPTool("create", "d")], instructions="Call list_projects first."
    )
    agent = LegacyAgent(llm=ScriptedLLM(), mcps=[server])
    graph = AgentGraph(spec_from_agent(agent))
    assert "list_projects first" in graph.prefix.system_text


def test_permission_callback_becomes_the_approval_gate():
    def deny(call: Any) -> bool:
        return False

    agent = LegacyAgent(llm=ScriptedLLM(), permission_callback=deny)
    assert spec_from_agent(agent).approve is deny


def test_an_agent_with_no_mcps_gets_no_bridge():
    assert spec_from_agent(LegacyAgent(llm=ScriptedLLM())).mcp is None


def test_a_non_iterable_skill_registry_does_not_break_the_bridge():
    agent = LegacyAgent(llm=ScriptedLLM(), skill_registry=object())
    assert spec_from_agent(agent).skills == []


# --------------------------------------------------------------------------- #
# It actually runs
# --------------------------------------------------------------------------- #


def test_a_legacy_agent_config_drives_the_new_loop_end_to_end():
    tool = EchoTool()
    llm = ScriptedLLM(
        Reply(tool_calls=[__import__("shipit_agent.models", fromlist=["ToolCall"]).ToolCall(
            name="echo", arguments={"text": "hi"}
        )]),
        Reply(content="finished"),
    )
    agent = LegacyAgent(llm=llm, tools=[tool], model="google.gemma-4-31b")
    graph = AgentGraph(spec_from_agent(agent, "go"))
    list(graph.run("go"))

    assert tool.seen == [{"text": "hi"}]
    assert graph.result().output == "finished"
    assert graph.result().metadata["pairing_ok"] is True


def test_model_parameters_are_adapted_for_the_family():
    llm = ScriptedLLM(Reply(content="ok"))
    agent = LegacyAgent(
        llm=llm, model_parameters={"temperature": 0.3, "topK": 40, "maxContextTokens": 1000}
    )
    list(AgentGraph(spec_from_agent(agent)).run("hi"))

    sent = llm.calls[0]
    assert sent["temperature"] == 0.3
    assert "top_k" not in sent                 # blocked for Gemma
    assert "max_context_tokens" not in sent    # host-side, never on the wire


# --------------------------------------------------------------------------- #
# Honest about gaps
# --------------------------------------------------------------------------- #


def test_an_unconfigured_feature_is_not_reported_as_missing():
    assert unmapped(LegacyAgent(llm=ScriptedLLM())) == {}


def test_a_configured_feature_the_loop_lacks_is_named():
    gaps = unmapped(LegacyAgent(llm=ScriptedLLM(), code_mode=True, rag=object()))
    assert set(gaps) == {"code_mode", "rag"}
    assert "calls tools" in gaps["code_mode"]


def test_the_default_observability_setting_is_not_a_gap():
    assert "observability" not in unmapped(LegacyAgent(llm=ScriptedLLM()))


def test_every_gap_carries_an_explanation():
    assert all(note for note in NOT_YET_MAPPED.values())


def test_no_field_is_both_mapped_and_missing():
    assert not (set(MAPPING) & set(NOT_YET_MAPPED))
