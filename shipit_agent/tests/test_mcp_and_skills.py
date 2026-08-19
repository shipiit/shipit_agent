"""MCP attachment, deferred tool disclosure, and the SKILL.md format."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from shipit_agent.discovery import (
    DiscoveryState,
    ToolSearchTool,
    filter_schemas,
    score_match,
)
from shipit_agent.graph import AgentGraph, RunSpec
from shipit_agent.mcp_bridge import (
    MCP_DELIMITER,
    MCPBridge,
    MCPToolDescriptor,
    namespaced,
    split_namespaced,
)
from shipit_agent.models import ToolCall
from shipit_agent.skills.markdown import (
    Skill,
    SkillParseError,
    discover_skills,
    load_skill_dir,
    parse_skill_markdown,
    write_skill,
)
from shipit_agent.tests.test_graph import Reply, ScriptedLLM, spec


# --------------------------------------------------------------------------- #
# Doubles
# --------------------------------------------------------------------------- #


@dataclass
class FakeMCPTool:
    name: str
    description: str = ""
    inputSchema: dict[str, Any] = field(default_factory=dict)


class FakeMCPServer:
    def __init__(
        self,
        name: str,
        tools: list[FakeMCPTool],
        *,
        instructions: str = "",
        fail: bool = False,
    ) -> None:
        self.name = name
        self.instructions = instructions
        self._tools = tools
        self._fail = fail
        self.discoveries = 0

    def discover_tools(self) -> list[FakeMCPTool]:
        self.discoveries += 1
        if self._fail:
            raise RuntimeError("server would not start")
        return self._tools


class FakeConnection:
    def __init__(self, server: str) -> None:
        self.server = server
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def call(self, tool: str, arguments: dict[str, Any]) -> str:
        self.calls.append((tool, arguments))
        return f"{self.server}:{tool} ok"


# --------------------------------------------------------------------------- #
# Namespacing
# --------------------------------------------------------------------------- #


def test_two_servers_may_both_expose_search():
    a = namespaced("jira", "search")
    b = namespaced("slack", "search")
    assert a != b
    assert split_namespaced(a) == ("search", "jira")


def test_a_plain_tool_name_has_no_server():
    assert split_namespaced("bash") == ("bash", None)
    assert MCP_DELIMITER not in "bash"


# --------------------------------------------------------------------------- #
# Attachment
# --------------------------------------------------------------------------- #


def test_attaching_describes_without_connecting():
    server = FakeMCPServer("jira", [FakeMCPTool("search", "Find issues")])
    bridge = MCPBridge([server])
    bridge.attach()

    assert server.discoveries == 1          # descriptors only
    assert [d.name for d in bridge.descriptors()] == ["search__mcp__jira"]


def test_a_broken_server_degrades_itself_not_the_run():
    good = FakeMCPServer("jira", [FakeMCPTool("search", "Find issues")])
    bad = FakeMCPServer("slack", [], fail=True)
    bridge = MCPBridge([good, bad])
    bridge.attach()

    assert len(bridge.descriptors()) == 1
    assert "slack" in bridge.summary()["failed"]
    assert bridge.summary()["healthy"] == 1


def test_server_instructions_reach_the_prefix():
    server = FakeMCPServer(
        "jira",
        [FakeMCPTool("create", "Create an issue")],
        instructions="Always call list_projects before create.",
    )
    bridge = MCPBridge([server])
    bridge.attach()

    graph = AgentGraph(spec(ScriptedLLM(Reply(content="ok")), mcp=bridge))
    assert "list_projects before create" in graph.prefix.system_text


def test_a_server_without_instructions_adds_nothing():
    bridge = MCPBridge([FakeMCPServer("jira", [FakeMCPTool("x")])])
    bridge.attach()
    assert bridge.instructions() == {}


def test_schemas_are_prepared_for_the_models_dialect():
    server = FakeMCPServer(
        "api",
        [
            FakeMCPTool(
                "query",
                "Query it",
                inputSchema={
                    "type": "object",
                    "properties": {"f": {"$ref": "#/$defs/F"}},
                    "$defs": {"F": {"type": "string"}},
                },
            )
        ],
    )
    bridge = MCPBridge([server])
    bridge.attach()
    schemas = bridge.schemas("google.gemma-4-31b")
    assert "$ref" not in repr(schemas)
    assert "$defs" not in repr(schemas)


def test_connection_opens_on_first_call_and_is_reused():
    server = FakeMCPServer("jira", [FakeMCPTool("search", "Find issues")])
    bridge = MCPBridge([server])
    bridge.attach()

    opened: list[str] = []

    def connect(name: str) -> FakeConnection:
        opened.append(name)
        return FakeConnection(name)

    tool = bridge.tools(connect)[0]
    assert opened == []                       # nothing yet
    assert tool.run(None, q="bug") == "jira:search ok"
    assert tool.run(None, q="other") == "jira:search ok"
    assert opened == ["jira"]                 # opened once, reused


def test_large_servers_are_deferred_and_small_ones_are_not():
    small = FakeMCPServer("small", [FakeMCPTool(f"t{i}") for i in range(3)])
    large = FakeMCPServer("large", [FakeMCPTool(f"t{i}") for i in range(50)])
    bridge = MCPBridge([small, large], max_eager_tools=10)
    bridge.attach()

    eager = {d.server for d in bridge.descriptors() if not d.deferred}
    deferred = {d.server for d in bridge.descriptors() if d.deferred}
    assert eager == {"small"}
    assert deferred == {"large"}


def test_a_server_can_be_deferred_by_name():
    bridge = MCPBridge(
        [FakeMCPServer("noisy", [FakeMCPTool("a")])], deferred_servers=["noisy"]
    )
    bridge.attach()
    assert all(d.deferred for d in bridge.descriptors())


def test_attachment_events_report_health_and_counts():
    bridge = MCPBridge(
        [FakeMCPServer("ok", [FakeMCPTool("a")]), FakeMCPServer("bad", [], fail=True)]
    )
    bridge.attach()
    events = list(bridge.events())
    payloads = {e.payload["server"]: e.payload for e in events}
    assert payloads["ok"]["tools"] == 1
    assert "error" in payloads["bad"]


# --------------------------------------------------------------------------- #
# Deferred disclosure
# --------------------------------------------------------------------------- #


def test_search_matches_descriptions_not_just_names():
    score = score_match(
        "file a bug", name="create_issue__mcp__jira", description="Create a bug report"
    )
    assert score > 0


def test_a_name_hit_outranks_a_description_hit():
    named = score_match("search", name="search__mcp__jira", description="")
    described = score_match("search", name="query__mcp__jira", description="search things")
    assert named > described


def test_searching_makes_a_tool_callable():
    state = DiscoveryState(
        deferred={"create_issue__mcp__jira": "Create a bug report"},
        servers={"create_issue__mcp__jira": "jira"},
    )
    assert not state.is_available("create_issue__mcp__jira")

    output = ToolSearchTool(state).run(query="file a bug")
    assert "create_issue__mcp__jira" in output.text
    assert state.is_available("create_issue__mcp__jira")


def test_search_returns_the_signature_so_no_second_round_trip_is_needed():
    state = DiscoveryState(deferred={"create__mcp__jira": "Create an issue"})
    schemas = {
        "create__mcp__jira": {
            "function": {
                "name": "create__mcp__jira",
                "parameters": {
                    "type": "object",
                    "properties": {"title": {"type": "string"}, "body": {"type": "string"}},
                    "required": ["title"],
                },
            }
        }
    }
    output = ToolSearchTool(state, schemas=schemas).run(query="create issue")
    assert "title: string" in output.text
    assert "body?: string" in output.text     # optional marked


def test_a_miss_teaches_rather_than_just_failing():
    state = DiscoveryState(
        deferred={"a__mcp__jira": "x", "b__mcp__slack": "y"},
        servers={"a__mcp__jira": "jira", "b__mcp__slack": "slack"},
    )
    text = ToolSearchTool(state).run(query="quantum tunnelling").text
    assert "jira" in text and "slack" in text
    assert "Examples of what is available" in text


def test_filter_schemas_hides_what_is_still_deferred():
    state = DiscoveryState(deferred={"hidden": "x"})
    schemas = [
        {"function": {"name": "visible"}},
        {"function": {"name": "hidden"}},
    ]
    assert [s["function"]["name"] for s in filter_schemas(state, schemas)] == ["visible"]


def test_discovery_state_round_trips_for_resume():
    state = DiscoveryState(deferred={"a": "x"}, servers={"a": "srv"})
    state.discover("a")
    restored = DiscoveryState.from_dict(state.to_dict())
    assert restored.is_available("a")


# --------------------------------------------------------------------------- #
# Discovery inside a run
# --------------------------------------------------------------------------- #


def test_deferred_mcp_tools_are_absent_until_searched():
    server = FakeMCPServer("jira", [FakeMCPTool(f"t{i}", f"tool {i}") for i in range(20)])
    bridge = MCPBridge([server], max_eager_tools=5)
    bridge.attach()

    graph = AgentGraph(spec(ScriptedLLM(Reply(content="ok")), mcp=bridge))
    bound = {d["function"]["name"] for d in graph.prefix.tool_definitions}
    assert "t0__mcp__jira" not in bound
    assert "tool_search" in bound


def test_calling_a_deferred_tool_directly_is_a_recoverable_result():
    server = FakeMCPServer("jira", [FakeMCPTool(f"t{i}") for i in range(20)])
    bridge = MCPBridge([server], max_eager_tools=1)
    bridge.attach()

    llm = ScriptedLLM(
        Reply(tool_calls=[ToolCall(name="t0__mcp__jira", arguments={})]),
        Reply(content="recovered"),
    )
    graph = AgentGraph(spec(llm, mcp=bridge))
    list(graph.run("go"))

    assert graph.tool_results[0].is_error
    assert "tool_search" in graph.tool_results[0].output


def test_search_then_call_works_in_one_run():
    server = FakeMCPServer("jira", [FakeMCPTool("create_issue", "Create a bug report")])
    bridge = MCPBridge([server], deferred_servers=["jira"])
    bridge.attach()
    bridge.connect = lambda name: FakeConnection(name)  # type: ignore[attr-defined]

    llm = ScriptedLLM(
        Reply(tool_calls=[ToolCall(name="tool_search", arguments={"query": "file a bug"})]),
        Reply(tool_calls=[ToolCall(name="create_issue__mcp__jira", arguments={"title": "x"})]),
        Reply(content="filed"),
    )
    graph = AgentGraph(spec(llm, mcp=bridge))
    kinds = [e.type for e in graph.run("file a bug")]

    assert "tools_discovered" in kinds
    assert "tools_rebound" in kinds
    assert graph.result().output == "filed"
    assert not graph.tool_results[-1].is_error


def test_the_prefix_is_rebuilt_only_when_capability_actually_changed():
    server = FakeMCPServer("jira", [FakeMCPTool("a", "x")])
    bridge = MCPBridge([server])
    bridge.attach()
    llm = ScriptedLLM(Reply(content="ok"))
    graph = AgentGraph(spec(llm, mcp=bridge))
    before = graph.prefix.fingerprint()
    list(graph.run("hi"))
    assert graph.prefix.fingerprint() == before


# --------------------------------------------------------------------------- #
# SKILL.md
# --------------------------------------------------------------------------- #

SKILL_MD = """---
name: Invoice Processing
description: Extract totals and VAT from supplier invoices. Use when handling PDF or scanned invoices.
tools: [file_read, pdf]
trigger_phrases: ["process invoice", "invoice totals"]
version: 2.1.0
---

# Invoice Processing

1. Read the invoice.
2. For VAT edge cases, read `references/vat-rules.md`.
"""


def test_front_matter_and_body_are_separated():
    skill = parse_skill_markdown(SKILL_MD)
    assert skill.id == "invoice-processing"
    assert skill.tools == ["file_read", "pdf"]
    assert skill.trigger_phrases == ["process invoice", "invoice totals"]
    assert skill.version == "2.1.0"
    assert skill.body.startswith("# Invoice Processing")
    assert "description:" not in skill.body


def test_the_description_says_when_not_just_what():
    """The catalog line is all the model sees when choosing."""
    skill = parse_skill_markdown(SKILL_MD)
    assert "Use when" in skill.description


def test_a_skill_without_a_description_is_rejected_with_the_reason():
    with pytest.raises(SkillParseError, match="never be selected"):
        parse_skill_markdown("---\nname: X\n---\n")


def test_plain_markdown_without_front_matter_still_loads():
    skill = parse_skill_markdown("# Release Notes\n\nWrite release notes from commits.\n")
    assert skill.name == "Release Notes"
    assert "release notes" in skill.description.lower()


def test_reference_files_are_listed_but_not_loaded(tmp_path):
    directory = tmp_path / "invoice"
    directory.mkdir()
    (directory / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
    references = directory / "references"
    references.mkdir()
    (references / "vat-rules.md").write_text("VAT DETAIL", encoding="utf-8")

    skill = load_skill_dir(directory)
    assert skill.references() == ["references/vat-rules.md"]
    assert "VAT DETAIL" not in skill.body           # not in context
    assert skill.reference("references/vat-rules.md") == "VAT DETAIL"


def test_a_reference_cannot_escape_its_directory(tmp_path):
    directory = tmp_path / "s"
    directory.mkdir()
    (directory / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
    with pytest.raises(ValueError, match="escapes"):
        load_skill_dir(directory).reference("../../etc/passwd")


def test_discovery_skips_a_bad_skill_and_keeps_the_rest(tmp_path):
    good = tmp_path / "good"
    good.mkdir()
    (good / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "SKILL.md").write_text("---\nname: Broken\n---\n", encoding="utf-8")

    found = discover_skills(tmp_path)
    assert [s.id for s in found] == ["invoice-processing"]


def test_an_earlier_root_shadows_a_later_one(tmp_path):
    for index, root in enumerate(["project", "shipped"]):
        directory = tmp_path / root / "invoice"
        directory.mkdir(parents=True)
        (directory / "SKILL.md").write_text(
            SKILL_MD.replace("version: 2.1.0", f"version: {index}.0.0"), encoding="utf-8"
        )
    found = discover_skills(tmp_path / "project", tmp_path / "shipped")
    assert found[0].version == "0.0.0"


def test_a_skill_round_trips_through_disk(tmp_path):
    original = Skill(
        id="release-notes",
        name="Release Notes",
        description="Write release notes from commits. Use when cutting a release.",
        body="## Steps\n\n1. Read the log.",
        tools=["git_ops"],
        trigger_phrases=["release notes"],
    )
    write_skill(tmp_path / "release-notes", original)
    restored = load_skill_dir(tmp_path / "release-notes")

    assert restored.id == original.id
    assert restored.tools == original.tools
    assert restored.trigger_phrases == original.trigger_phrases
    assert "Read the log" in restored.body


def test_a_skill_folder_drops_straight_into_a_run(tmp_path):
    directory = tmp_path / "invoice"
    directory.mkdir()
    (directory / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")

    graph = AgentGraph(
        spec(ScriptedLLM(Reply(content="ok")), skills=discover_skills(tmp_path))
    )
    assert "invoice-processing" in graph.prefix.system_text
    assert "VAT edge cases" not in graph.prefix.system_text   # body stays out
