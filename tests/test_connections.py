"""Connections — what the agent can reach, and what it needs from you."""

from __future__ import annotations

import time

import pytest

from shipit_agent.connections import (
    AuthKind,
    ConnectionRegistry,
    ConnectionState,
    title_for,
)
from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.connections import ConnectionsTool
from shipit_agent.tools.connections.connections_tool import REGISTRY_STATE_KEY


class FakeRecord:
    def __init__(self, secrets=None, metadata=None):
        self.secrets = secrets or {}
        self.metadata = metadata or {}


class FakeStore:
    def __init__(self, records=None, raises=False):
        self.records = records or {}
        self.raises = raises

    def get(self, key):
        if self.raises:
            raise RuntimeError("store is down")
        return self.records.get(key)


def connector(name, credential_key, description="a connector"):
    class T:
        def __init__(self):
            self.name = name
            self.credential_key = credential_key
            self.description = description
            self.prompt_instructions = ""

        def schema(self):
            return {"function": {"name": name, "parameters": {}}}

    return T()


def registry(records=None, tools=None, **kwargs):
    return ConnectionRegistry(
        credential_store=FakeStore(records) if records is not None else None,
        tools=tools if tools is not None else [connector("slack", "slack")],
        **kwargs,
    )


class TestDiscovery:
    def test_connectors_are_discovered_from_the_tools(self) -> None:
        # Not a maintained list — a registry with its own list would drift.
        found = registry(tools=[connector("slack", "slack"),
                                connector("github", "github")]).all()
        assert {c.id for c in found} == {"slack", "github"}

    def test_tools_sharing_a_credential_are_one_connection(self) -> None:
        found = registry(tools=[
            connector("google_sheets", "google"),
            connector("google_drive", "google"),
        ]).all()
        assert len(found) == 1
        assert set(found[0].tools) == {"google_sheets", "google_drive"}

    def test_tools_without_credentials_are_ignored(self) -> None:
        class Plain:
            name = "read_file"

        assert registry(tools=[Plain()]).all() == []

    def test_every_real_connector_is_found(self) -> None:
        from shipit_agent.builtins import get_builtin_tools

        found = registry(tools=get_builtin_tools(llm=None, project_root=".")).all()
        assert len(found) == 17

    def test_attached_mcp_servers_are_connected_by_definition(self) -> None:
        class MCP:
            name = "playwright"
            description = "browser"

        found = ConnectionRegistry(tools=[], mcps=[MCP()]).all()
        assert found[0].kind == "mcp"
        assert found[0].state is ConnectionState.CONNECTED

    def test_the_catalog_is_off_by_default(self) -> None:
        # "What's connected?" should not answer with a shopping list.
        assert ConnectionRegistry(tools=[], mcps=[]).all() == []
        assert ConnectionRegistry(tools=[], mcps=[], include_catalog=True).all()


class TestStateResolution:
    def test_no_store_means_disconnected(self) -> None:
        # Not "needs auth" — nothing is configured at all.
        assert registry().all()[0].state is ConnectionState.DISCONNECTED

    def test_no_record_means_disconnected(self) -> None:
        assert registry({}).all()[0].state is ConnectionState.DISCONNECTED

    def test_a_record_with_a_secret_is_connected(self) -> None:
        found = registry({"slack": FakeRecord({"token": "xoxb-1"})}).all()[0]
        assert found.state is ConnectionState.CONNECTED
        assert found.usable

    @pytest.mark.parametrize("field", ["api_key", "token", "access_token", "password"])
    def test_any_secret_field_counts(self, field) -> None:
        assert registry({"slack": FakeRecord({field: "x"})}).all()[0].usable

    def test_a_record_with_no_secret_needs_auth(self) -> None:
        # Someone started setting this up and did not finish.
        found = registry({"slack": FakeRecord({}, {"account": "a@b.c"})}).all()[0]
        assert found.state is ConnectionState.NEEDS_AUTH

    def test_an_expired_token_is_distinct_from_disconnected(self) -> None:
        """"Reconnect this" and "set this up" are different instructions."""
        found = registry({"slack": FakeRecord(
            {"token": "x"}, {"expires_at": time.time() - 60})}).all()[0]
        assert found.state is ConnectionState.EXPIRED
        assert "Reconnect" in found.next_step()

    def test_a_future_expiry_is_still_connected(self) -> None:
        found = registry({"slack": FakeRecord(
            {"token": "x"}, {"expires_at": time.time() + 3600})}).all()[0]
        assert found.state is ConnectionState.CONNECTED

    def test_a_malformed_expiry_does_not_break_resolution(self) -> None:
        found = registry({"slack": FakeRecord(
            {"token": "x"}, {"expires_at": "not a number"})}).all()[0]
        assert found.state is ConnectionState.CONNECTED

    def test_a_failing_store_becomes_an_error_not_an_exception(self) -> None:
        reg = ConnectionRegistry(
            credential_store=FakeStore(raises=True),
            tools=[connector("slack", "slack")],
        )
        found = reg.all()[0]
        assert found.state is ConnectionState.ERROR
        assert "store is down" in found.error

    def test_the_account_is_surfaced(self) -> None:
        found = registry({"slack": FakeRecord(
            {"token": "x"}, {"email": "events@acme.com"})}).all()[0]
        assert found.account == "events@acme.com"
        assert "events@acme.com" in found.describe()


class TestGuidance:
    @pytest.mark.parametrize("key,expected", [
        ("slack", "sign in"),
        ("github", "a token"),
        ("stripe", "an API key"),
    ])
    def test_the_next_step_matches_the_auth_kind(self, key, expected) -> None:
        """Wrong guidance is worse than none.

        Telling someone to "sign in" for something that wants a pasted key
        sends them looking for a button that does not exist.
        """
        found = registry({}, tools=[connector(key, key)]).all()[0]
        assert expected in found.next_step()

    def test_a_connected_one_needs_no_step(self) -> None:
        assert registry({"slack": FakeRecord({"token": "x"})}).all()[0].next_step() == ""

    def test_titles_are_human(self) -> None:
        assert title_for("google_sheets") == "Google Sheets"
        assert title_for("some_new_thing") == "Some New Thing"


class TestOrderingAndQueries:
    def _mixed(self):
        return registry(
            {"slack": FakeRecord({"token": "x"})},
            tools=[connector("slack", "slack"), connector("github", "github"),
                   connector("stripe", "stripe")],
        )

    def test_connected_come_first(self) -> None:
        assert self._mixed().all()[0].id == "slack"

    def test_connected_and_needing_action_split(self) -> None:
        reg = self._mixed()
        assert [c.id for c in reg.connected()] == ["slack"]
        assert {c.id for c in reg.needing_action()} == {"github", "stripe"}

    def test_is_connected(self) -> None:
        reg = self._mixed()
        assert reg.is_connected("slack")
        assert not reg.is_connected("github")
        assert not reg.is_connected("nonexistent")

    def test_lookup_by_title_as_well_as_id(self) -> None:
        reg = self._mixed()
        assert reg.get("Slack") is reg.get("slack") or reg.get("Slack").id == "slack"

    def test_summary_counts(self) -> None:
        assert self._mixed().summary() == {
            "total": 3, "connected": 1, "needs_action": 2, "pending_requests": 0
        }


class TestRequests:
    def test_a_request_is_recorded(self) -> None:
        reg = registry({})
        request = reg.request("slack", "to post the release notes")
        assert request.title == "Slack"
        assert reg.pending_requests() == [request]

    def test_the_request_carries_the_auth_kind(self) -> None:
        assert registry({}).request("slack", "why").auth is AuthKind.OAUTH

    def test_an_unknown_connection_can_still_be_requested(self) -> None:
        # The model may know about something we do not.
        assert registry({}).request("bigquery", "for usage data").title == "bigquery"


class TestTool:
    def _ctx(self, reg=None):
        return ToolContext(
            prompt="x",
            state={REGISTRY_STATE_KEY: reg if reg is not None else registry({})},
        )

    def test_list(self) -> None:
        out = ConnectionsTool().run(self._ctx(), action="list")
        assert "Slack" in out.text
        assert out.metadata["total"] == 1

    def test_list_is_the_default(self) -> None:
        assert "Slack" in ConnectionsTool().run(self._ctx()).text

    def test_connected_only(self) -> None:
        reg = registry({"slack": FakeRecord({"token": "x"})},
                       tools=[connector("slack", "slack"),
                              connector("github", "github")])
        out = ConnectionsTool().run(self._ctx(reg), action="list", connected_only=True)
        assert "Slack" in out.text and "GitHub" not in out.text

    def test_check_one(self) -> None:
        out = ConnectionsTool().run(self._ctx(), action="check", connection="slack")
        assert out.metadata["id"] == "slack"
        assert "sign in" in out.text

    def test_check_an_unknown_one_lists_what_exists(self) -> None:
        out = ConnectionsTool().run(self._ctx(), action="check", connection="nope")
        assert out.metadata["ok"] is False
        assert "slack" in out.text

    def test_request(self) -> None:
        reg = registry({})
        out = ConnectionsTool().run(
            self._ctx(reg), action="request", connection="slack",
            reason="to post the release notes",
        )
        assert out.metadata["requested"] is True
        assert "release notes" in out.text
        assert "do not retry" in out.text.lower()
        assert len(reg.pending_requests()) == 1

    def test_a_request_needs_a_reason(self) -> None:
        # A request with no reason is one the user cannot evaluate.
        out = ConnectionsTool().run(self._ctx(), action="request", connection="slack")
        assert out.metadata["error"] == "missing_reason"

    def test_requesting_something_already_connected_says_so(self) -> None:
        reg = registry({"slack": FakeRecord({"token": "x"})})
        out = ConnectionsTool().run(
            self._ctx(reg), action="request", connection="slack", reason="why"
        )
        assert out.metadata["already_connected"] is True
        assert reg.pending_requests() == []

    def test_it_is_an_observation(self) -> None:
        from shipit_agent.tools.contracts import contract_for

        assert contract_for("connections").read_only

    def test_registered_as_a_builtin(self) -> None:
        from shipit_agent.builtins import get_builtin_tools

        names = {getattr(t, "name", "") for t in
                 get_builtin_tools(llm=None, project_root=".")}
        assert "connections" in names

    def test_outside_a_run_it_says_so(self) -> None:
        out = ConnectionsTool().run(ToolContext(prompt="x"), action="list")
        assert out.metadata["error"] == "no_registry"


class TestNarration:
    def test_listing_matches_the_reference_phrasing(self) -> None:
        from shipit_agent.narrate import summarize

        assert summarize("connections", {"action": "list"}).past_label() == (
            "Listed connectable resources"
        )

    def test_requesting_reads_differently_from_listing(self) -> None:
        from shipit_agent.narrate import summarize

        label = summarize(
            "connections", {"action": "request", "connection": "github"}
        ).past_label()
        assert label == "Requested a connection to github"


class TestRuntimeIntegration:
    def test_the_registry_reaches_the_tool_in_a_real_run(self) -> None:
        from shipit_agent import Agent
        from shipit_agent.llms.base import LLMResponse
        from shipit_agent.models import ToolCall

        class L:
            model = "m"

            def __init__(self):
                self.n = 0

            def complete(self, **kw):
                self.n += 1
                if self.n == 1:
                    return LLMResponse(tool_calls=[
                        ToolCall(name="connections", arguments={"action": "list"})])
                return LLMResponse(content="checked")

        result = Agent(
            llm=L(),
            tools=[ConnectionsTool(), connector("slack", "slack")],
            auto_use_skills=False,
            max_iterations=3,
        ).run("what's connected?")
        listing = [m for m in result.messages if m.role == "tool"][0].content
        assert "Slack" in listing
