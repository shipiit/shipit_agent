"""One dead MCP server must not take down the agent.

Discovery used to re-raise, so an unreachable server — a sleeping laptop, an
expired token, a container still starting — failed the whole run at
construction, taking every unrelated tool with it.
"""

from __future__ import annotations

import pytest

from shipit_agent.registry import ToolRegistry, UnavailableTool
from shipit_agent.tools.base import ToolOutput


class _DeadServer:
    name = "dead"

    def discover_tools(self):
        raise ConnectionError("connection refused")


class _LiveServer:
    name = "live"

    def discover_tools(self):
        return [_LocalTool("remote_ok")]


class _LocalTool:
    prompt_instructions = ""

    def __init__(self, name: str) -> None:
        self.name = name
        self.description = "ok"
        self.metadata: dict = {}

    def schema(self) -> dict:
        return {"type": "function", "function": {"name": self.name}}

    def run(self, context, **kwargs):
        return ToolOutput(text="fine", metadata={})


class TestIsolation:
    def test_a_dead_server_does_not_fail_construction(self) -> None:
        registry = ToolRegistry.build(tools=[_LocalTool("local")], mcps=[_DeadServer()])
        assert "local" in registry.tools

    def test_healthy_servers_still_register(self) -> None:
        registry = ToolRegistry.build(mcps=[_DeadServer(), _LiveServer()])
        assert "remote_ok" in registry.tools

    def test_no_cached_schema_means_no_stubs_rather_than_invented_ones(self) -> None:
        """With nothing cached there is no honest tool list to advertise."""
        registry = ToolRegistry.build(mcps=[_DeadServer()])
        assert registry.tools == {}


class TestStubBehaviour:
    def test_stub_reports_unavailability_to_the_model(self) -> None:
        stub = UnavailableTool("search", "dead", "ConnectionError: refused")
        result = stub.run(None)
        assert result.metadata["error"] == "mcp_unavailable"
        assert "unavailable" in result.text.lower()
        assert "do not retry" in result.text.lower()

    def test_stub_advertises_itself_as_unavailable_in_its_description(self) -> None:
        """The model reads the schema before it ever calls the tool; that is
        the cheapest place to tell it."""
        stub = UnavailableTool("search", "dead")
        assert "UNAVAILABLE" in stub.schema()["function"]["description"]

    def test_stub_is_read_only_so_no_approval_gate_fires(self) -> None:
        """A stub cannot do anything, so treating it as side-effecting would
        put an approval prompt in front of a guaranteed no-op."""
        assert UnavailableTool("write_thing", "dead").read_only is True

    def test_stub_carries_server_provenance(self) -> None:
        stub = UnavailableTool("search", "dead")
        assert stub.metadata["server"] == "dead"
        assert stub.metadata["unavailable"] is True

    def test_stub_accepts_any_arguments(self) -> None:
        """The real schema is unknown — that is what failed discovery means —
        so the stub must not reject the call before explaining itself."""
        stub = UnavailableTool("search", "dead")
        assert "unavailable" in stub.run(None, anything=1, else_=2).text.lower()
