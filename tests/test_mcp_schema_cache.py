"""MCP schema cache + lazy register.

The point of the feature is that a warm start rebuilds an MCP server's tools
from disk *without spawning the process* until a tool is actually called. These
tests use a recording stub transport (no subprocess) and assert on exactly which
protocol requests happen — the only way to prove laziness rather than assume it.
"""

from __future__ import annotations

import pytest

from shipit_agent import mcp_schema_cache as sc
from shipit_agent.mcp import MCPError, RemoteMCPServer
from shipit_agent.tools.base import ToolContext


class RecordingTransport:
    """A stub MCP transport that records every request. No process, no network."""

    def __init__(self, *, command=None, tools=None, fail_initialize=False):
        self.command = command or ["fake-server", "--stdio"]
        self.env = {"FAKE_KEY": "secret"}
        self.generation = 0
        self.calls: list[str] = []
        self.closed = 0
        self._tools = tools if tools is not None else [
            {"name": "do_thing", "description": "does a thing",
             "inputSchema": {"type": "object", "properties": {"x": {"type": "string"}}}},
        ]
        self._fail_initialize = fail_initialize

    def request(self, method, params=None):
        self.calls.append(method)
        if method == "initialize":
            if self._fail_initialize:
                raise MCPError("server refused the handshake")
            return {"protocolVersion": "2025-11-25", "capabilities": {},
                    "serverInfo": {"name": "fake"}, "instructions": ""}
        if method == "tools/list":
            return {"tools": self._tools}
        if method == "tools/call":
            return {"content": [{"type": "text", "text": "ok"}], "isError": False}
        raise MCPError(f"unexpected method {method}")

    def close(self):
        self.closed += 1


@pytest.fixture
def cache_home(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIPIT_MCP_CACHE_DIR", str(tmp_path / "mcp-cache"))
    return tmp_path


def _server(transport, **kw):
    return RemoteMCPServer(name="fake", transport=transport, cache=True, **kw)


# ── the cache module ──────────────────────────────────────────────────────────


def test_save_then_load_roundtrips(cache_home):
    tools = [{"name": "a", "remote_name": "a", "description": "d",
              "input_schema": {}, "output_schema": {}, "title": "", "annotations": {}, "execution": {}}]
    sc.save("srv", "fp1", tools, saved_at=1000.0)
    assert sc.load("srv", "fp1", ttl=1e12) == tools


def test_load_miss_on_absent_file(cache_home):
    assert sc.load("srv", "nope") is None


def test_load_miss_on_ttl_expiry(cache_home, monkeypatch):
    sc.save("srv", "fp", [{"name": "a"}], saved_at=0.0)
    monkeypatch.setattr(sc.time, "time", lambda: 10_000.0)
    assert sc.load("srv", "fp", ttl=100.0) is None      # 10000s old, 100s ttl


def test_corrupt_cache_is_a_miss_not_a_crash(cache_home):
    sc.save("srv", "fp", [{"name": "a"}], saved_at=1.0)
    path = sc._path_for("srv", "fp")
    path.write_text("{ this is not json", encoding="utf-8")
    assert sc.load("srv", "fp", ttl=1e9) is None         # no exception


def test_env_values_are_not_written_to_disk(cache_home):
    fp = sc.fingerprint(name="s", identity="stdio:x", protocol_version="v",
                        allowed=None, blocked=set(), include_server_in_tool_names=False,
                        env={"SECRET_TOKEN": "hunter2"})
    sc.save("s", fp, [{"name": "a"}], saved_at=1.0)
    on_disk = sc._path_for("s", fp).read_text(encoding="utf-8")
    assert "hunter2" not in on_disk and "SECRET_TOKEN" not in on_disk


def test_fingerprint_is_stable_and_config_sensitive():
    base = dict(name="s", identity="stdio:cmd", protocol_version="2025-11-25",
                allowed=None, blocked=set(), include_server_in_tool_names=False, env=None)
    fp = sc.fingerprint(**base)
    assert fp == sc.fingerprint(**base)                                  # stable
    assert fp != sc.fingerprint(**{**base, "identity": "stdio:other"})   # command
    assert fp != sc.fingerprint(**{**base, "include_server_in_tool_names": True})
    assert fp != sc.fingerprint(**{**base, "blocked": {"x"}})
    assert fp != sc.fingerprint(**{**base, "env": {"K": "v"}})


def test_fingerprint_ignores_set_order():
    a = sc.fingerprint(name="s", identity="i", protocol_version="v",
                       allowed={"a", "b", "c"}, blocked=set(),
                       include_server_in_tool_names=False, env=None)
    b = sc.fingerprint(name="s", identity="i", protocol_version="v",
                       allowed={"c", "b", "a"}, blocked=set(),
                       include_server_in_tool_names=False, env=None)
    assert a == b


# ── lazy register on the server ───────────────────────────────────────────────


def test_cold_start_discovers_live_and_writes_cache(cache_home):
    t = RecordingTransport()
    tools = _server(t).discover_tools()
    assert [x.name for x in tools] == ["do_thing"]
    assert t.calls == ["initialize", "tools/list"]       # live path ran
    # cache now exists for the next run
    assert sc.load("fake", RemoteMCPServer(name="fake", transport=t, cache=True)._cache_fingerprint(),
                   ttl=1e9) is not None


def test_warm_start_is_lazy_zero_transport_traffic(cache_home):
    # Prime the cache with a cold run on one instance.
    _server(RecordingTransport()).discover_tools()

    # A fresh instance (new process would-be) warm-starts from cache.
    warm = RecordingTransport()
    server = _server(warm)
    tools = server.discover_tools()
    assert [x.name for x in tools] == ["do_thing"]
    # THE discriminating assertion: discovering twice touches the transport zero
    # times. A one-call test would pass even without the _lazy_pending guard.
    server.discover_tools()
    assert warm.calls == []
    assert warm.closed == 0


def test_first_tool_call_spawns_and_handshakes_once(cache_home):
    _server(RecordingTransport()).discover_tools()       # prime cache
    warm = RecordingTransport()
    server = _server(warm)
    tool = server.discover_tools()[0]
    assert warm.calls == []                               # still cold

    out = tool.run(ToolContext(prompt=""), x="hi")
    assert out.metadata["ok"] is True
    # Exactly one handshake, then the call. Not two initializes, not zero.
    assert warm.calls == ["initialize", "tools/call"]
    # A subsequent discover is a no-op: initialize() is idempotent once the
    # session is live and the transport hasn't respawned.
    server.discover_tools()
    assert warm.calls == ["initialize", "tools/call"]


def test_unused_server_never_respawns_across_turns(cache_home):
    """close_mcps() runs every turn. A cache-registered server that no tool
    touches must stay lazy turn after turn — never spawning. This is the claim
    the whole feature rests on, so it gets an explicit multi-turn test."""
    _server(RecordingTransport()).discover_tools()          # prime the cache
    t = RecordingTransport()
    server = _server(t)

    for _turn in range(3):
        server.discover_tools()   # start of turn: register from cache, no spawn
        server.close()            # end of turn: close_mcps()
    # Three turns, zero tool calls → the transport was never touched.
    assert t.calls == []
    assert t.closed == 3          # closed each turn, but never spawned


def test_used_then_idle_turn_goes_lazy_again(cache_home):
    _server(RecordingTransport()).discover_tools()          # prime the cache
    t = RecordingTransport()
    server = _server(t)

    # Turn 1: register lazily, call a tool (spawns), close.
    tool = server.discover_tools()[0]
    tool.run(ToolContext(prompt=""), x="hi")
    assert t.calls == ["initialize", "tools/call"]
    server.close()

    # Turn 2: idle — register from cache again, no new spawn.
    server.discover_tools()
    server.close()
    assert t.calls == ["initialize", "tools/call"]          # unchanged: stayed lazy


def test_failed_handshake_surfaces_as_tool_result_and_closes(cache_home):
    _server(RecordingTransport()).discover_tools()       # prime cache
    dead = RecordingTransport(fail_initialize=True)
    server = _server(dead)
    tool = server.discover_tools()[0]

    out = tool.run(ToolContext(prompt=""), x="hi")
    assert out.metadata["ok"] is False and "failed" in out.text  # no crash
    assert dead.closed == 1                                # half-spawn cleaned up
    assert "tools/call" not in dead.calls                 # never reached the call


def test_changed_command_is_a_cache_miss(cache_home):
    _server(RecordingTransport(command=["server-v1"])).discover_tools()   # prime
    other = RecordingTransport(command=["server-v2"])                     # different config
    server = _server(other)
    server.discover_tools()
    assert other.calls == ["initialize", "tools/list"]    # miss → live discovery


def test_tool_filter_bypasses_the_cache(cache_home):
    # A callable filter can't be fingerprinted, so caching is skipped entirely.
    _server(RecordingTransport()).discover_tools()        # prime an unfiltered cache
    filtered = RecordingTransport()
    server = RemoteMCPServer(
        name="fake", transport=filtered, cache=True,
        tool_filter=lambda item: True,
    )
    server.discover_tools()
    assert filtered.calls == ["initialize", "tools/list"]  # live, not from cache
    # Second discover is a no-op (idempotent initialize) — never lazy/cached.
    server.discover_tools()
    assert filtered.calls == ["initialize", "tools/list"]


def test_cache_off_by_default_is_unchanged_behaviour(cache_home):
    t = RecordingTransport()
    server = RemoteMCPServer(name="fake", transport=t)     # cache defaults False
    server.discover_tools()
    server.discover_tools()
    # Old behaviour, unchanged: one live discover; the per-turn re-discover's
    # initialize() is a no-op while the session stays live.
    assert t.calls == ["initialize", "tools/list"]


# ── real subprocess end-to-end (proves it beyond the stub) ────────────────────

_TINY_MCP_SERVER = r"""
import json, sys
def send(o):
    sys.stdout.write(json.dumps(o) + "\n"); sys.stdout.flush()
for line in sys.stdin:
    line = line.strip()
    if not line: continue
    m = json.loads(line); mid, method = m.get("id"), m.get("method")
    if method == "initialize":
        send({"jsonrpc":"2.0","id":mid,"result":{"protocolVersion":"2025-11-25",
              "capabilities":{},"serverInfo":{"name":"tiny"},"instructions":""}})
    elif method == "tools/list":
        send({"jsonrpc":"2.0","id":mid,"result":{"tools":[{"name":"echo",
              "description":"echo","inputSchema":{"type":"object",
              "properties":{"msg":{"type":"string"}}}}]}})
    elif method == "tools/call":
        a = m.get("params",{}).get("arguments",{})
        send({"jsonrpc":"2.0","id":mid,"result":{"content":[{"type":"text",
              "text":"echo:"+str(a.get("msg",""))}],"isError":False}})
    else:
        send({"jsonrpc":"2.0","id":mid,"error":{"code":-32601,"message":"no"}})
"""


def test_real_subprocess_warm_start_defers_the_spawn(cache_home):
    """End-to-end with an actual stdio subprocess, not the stub: a warm start
    builds tools from cache without launching the process, and the first tool
    call is what finally spawns it."""
    import sys

    from shipit_agent.mcp import PersistentMCPSubprocessTransport

    cmd = [sys.executable, "-c", _TINY_MCP_SERVER]

    # Cold run: real spawn, real handshake, cache written.
    cold_t = PersistentMCPSubprocessTransport(cmd)
    cold = RemoteMCPServer(name="tiny", transport=cold_t, cache=True)
    assert [x.name for x in cold.discover_tools()] == ["echo"]
    assert cold_t._process is not None                      # cold path spawned
    cold.close()

    # Warm run: a brand-new transport that must NOT spawn on discover.
    warm_t = PersistentMCPSubprocessTransport(cmd)
    warm = RemoteMCPServer(name="tiny", transport=warm_t, cache=True)
    tool = warm.discover_tools()[0]
    assert tool.name == "echo"
    assert warm_t._process is None                          # ← lazy: no subprocess

    # First real tool call spawns + handshakes + returns.
    out = tool.run(ToolContext(prompt=""), msg="hi")
    assert out.metadata["ok"] is True and out.text == "echo:hi"
    assert warm_t._process is not None                      # now it's live
    warm.close()
