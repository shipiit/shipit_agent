"""MCP servers are discovered concurrently at registry build time.

Each server's connect is a network handshake; doing 20 serially is 20x the
latency. These tests prove discovery runs in parallel, preserves order (so tool
collision handling is deterministic), and re-raises a failing server's error
exactly as the old serial path did.
"""

from __future__ import annotations

import time

import pytest

from shipit_agent.registry import ToolRegistry


class FakeTool:
    def __init__(self, name):
        self.name = name
        self.metadata = {}

    def schema(self):
        return {"type": "function", "function": {"name": self.name, "parameters": {}}}

    def run(self, context=None, **kwargs):
        return None


class SlowServer:
    """An MCP-server stand-in whose discovery sleeps, to expose serialisation."""

    def __init__(self, name, tool_names, delay=0.2, error=None):
        self.name = name
        self._tools = [FakeTool(n) for n in tool_names]
        self._delay = delay
        self._error = error

    def discover_tools(self):
        time.sleep(self._delay)
        if self._error:
            raise self._error
        return self._tools


def test_discovery_runs_in_parallel():
    servers = [SlowServer(f"s{i}", [f"tool_{i}"], delay=0.2) for i in range(4)]
    t0 = time.time()
    reg = ToolRegistry.build(mcps=servers)
    elapsed = time.time() - t0
    # 4 servers x 0.2s serial = 0.8s; parallel should be well under half that.
    assert elapsed < 0.5, f"discovery looks serial ({elapsed:.2f}s)"
    assert {"tool_0", "tool_1", "tool_2", "tool_3"} <= set(reg.tools)


def test_order_is_preserved_for_collision_handling():
    # Two servers expose the same tool name; the FIRST keeps the bare name,
    # the second is renamed — which requires ordered registration.
    a = SlowServer("alpha", ["dup"], delay=0.05)
    b = SlowServer("beta", ["dup"], delay=0.05)
    reg = ToolRegistry.build(mcps=[a, b])
    assert "dup" in reg.tools           # alpha (first) keeps the bare name
    assert "beta__dup" in reg.tools     # beta (second) is namespaced


def test_a_failing_server_is_isolated_not_fatal():
    """A failing server used to abort the whole build.

    That made one unreachable server — a sleeping laptop, an expired token, a
    container still starting — take down every unrelated tool with it. The
    healthy server's tools must survive; the dead one contributes nothing when
    there is no cached schema to build stubs from.
    """
    good = SlowServer("good", ["ok"], delay=0.05)
    bad = SlowServer("bad", [], delay=0.05, error=RuntimeError("connect refused"))
    reg = ToolRegistry.build(mcps=[good, bad])
    assert "ok" in reg.tools


def test_the_failure_is_reported_not_swallowed(caplog):
    """Isolation must not mean silence — a tool vanishing with no explanation
    is harder to diagnose than a crash."""
    bad = SlowServer("bad", [], delay=0.01, error=RuntimeError("connect refused"))
    with caplog.at_level("WARNING"):
        ToolRegistry.build(mcps=[bad])
    assert any("unreachable" in r.message.lower() for r in caplog.records)


def test_single_server_still_works():
    reg = ToolRegistry.build(mcps=[SlowServer("solo", ["only"], delay=0.01)])
    assert "only" in reg.tools
