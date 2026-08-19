"""Per-directory tools, the rules block, and MCP connector records."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from shipit_agent.connections.mcp import (
    MCP_CATALOG,
    MCPAuth,
    MCPAuthKind,
    MCPConnector,
    MCPConnectorRegistry,
    Transport,
)
from shipit_agent.prefix_rules import collect_tool_rules, render_rules
from shipit_agent.tools import core_tools, specialist_tools
from shipit_agent.tools.fetch_url import html_to_text
from shipit_agent.tools.memory import MemoryStore, MemoryTool
from shipit_agent.tools.web_search import WebSearchTool


def by_name(tools: list[Any]) -> dict[str, Any]:
    return {t.name: t for t in tools}


# --------------------------------------------------------------------------- #
# Layout
# --------------------------------------------------------------------------- #


def test_each_tool_lives_in_its_own_package():
    root = Path(__file__).resolve().parent.parent / "tools"
    for name in ("bash", "read_file", "edit_file", "grep", "web_search", "memory"):
        assert (root / name / "__init__.py").is_file()
        assert (root / name / f"{name}_tool.py").is_file() or name == "memory"
        assert (root / name / "prompt.py").is_file()


def test_every_tool_carries_its_own_prompt_guidance():
    for tool in core_tools(".") + specialist_tools():
        assert tool.description, tool.name
        assert tool.prompt_instructions, tool.name


def test_the_core_seven_and_the_five_specialists():
    assert [t.name for t in core_tools(".")] == [
        "bash", "read_file", "write_file", "edit_file", "glob", "grep", "todo"
    ]
    assert [t.name for t in specialist_tools()] == [
        "fetch_url", "web_search", "ask_user", "memory", "report_progress"
    ]


# --------------------------------------------------------------------------- #
# fetch_url
# --------------------------------------------------------------------------- #


def test_html_becomes_readable_text():
    text = html_to_text("<h1>Title</h1><script>evil()</script><p>Body &amp; more</p>")
    assert "Title" in text and "Body & more" in text
    assert "evil" not in text


def test_a_file_url_is_refused():
    tool = by_name(specialist_tools())["fetch_url"]
    output = tool.run(url="file:///etc/passwd")
    assert output.metadata.get("is_error")
    assert "not allowed" in output.text


def test_a_fetch_failure_is_a_result_not_a_raise():
    def broken(url: str, timeout: int):
        raise ConnectionError("no route to host")

    from shipit_agent.tools.fetch_url import FetchUrlTool

    output = FetchUrlTool(opener=broken).run(url="https://example.com")
    assert output.metadata.get("is_error")
    assert "no route to host" in output.text


def test_a_successful_fetch_returns_text_and_status():
    from shipit_agent.tools.fetch_url import FetchUrlTool

    tool = FetchUrlTool(opener=lambda u, t: (200, "text/html", "<p>hello</p>"))
    output = tool.run(url="https://example.com")
    assert output.text.strip() == "hello"
    assert output.metadata["status"] == 200


# --------------------------------------------------------------------------- #
# web_search
# --------------------------------------------------------------------------- #


def test_search_without_a_backend_says_so_rather_than_returning_nothing():
    output = WebSearchTool().run(query="anything")
    assert output.metadata.get("is_error")
    assert "No search backend" in output.text


def test_results_are_rendered_with_the_snippet_caveat():
    def backend(query: str, limit: int):
        return [{"title": "A", "url": "https://a.test", "snippet": "about a"}]

    output = WebSearchTool(backend).run(query="a")
    assert "https://a.test" in output.text
    assert "Fetch a page before relying on it" in output.text
    assert output.metadata["urls"] == ["https://a.test"]


def test_a_failing_backend_is_reported():
    def backend(query: str, limit: int):
        raise RuntimeError("quota exceeded")

    output = WebSearchTool(backend).run(query="a")
    assert output.metadata.get("is_error")
    assert "quota exceeded" in output.text


# --------------------------------------------------------------------------- #
# memory
# --------------------------------------------------------------------------- #


def test_memory_persists_across_instances(tmp_path):
    path = tmp_path / "memory.json"
    MemoryTool(MemoryStore(path)).run(action="set", key="editor", value="neovim")
    assert MemoryTool(MemoryStore(path)).run(action="get", key="editor").text == "neovim"


def test_an_oversized_value_is_refused_with_the_reason(tmp_path):
    tool = MemoryTool(MemoryStore(tmp_path / "m.json"))
    output = tool.run(action="set", key="k", value="x" * 5000)
    assert output.metadata.get("is_error")
    assert "the conclusion, not the whole document" in output.text


def test_a_corrupt_memory_file_does_not_stop_a_run(tmp_path):
    path = tmp_path / "m.json"
    path.write_text("{ truncated", encoding="utf-8")
    assert MemoryStore(path).items == {}


# --------------------------------------------------------------------------- #
# ask_user
# --------------------------------------------------------------------------- #


def test_an_unattended_run_is_told_to_assume_and_say_so():
    output = by_name(specialist_tools())["ask_user"].run(question="which branch?")
    assert output.metadata["unattended"]
    assert "state clearly what you assumed" in output.text


def test_a_handler_answers_the_question():
    from shipit_agent.tools.ask_user import AskUserTool

    tool = AskUserTool(lambda q, o: "main")
    assert tool.run(question="which branch?").text == "main"
    assert tool.asked == ["which branch?"]


# --------------------------------------------------------------------------- #
# Rules
# --------------------------------------------------------------------------- #


class FakeRule:
    def __init__(self, text, *, tools=(), priority=0, rule_id="", source=""):
        self.text = text
        self.tools = tools
        self.priority = priority
        self.id = rule_id
        self.source = source

    def applies(self, *, tools=frozenset(), paths=()):
        return not self.tools or bool(set(self.tools) & set(tools))


def test_a_tool_scoped_rule_is_hidden_when_the_tool_is_absent():
    rules = [FakeRule("never rm -rf", tools=("bash",)), FakeRule("always test")]
    assert "rm -rf" not in render_rules(rules, active_tools=["grep"])
    assert "rm -rf" in render_rules(rules, active_tools=["bash"])


def test_rules_are_ordered_by_priority_then_deterministically():
    rules = [
        FakeRule("low", priority=1, rule_id="b"),
        FakeRule("high", priority=9, rule_id="a"),
    ]
    assert render_rules(rules).splitlines()[0] == "- high"


def test_the_same_guidance_from_two_sources_appears_once():
    rules = [FakeRule("write a test", source="AGENTS.md"), FakeRule("write a test", source="agent")]
    assert render_rules(rules).count("write a test") == 1


def test_rendering_is_byte_stable_across_calls():
    rules = [FakeRule("a", priority=2), FakeRule("b", priority=1)]
    assert len({render_rules(rules) for _ in range(5)}) == 1


def test_a_tool_can_ship_its_own_rules():
    class Guarded:
        name = "bash"
        rules = [FakeRule("never rm -rf", tools=("bash",))]

    assert len(collect_tool_rules([Guarded()])) == 1


# --------------------------------------------------------------------------- #
# MCP connectors
# --------------------------------------------------------------------------- #


def test_a_connector_holds_a_variable_name_not_a_secret():
    connector = MCPConnector.from_dict("github", MCP_CATALOG["github"])
    assert connector.auth.env == "GITHUB_PERSONAL_ACCESS_TOKEN"
    assert "ghp_" not in repr(connector)


def test_a_missing_token_is_a_named_state_before_any_call(monkeypatch):
    monkeypatch.delenv("GITHUB_PERSONAL_ACCESS_TOKEN", raising=False)
    status = MCPConnector.from_dict("github", MCP_CATALOG["github"]).check()
    assert status.state == "missing_credentials"
    assert status.missing == ["GITHUB_PERSONAL_ACCESS_TOKEN"]


def test_a_resolved_token_becomes_a_header_only_at_connect_time(monkeypatch):
    monkeypatch.setenv("TOK", "secret")
    connector = MCPConnector(
        name="x",
        transport=Transport.SSE,
        url="https://x.test/sse",
        auth=MCPAuth(kind=MCPAuthKind.BEARER, env="TOK"),
    )
    assert "secret" not in repr(connector)
    assert connector.connection_kwargs()["headers"]["Authorization"] == "Bearer secret"


def test_a_stdio_connector_missing_its_binary_says_which():
    connector = MCPConnector(name="x", command=("definitely-not-installed", "--go"))
    status = connector.check()
    assert status.state == "missing_binary"
    assert "definitely-not-installed" in status.advice


def test_a_misconfigured_connector_is_caught_before_connecting():
    assert MCPConnector(name="x", transport=Transport.SSE).check().state == "misconfigured"
    assert MCPConnector(name="y", transport=Transport.STDIO).check().state == "misconfigured"


def test_a_catalog_template_can_be_overridden_in_two_lines():
    registry = MCPConnectorRegistry.from_config(
        {"fs": {"use": "filesystem", "command": ["npx", "-y", "srv", "./src"]}}
    )
    connector = registry.get("fs")
    assert connector is not None
    assert connector.command[-1] == "./src"
    assert connector.description == MCP_CATALOG["filesystem"]["description"]


def test_one_bad_entry_does_not_cost_the_others():
    registry = MCPConnectorRegistry.from_config(
        {"good": {"use": "git"}, "bad": {"transport": "carrier-pigeon"}}
    )
    assert len(registry) == 1
    assert registry.get("good") is not None


def test_the_report_shows_every_problem_at_once(monkeypatch):
    monkeypatch.delenv("GITHUB_PERSONAL_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    report = MCPConnectorRegistry.from_catalog("github", "slack").report()
    assert report["total"] == 2
    assert len(report["problems"]) == 2


def test_deferred_servers_are_named_for_the_bridge():
    assert MCPConnectorRegistry.from_catalog("slack", "git").deferred_names() == ["slack"]


def test_a_disabled_connector_is_its_own_state():
    assert MCPConnector(name="x", enabled=False).check().state == "disabled"
