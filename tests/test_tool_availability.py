"""Tool availability gating — a tool whose declared dependency is missing is
hidden from the agent (its schema never costs tokens, the model never wastes a
turn calling it). A tool that declares nothing is always kept, so gating is
backward-compatible.
"""

from __future__ import annotations

import pytest

from shipit_agent.tools import availability
from shipit_agent.tools.availability import (
    clear_cache,
    filter_available,
    is_available,
)
from shipit_agent.tools.base import ToolOutput


@pytest.fixture(autouse=True)
def _clear():
    clear_cache()
    yield
    clear_cache()


class FakeTool:
    """A minimal tool that can declare availability requirements."""

    def __init__(self, name="fake", **reqs):
        self.name = name
        for k, v in reqs.items():
            setattr(self, k, v)

    def schema(self):
        return {"type": "function", "function": {"name": self.name, "parameters": {}}}

    def run(self, context=None, **kwargs):
        return ToolOutput(text="ok", metadata={})


# ── is_available ──────────────────────────────────────────────────────────


def test_no_requirements_is_always_available():
    ok, reason = is_available(FakeTool())
    assert ok and reason == ""


def test_missing_command_is_unavailable():
    ok, reason = is_available(FakeTool(requires_command="definitely-not-a-real-binary-xyz"))
    assert not ok and "not on PATH" in reason


def test_present_command_is_available():
    # Every POSIX box has one of these; use the interpreter itself to be safe.
    import sys, os
    exe = os.path.basename(sys.executable)
    ok, _ = is_available(FakeTool(requires_command=exe))
    # `sys.executable`'s basename is on PATH in CI/dev shells; if not, skip.
    if not ok:
        pytest.skip("interpreter basename not on PATH in this environment")
    assert ok


def test_unset_env_is_unavailable(monkeypatch):
    monkeypatch.delenv("MY_TOOL_KEY", raising=False)
    ok, reason = is_available(FakeTool(requires_env="MY_TOOL_KEY"))
    assert not ok and "MY_TOOL_KEY" in reason


def test_set_env_is_available(monkeypatch):
    monkeypatch.setenv("MY_TOOL_KEY", "x")
    ok, _ = is_available(FakeTool(requires_env="MY_TOOL_KEY"))
    assert ok


def test_check_fn_true_and_false():
    # Distinct names — the probe cache is keyed by tool name (names are unique
    # within a registry), so same-named tools would share a cached result.
    assert is_available(FakeTool("yes", check_fn=lambda: True))[0] is True
    ok, reason = is_available(FakeTool("no", check_fn=lambda: False))
    assert not ok and "check failed" in reason


def test_check_fn_that_raises_is_unavailable():
    def boom():
        raise RuntimeError("probe blew up")

    ok, _ = is_available(FakeTool("boom", check_fn=boom))
    assert not ok  # a raising probe means "unavailable", never crashes gating


def test_multiple_requirements_all_must_pass(monkeypatch):
    monkeypatch.setenv("HAVE_IT", "1")
    tool = FakeTool(requires_env=["HAVE_IT", "MISSING_ONE"])
    ok, reason = is_available(tool)
    assert not ok and "MISSING_ONE" in reason


# ── caching ────────────────────────────────────────────────────────────────


def test_transient_failure_is_suppressed_within_grace(monkeypatch):
    # A probe that fails soon after a success is a flake — serve last-good and
    # keep re-probing; only a failure past the grace window strips the tool.
    clock = {"t": 0.0}
    monkeypatch.setattr(availability, "_now", lambda: clock["t"])
    result = {"ok": True}
    tool = FakeTool("flaky", check_fn=lambda: result["ok"])

    assert is_available(tool)[0] is True          # t=0: succeeds, cached good

    clock["t"] = 35.0                              # past 30s TTL → re-probe
    result["ok"] = False                           # ...and it now fails
    assert is_available(tool)[0] is True           # but within 60s grace → last-good

    clock["t"] = 100.0                             # past the grace window
    assert is_available(tool)[0] is False          # honoured: tool is stripped


def test_recovery_after_grace_is_picked_up(monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr(availability, "_now", lambda: clock["t"])
    result = {"ok": False}
    tool = FakeTool("recovers", check_fn=lambda: result["ok"])

    assert is_available(tool)[0] is False          # starts unavailable
    clock["t"] = 40.0
    result["ok"] = True
    assert is_available(tool)[0] is True            # comes back once the dep appears


def test_command_probe_is_cached(monkeypatch):
    calls = []

    def fake_which(cmd):
        calls.append(cmd)
        return "/usr/bin/thing"

    monkeypatch.setattr(availability.shutil, "which", fake_which)
    tool = FakeTool(requires_command="thing")
    is_available(tool)
    is_available(tool)
    assert calls == ["thing"]  # second call served from cache


# ── filter_available ────────────────────────────────────────────────────────


def test_filter_splits_and_reports():
    good = FakeTool("good")
    bad = FakeTool("bad", requires_command="nope-nope-nope")
    kept, skipped = filter_available([good, bad])
    assert [t.name for t in kept] == ["good"]
    assert skipped[0][0] == "bad" and "not on PATH" in skipped[0][1]


# ── Agent integration ───────────────────────────────────────────────────────


def test_agent_gates_unavailable_tool_by_default():
    from shipit_agent import Agent
    from shipit_agent.llms.simple import ShipitLLM

    good = FakeTool("good")
    bad = FakeTool("bad", requires_command="nope-nope-nope")
    agent = Agent(llm=ShipitLLM(), tools=[good, bad],
                  auto_use_skills=False, auto_project_memory=False, skill_source=None)
    names = {getattr(t, "name", "") for t in agent.tools}
    assert "good" in names and "bad" not in names
    assert agent.metadata["gated_tools"] == [("bad", "'nope-nope-nope' not on PATH")]


def test_agent_gating_can_be_disabled():
    from shipit_agent import Agent
    from shipit_agent.llms.simple import ShipitLLM

    bad = FakeTool("bad", requires_command="nope-nope-nope")
    agent = Agent(llm=ShipitLLM(), tools=[bad], gate_unavailable_tools=False,
                  auto_use_skills=False, auto_project_memory=False, skill_source=None)
    assert any(getattr(t, "name", "") == "bad" for t in agent.tools)


def test_agent_keeps_plain_tools_untouched():
    from shipit_agent import Agent
    from shipit_agent.llms.simple import ShipitLLM

    agent = Agent(llm=ShipitLLM(), tools=[FakeTool("a"), FakeTool("b")],
                  auto_use_skills=False, auto_project_memory=False, skill_source=None)
    assert {t.name for t in agent.tools} == {"a", "b"}
    assert "gated_tools" not in agent.metadata


# ── a real builtin declares availability ─────────────────────────────────────


def test_playwright_tool_declares_a_check_fn():
    from shipit_agent.tools.playwright_browser.playwright_browser_tool import (
        PlaywrightBrowserTool,
    )

    tool = PlaywrightBrowserTool()
    assert callable(getattr(tool, "check_fn", None))
    # Its availability tracks whether the playwright package is importable.
    import importlib.util

    expected = importlib.util.find_spec("playwright") is not None
    assert is_available(tool)[0] == expected
