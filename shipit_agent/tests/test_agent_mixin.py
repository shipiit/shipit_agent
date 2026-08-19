"""The mixin adds capability to an existing Agent without replacing anything."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from shipit_agent.agent_mixin import UpgradeMixin
from shipit_agent.models import ToolCall
from shipit_agent.tests.test_bridge import FakeRule, FakeSkill, LegacyAgent
from shipit_agent.tests.test_graph import EchoTool, Reply, ScriptedLLM
from shipit_agent.tests.test_mcp_and_skills import FakeMCPServer, FakeMCPTool


@dataclass
class UpgradedAgent(UpgradeMixin, LegacyAgent):
    """What the real Agent becomes: one extra base class, nothing removed."""

    # Existing methods, kept verbatim to prove they survive the mixin.
    def run(self, user_prompt: str, **kwargs: Any) -> str:
        return f"legacy:{user_prompt}"

    def clone(self, **changes: Any) -> "UpgradedAgent":
        return UpgradedAgent(**{**self.__dict__, **changes})


def agent(**fields: Any) -> UpgradedAgent:
    fields.setdefault("llm", ScriptedLLM(Reply(content="ok")))
    fields.setdefault("model", "google.gemma-4-31b")
    return UpgradedAgent(**fields)


# --------------------------------------------------------------------------- #
# Nothing is taken away
# --------------------------------------------------------------------------- #


def test_the_existing_methods_still_work():
    assert agent().run("hello") == "legacy:hello"


def test_the_existing_fields_are_untouched():
    a = agent(prompt="custom", max_iterations=7)
    assert a.prompt == "custom"
    assert a.max_iterations == 7


def test_the_mixin_overrides_nothing():
    """Every new name ends in _v2 or is new, so no existing method is shadowed."""
    added = {n for n in dir(UpgradeMixin) if not n.startswith("__")}
    legacy = {n for n in dir(LegacyAgent) if not n.startswith("__")}
    assert not (added & legacy)


def test_clone_still_returns_an_upgraded_agent():
    assert isinstance(agent().clone(max_iterations=3), UpgradedAgent)


# --------------------------------------------------------------------------- #
# The new loop, driven by the existing fields
# --------------------------------------------------------------------------- #


def test_run_v2_uses_the_same_configuration():
    result = agent(prompt="be careful").run_v2("go")
    assert result.output == "ok"
    assert result.metadata["pairing_ok"] is True


def test_run_v2_and_stream_v2_are_one_execution():
    a = agent()
    events = list(a.stream_v2("go"))
    assert a._last_result_v2.output == "ok"
    assert events[-1].type == "run_completed"


def test_tools_run_through_the_new_loop():
    tool = EchoTool()
    llm = ScriptedLLM(
        Reply(tool_calls=[ToolCall(name="echo", arguments={"text": "hi"})]),
        Reply(content="done"),
    )
    result = agent(llm=llm, tools=[tool]).run_v2("go")
    assert tool.seen == [{"text": "hi"}]
    assert result.output == "done"


def test_tool_output_streams_live_with_its_call_id():
    llm = ScriptedLLM(
        Reply(tool_calls=[ToolCall(name="echo", arguments={"text": "x"})]),
        Reply(content="done"),
    )
    deltas = [
        e
        for e in agent(llm=llm, tools=[EchoTool(streaming=True)]).stream_v2("go")
        if e.type == "tool_output_delta"
    ]
    assert [d.payload["chunk"] for d in deltas] == ["x-0", "x-1", "x-2"]
    assert all(d.payload["tool_call_id"] for d in deltas)


def test_packets_v2_terminate_last():
    packets = list(agent().packets_v2("go"))
    assert packets[-1].is_terminal


def test_two_runs_do_not_leak_into_each_other():
    a = agent(llm=ScriptedLLM(Reply(content="first"), Reply(content="second")))
    assert a.run_v2("a").output == "first"
    second = a.run_v2("b")
    assert second.output == "second"
    assert len(second.messages) == 2


def test_history_is_carried_when_the_agent_has_it():
    from shipit_agent.models import Message

    a = agent(history=[Message(role="user", content="earlier")])
    assert [m.text for m in a.run_v2("now").messages][:2] == ["earlier", "now"]


def test_skills_reach_the_catalog_and_trigger_phrases_still_prime():
    skill = FakeSkill("rev", "Rev", "review code", body="BODY", trigger_phrases=["code review"])
    a = agent(skill_registry=[skill])
    result = a.run_v2("please do a code review")
    assert "rev" in result.metadata["primed_skills"]


def test_rules_are_scoped_to_the_tools_actually_present():
    a = agent(tools=[EchoTool()], rules=[FakeRule("never rm -rf", tools=("bash",))])
    assert "rm -rf" not in a.preflight()["parameters"] + str(a.describe_tools_v2())


def test_mcp_servers_attach_through_the_mixin():
    a = agent(mcps=[FakeMCPServer("jira", [FakeMCPTool("search", "Find issues")])])
    assert "search__mcp__jira" in {row["name"] for row in a.describe_tools_v2()}


# --------------------------------------------------------------------------- #
# Preflight
# --------------------------------------------------------------------------- #


def test_preflight_reports_the_model_and_prefix_size():
    report = agent().preflight()
    assert report["model"] == "google.gemma-4-31b"
    assert report["schema_dialect"] == "openai_strict"
    assert report["context_window"] == 256_000
    assert report["prefix_tokens"] > 0


def test_preflight_names_a_dead_connector_before_any_call():
    a = agent(mcps=[FakeMCPServer("jira", [], fail=True)])
    report = a.preflight()
    assert report["mcp"]["failed"]["jira"]
    assert any("jira" in w for w in report["warnings"])


def test_preflight_flags_a_parameter_this_model_rejects():
    report = agent(model_parameters={"top_k": 40}).preflight()
    assert any("Blocked for this model" in w for w in report["warnings"])
    assert "top_k" in report["parameters"]


def test_preflight_flags_a_prompt_that_eats_the_budget():
    report = agent(model="google.gemma-4-e2b", prompt="rule. " * 60_000).preflight()
    assert any("input budget" in w for w in report["warnings"])


def test_preflight_warns_when_no_context_window_is_known():
    assert any("No context window" in w for w in agent(model="mystery-model-9").preflight()["warnings"])


def test_preflight_costs_no_model_call():
    llm = ScriptedLLM(Reply(content="never"))
    agent(llm=llm).preflight()
    assert llm.calls == []


# --------------------------------------------------------------------------- #
# Honest about what is missing
# --------------------------------------------------------------------------- #


def test_an_unconfigured_feature_is_not_reported_as_missing():
    assert agent().upgrade_report() == {}


def test_a_configured_feature_the_loop_lacks_is_named_with_a_reason():
    gaps = agent(code_mode=True, rag=object()).upgrade_report()
    assert set(gaps) == {"code_mode", "rag"}
    assert all(gaps.values())


def test_preflight_surfaces_the_gaps_too():
    assert "code_mode" in agent(code_mode=True).preflight()["not_yet_in_v2"]


def test_the_usage_ledger_is_available_after_a_run():
    a = agent(llm=ScriptedLLM(Reply(content="ok", usage={"input_tokens": 50, "output_tokens": 5})))
    a.run_v2("go")
    assert a.last_ledger_v2 is not None
    assert a.last_ledger_v2.totals()["calls"] == 1
