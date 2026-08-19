"""Prefix stability, skills, usage accounting, checkpoints, streaming, config."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from shipit_agent.checkpoint import (
    FileCheckpointStore,
    InMemoryCheckpointStore,
    PendingApproval,
    RunCheckpoint,
)
from shipit_agent.config import DEFAULTS, deep_merge, load_config
from shipit_agent.live import Packet, PacketAccumulator, PacketKind, to_packets
from shipit_agent.llms.throttle import ThrottleKind
from shipit_agent.prefix import (
    SkillCatalogEntry,
    build_prefix,
    sort_tool_definitions,
)
from shipit_agent.skills.catalog import (
    LoadSkillTool,
    SkillCaps,
    SkillSession,
    build_catalog,
)
from shipit_agent.usage import (
    DEFAULT_TIER_POLICY,
    Purpose,
    ServiceTier,
    UsageEvent,
    UsageLedger,
    split_usage,
)


@dataclass
class FakeSkill:
    id: str
    name: str
    description: str
    body: str = "detailed guidance"
    tools: list[str] = field(default_factory=list)

    def prompt_text(self) -> str:
        return self.body


@dataclass
class FakeEvent:
    type: str
    message: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


def tool(name: str) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {"name": name, "description": "", "parameters": {"type": "object"}},
    }


# --------------------------------------------------------------------------- #
# Prefix stability — the test that should fail before the fix
# --------------------------------------------------------------------------- #


def test_tool_order_does_not_change_the_prefix():
    a = build_prefix(system_prompt="You are helpful.", tool_definitions=[tool("b"), tool("a")])
    b = build_prefix(system_prompt="You are helpful.", tool_definitions=[tool("a"), tool("b")])
    assert a.fingerprint() == b.fingerprint()


def test_mcp_instruction_order_does_not_change_the_prefix():
    a = build_prefix(system_prompt="S", mcp_instructions={"jira": "x", "slack": "y"})
    b = build_prefix(system_prompt="S", mcp_instructions={"slack": "y", "jira": "x"})
    assert a.fingerprint() == b.fingerprint()


def test_prefix_is_stable_across_iterations_of_one_run():
    prefix = build_prefix(
        system_prompt="S",
        rules="Be careful.",
        tool_definitions=[tool("z"), tool("a")],
        skill_catalog=[SkillCatalogEntry("s1", "One", "does a thing")],
    )
    assert len({prefix.fingerprint() for _ in range(5)}) == 1


def test_a_changed_tool_set_does_change_the_prefix():
    one = build_prefix(system_prompt="S", tool_definitions=[tool("a")])
    two = build_prefix(system_prompt="S", tool_definitions=[tool("a"), tool("b")])
    assert one.fingerprint() != two.fingerprint()


def test_catalog_is_capped_and_summaries_are_truncated():
    entries = [SkillCatalogEntry(f"s{i}", f"Skill {i}", "x" * 500) for i in range(50)]
    prefix = build_prefix(
        system_prompt="S",
        skill_catalog=entries,
        max_catalog_entries=10,
        max_description_chars=40,
    )
    listing = prefix.sections["skill_catalog"]
    entry_lines = [ln for ln in listing.splitlines() if ln.startswith("- s")]
    assert len(entry_lines) == 10
    assert all(len(ln) <= 80 for ln in entry_lines)


def test_sections_appear_in_the_documented_order():
    prefix = build_prefix(
        system_prompt="BASE",
        rules="RULES",
        mcp_instructions={"srv": "MCPTEXT"},
        skill_catalog=[SkillCatalogEntry("s", "S", "d")],
    )
    text = prefix.system_text
    assert text.index("BASE") < text.index("RULES") < text.index("MCPTEXT") < text.index("- s")


def test_sort_tool_definitions_handles_bare_schemas():
    assert [d["name"] for d in sort_tool_definitions([{"name": "b"}, {"name": "a"}])] == ["a", "b"]


# --------------------------------------------------------------------------- #
# Skills
# --------------------------------------------------------------------------- #


def test_catalog_costs_a_line_per_skill_not_a_body():
    skills = [FakeSkill(f"s{i}", f"Skill {i}", "summary", body="X" * 5000) for i in range(20)]
    prefix = build_prefix(system_prompt="S", skill_catalog=build_catalog(skills))
    assert "X" * 100 not in prefix.system_text
    assert prefix.system_text.count("- s") == 20


def test_priming_widens_the_tool_set_for_the_rest_of_the_run():
    session = SkillSession(base_tools=frozenset({"bash"}))
    skill = FakeSkill("docx", "Docs", "d", tools=["document_builder"])
    session.prime(skill, available_tools={"bash", "document_builder"})
    assert session.allowed_tools == {"bash", "document_builder"}


def test_unavailable_tools_are_dropped_not_fatal():
    session = SkillSession(base_tools=frozenset({"bash"}))
    skill = FakeSkill("x", "X", "d", tools=["bash", "not_installed"])
    primed = session.prime(skill, available_tools={"bash"})
    assert primed is not None
    assert primed.tools == ("bash",)
    assert "not_installed" in session.unmet_tools


def test_priming_is_idempotent():
    session = SkillSession()
    skill = FakeSkill("a", "A", "d")
    assert session.prime(skill) is not None
    assert session.prime(skill) is None
    assert len(session.primed) == 1


def test_per_turn_cap_is_enforced():
    session = SkillSession(caps=SkillCaps(primed_per_turn=2))
    for i in range(3):
        session.prime(FakeSkill(f"s{i}", f"S{i}", "d"))
    assert len(session.primed) == 2


def test_oversized_skill_body_is_truncated_visibly():
    session = SkillSession(caps=SkillCaps(body_chars=50))
    primed = session.prime(FakeSkill("a", "A", "d", body="Y" * 500))
    assert primed is not None and "truncated" in primed.body


def test_load_skill_tool_returns_the_body_as_a_result():
    registry = {"docx": FakeSkill("docx", "Docs", "d", body="STEP ONE", tools=["document_builder"])}
    session = SkillSession(base_tools=frozenset({"bash"}))
    loader = LoadSkillTool(registry, session, available_tools={"bash", "document_builder"})

    output = loader.run(skill_id="docx")
    assert "STEP ONE" in output.text
    assert "document_builder" in output.text
    assert output.metadata["unlocked_tools"] == ["document_builder"]
    assert session.is_primed("docx")


def test_load_skill_can_be_called_at_any_iteration():
    """The point of the design: selection is not frozen at turn one."""
    registry = {"late": FakeSkill("late", "Late", "d", body="ARRIVED")}
    session = SkillSession()
    loader = LoadSkillTool(registry, session)
    assert not session.primed  # nothing chosen up front
    assert "ARRIVED" in loader.run(skill_id="late").text


def test_unknown_skill_id_suggests_near_matches_instead_of_failing():
    registry = {"contract-review": FakeSkill("contract-review", "CR", "d")}
    loader = LoadSkillTool(registry, SkillSession())
    text = loader.run(skill_id="contract").text
    assert "contract-review" in text


def test_load_skill_schema_is_minimal_and_valid():
    schema = LoadSkillTool({}, SkillSession()).schema()
    assert schema["function"]["name"] == "load_skill"
    assert schema["function"]["parameters"]["required"] == ["skill_id"]


def test_skill_session_round_trips_through_a_checkpoint():
    session = SkillSession(base_tools=frozenset({"bash"}))
    session.prime(FakeSkill("a", "A", "d", tools=["bash"]))
    restored = SkillSession.from_dict(session.to_dict())
    assert restored.is_primed("a")
    assert restored.allowed_tools == session.allowed_tools


# --------------------------------------------------------------------------- #
# Usage and tiers
# --------------------------------------------------------------------------- #


def test_cache_tokens_inside_input_are_not_double_counted():
    usage = {"input_tokens": 1000, "output_tokens": 100, "cache_read_input_tokens": 400}
    assert split_usage(usage, cache_included_in_input=True) == (600, 100, 400, 0)


def test_cache_tokens_added_to_input_are_kept_separate():
    usage = {"input_tokens": 600, "output_tokens": 100, "cache_read_input_tokens": 400}
    assert split_usage(usage, cache_included_in_input=False) == (600, 100, 400, 0)


def test_missing_usage_fields_count_as_zero():
    assert split_usage({}, cache_included_in_input=True) == (0, 0, 0, 0)


def test_every_nested_call_reaches_the_ledger():
    ledger = UsageLedger()
    ledger.sink(Purpose.MAIN, "gemma")({"input_tokens": 100, "output_tokens": 10})
    ledger.sink(Purpose.SUBAGENT, "gemma")({"input_tokens": 50, "output_tokens": 5})
    ledger.sink(Purpose.SUMMARIZER, "haiku")({"input_tokens": 20, "output_tokens": 2})

    totals = ledger.totals()
    assert totals["calls"] == 3
    assert totals["total_tokens"] == 187
    assert set(ledger.by_purpose()) == {"main", "subagent", "summarizer"}


def test_delegating_run_accounts_for_more_than_the_foreground_turn():
    foreground = UsageLedger()
    foreground.sink(Purpose.MAIN, "m")({"input_tokens": 100, "output_tokens": 10})

    delegating = UsageLedger()
    delegating.sink(Purpose.MAIN, "m")({"input_tokens": 100, "output_tokens": 10})
    for _ in range(3):
        delegating.sink(Purpose.SUBAGENT, "m")({"input_tokens": 80, "output_tokens": 8})

    assert delegating.totals()["total_tokens"] > foreground.totals()["total_tokens"]


def test_cost_is_omitted_when_any_call_cannot_be_priced():
    def price(event: UsageEvent) -> float | None:
        return None if event.purpose is Purpose.SUBAGENT else 0.01

    ledger = UsageLedger(price_fn=price)
    ledger.sink(Purpose.MAIN, "m")({"input_tokens": 1})
    ledger.sink(Purpose.SUBAGENT, "m")({"input_tokens": 1})
    assert ledger.cost_usd() is None
    assert "cost_usd" not in ledger.summary()


def test_cost_is_reported_when_coverage_is_complete():
    ledger = UsageLedger(price_fn=lambda event: 0.5)
    ledger.sink(Purpose.MAIN, "m")({"input_tokens": 1})
    ledger.sink(Purpose.SUBAGENT, "m")({"input_tokens": 1})
    assert ledger.cost_usd() == 1.0


def test_foreground_gets_priority_and_background_gets_flex():
    assert DEFAULT_TIER_POLICY.tier_for(Purpose.MAIN) is ServiceTier.PRIORITY
    assert DEFAULT_TIER_POLICY.tier_for(Purpose.SUBAGENT) is ServiceTier.FLEX


def test_tier_param_is_omitted_for_models_that_do_not_understand_it():
    assert DEFAULT_TIER_POLICY.as_request_param(Purpose.MAIN, supported=False) == {}
    assert DEFAULT_TIER_POLICY.as_request_param(Purpose.MAIN, supported=True) == {
        "service_tier": "priority"
    }


# --------------------------------------------------------------------------- #
# Checkpoints
# --------------------------------------------------------------------------- #


def _checkpoint() -> RunCheckpoint:
    session = SkillSession(base_tools=frozenset({"bash"}))
    session.prime(FakeSkill("docx", "Docs", "d", tools=["document_builder"]))
    return RunCheckpoint(
        run_id="run-1",
        iteration=4,
        messages=[{"role": "user", "content": "hi"}],
        skills=session.to_dict(),
        discovered_tools=["jira_search", "jira_create"],
        pending_approval=PendingApproval("call_9", "bash", {"command": "rm -rf build"}),
        prefix_fingerprint="abc123",
    )


def test_resume_restores_primed_skills_and_discovered_tools():
    store = InMemoryCheckpointStore()
    store.save(_checkpoint())
    restored = store.load("run-1")
    assert restored is not None
    assert SkillSession.from_dict(restored.skills).is_primed("docx")
    assert "jira_search" in restored.discovered_tools
    assert restored.pending_approval.tool_name == "bash"


def test_checkpoint_survives_a_json_round_trip(tmp_path):
    store = FileCheckpointStore(tmp_path)
    store.save(_checkpoint())
    restored = store.load("run-1")
    assert restored is not None
    assert restored.iteration == 4
    assert restored.pending_approval.arguments["command"] == "rm -rf build"
    assert store.list_ids() == ["run-1"]


def test_a_corrupt_checkpoint_is_a_miss_not_a_crash(tmp_path):
    store = FileCheckpointStore(tmp_path)
    store.save(_checkpoint())
    (tmp_path / "run-1.json").write_text("{ truncated", encoding="utf-8")
    assert store.load("run-1") is None


def test_missing_checkpoint_loads_as_none(tmp_path):
    assert FileCheckpointStore(tmp_path).load("nope") is None


def test_prefix_drift_is_detected_on_resume():
    checkpoint = _checkpoint()
    assert checkpoint.drift_from("different") is True
    assert checkpoint.drift_from("abc123") is False


def test_delete_removes_the_checkpoint(tmp_path):
    store = FileCheckpointStore(tmp_path)
    store.save(_checkpoint())
    store.delete("run-1")
    assert store.list_ids() == []


# --------------------------------------------------------------------------- #
# Live stream
# --------------------------------------------------------------------------- #


def test_tool_output_streams_as_concatenable_deltas():
    events = [
        FakeEvent("run_started"),
        FakeEvent("tool_called", payload={"tool": "bash", "tool_call_id": "c1"}),
        FakeEvent("tool_output_delta", payload={"chunk": "line 1\n", "tool_call_id": "c1"}),
        FakeEvent("tool_output_delta", payload={"chunk": "line 2\n", "tool_call_id": "c1"}),
        FakeEvent("tool_completed", payload={"tool": "bash", "tool_call_id": "c1"}),
        FakeEvent("text_delta", payload={"chunk": "Done."}),
        FakeEvent("run_completed"),
    ]
    accumulator = PacketAccumulator()
    packets = [accumulator.feed(p) for p in to_packets(events)]

    assert packets[0].kind is PacketKind.RUN_STARTED
    assert accumulator.output_for("c1") == "line 1\nline 2\n"
    assert accumulator.answer == "Done."
    assert packets[-1].is_terminal


def test_parallel_tool_output_stays_separated_by_call_id():
    events = [
        FakeEvent("tool_output_delta", payload={"chunk": "A1", "tool_call_id": "a"}),
        FakeEvent("tool_output_delta", payload={"chunk": "B1", "tool_call_id": "b"}),
        FakeEvent("tool_output_delta", payload={"chunk": "A2", "tool_call_id": "a"}),
        FakeEvent("run_completed"),
    ]
    accumulator = PacketAccumulator()
    for packet in to_packets(events):
        accumulator.feed(packet)
    assert accumulator.output_for("a") == "A1A2"
    assert accumulator.output_for("b") == "B1"


def test_stream_terminates_exactly_once_and_terminally():
    """The terminal packet is last, so a consumer's loop sees everything."""
    events = [
        FakeEvent("final_answer", payload={"text": "x"}),
        FakeEvent("run_summary", payload={"usage": {}}),
        FakeEvent("run_completed"),
    ]
    packets = list(to_packets(events))
    assert sum(1 for p in packets if p.is_terminal) == 1
    assert packets[-1].is_terminal
    assert packets[-1].text == "x"
    assert any(p.kind is PacketKind.USAGE for p in packets)


def test_stream_always_terminates_even_without_a_closing_event():
    assert list(to_packets([FakeEvent("text_delta", payload={"chunk": "x"})]))[-1].is_terminal


def test_unknown_event_types_pass_through_rather_than_vanishing():
    packets = list(to_packets([FakeEvent("some_new_event", message="hello")]))
    assert packets[0].kind is PacketKind.EVENT
    assert packets[0].text == "hello"


def test_empty_heartbeat_deltas_are_dropped():
    events = [FakeEvent("text_delta", payload={"chunk": ""}), FakeEvent("run_completed")]
    assert [p.kind for p in to_packets(events)] == [PacketKind.FINAL]


def test_packet_serialises_without_empty_keys():
    assert Packet(kind=PacketKind.TEXT, text="hi").to_dict() == {"kind": "text", "text": "hi"}


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #


def test_deleting_every_config_file_leaves_a_working_agent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SHIPIT_CONFIG", raising=False)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    config = load_config()
    assert config.source is None
    assert config.get("tools.max_output_chars") == DEFAULTS["tools"]["max_output_chars"]
    assert "us-east-1" in config.mantle_regions()
    assert config.skill_caps().primed_per_turn == 30


def test_overrides_win_over_defaults_without_erasing_siblings():
    config = load_config(overrides={"tools": {"max_output_chars": 99}})
    assert config.get("tools.max_output_chars") == 99
    assert config.get("tools.enforce_read_before_write") is True


def test_lists_replace_so_a_user_can_shorten_them():
    merged = deep_merge({"a": {"regions": ["x", "y"]}}, {"a": {"regions": ["x"]}})
    assert merged["a"]["regions"] == ["x"]


def test_per_tool_arg_limit_falls_back_to_the_global_cap():
    config = load_config()
    assert config.tool_arg_limit("edit_file") == 262_144
    assert config.tool_arg_limit("grep_search") == 65_536


def test_config_builds_the_runtime_objects_it_describes():
    config = load_config()
    assert config.tier_policy().tier_for(Purpose.SUBAGENT) is ServiceTier.FLEX
    quota = config.retry_schedule().policy_for(ThrottleKind.TOKEN_QUOTA)
    assert quota.base_delay == 20.0
    assert quota.max_attempts == 4


def test_unreadable_config_file_falls_back_to_defaults(tmp_path, monkeypatch):
    bad = tmp_path / "shipit.yaml"
    bad.write_text("{{{ not yaml", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    config = load_config()
    assert config.get("tools.max_output_chars") == DEFAULTS["tools"]["max_output_chars"]


@pytest.mark.parametrize("purpose", list(Purpose))
def test_every_purpose_resolves_to_a_tier(purpose):
    assert isinstance(DEFAULT_TIER_POLICY.tier_for(purpose), ServiceTier)
